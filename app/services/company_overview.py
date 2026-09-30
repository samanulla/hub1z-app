"""What an operator wants to see about each member company: plan, fee, dues, people, credits."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from ..models import (
    Company, CompanyStatus, CreditAllocation, Invoice, InvoiceStatus, Seat, Subscription, SubscriptionStatus, User,
    UserRole,
)
from . import billing_service, credit_service, gst

STATUS_META = {
    "active": ("Active", "tint-success"), "overdue": ("Payment due", "tint-danger"), "notice": ("On notice", "tint-warn"),
    "prospect": ("Prospect", "tint-info"), "suspended": ("Suspended", "tint-danger"), "churned": ("Churned", "tint-neutral"),
}
FILTER_ORDER = ["active", "overdue", "notice", "prospect", "suspended", "churned"]


def _q(model, operator_id: int):
    return model.query.execution_options(skip_operator_filter=True).filter(model.operator_id == operator_id)


def build(operator_id: int, today: date | None = None) -> dict:
    today = today or date.today()
    companies = _q(Company, operator_id).order_by(Company.name).all()
    ids = [c.id for c in companies] or [0]

    people: dict[int, list] = defaultdict(list)
    for u in _q(User, operator_id).filter(User.company_id.in_(ids)).order_by(User.full_name):
        people[u.company_id].append(u)

    subs: dict[int, list] = defaultdict(list)
    for s in (_q(Subscription, operator_id).filter(Subscription.company_id.in_(ids),
                                                   Subscription.status == SubscriptionStatus.ACTIVE).all()):
        subs[s.company_id].append(s)

    due: dict[int, Decimal] = defaultdict(Decimal)
    overdue_ids: set[int] = set()
    for inv in (_q(Invoice, operator_id).filter(Invoice.company_id.in_(ids),
                                                Invoice.status.in_(billing_service.OPEN_STATUSES)).all()):
        balance = Decimal(inv.balance_due)
        if balance <= 0:
            continue
        due[inv.company_id] += balance
        if inv.due_date and inv.due_date < today:
            overdue_ids.add(inv.company_id)

    allocation = {a.company_id: a.monthly_credits for a in _q(CreditAllocation, operator_id)
                  .filter(CreditAllocation.company_id.in_(ids)).all()}

    cards, counts = [], defaultdict(int)
    seats_in_use, ending_soon = 0, 0
    for c in companies:
        active = subs.get(c.id, [])
        monthly = sum((billing_service.effective_unit_price(s, today) * (s.quantity or 1) for s in active), Decimal("0"))
        seats = sum(s.quantity or 1 for s in active)
        seats_in_use += seats
        ends = None
        on_notice = any(s.terminate_on for s in active)
        for s in active:
            end = s.terminate_on or s.term_ends_on
            if end and (ends is None or end < ends):
                ends = end
        if ends and today <= ends <= today + timedelta(days=60):
            ending_soon += 1
        if c.status == CompanyStatus.ACTIVE:
            key = "overdue" if c.id in overdue_ids else ("notice" if on_notice else "active")
        else:
            key = c.status.value
        counts[key] += 1
        admins = [u for u in people.get(c.id, []) if u.role == UserRole.COMPANY_ADMIN]
        contact = admins[0] if admins else None
        monthly_credits = allocation.get(c.id)
        left = credit_service.balance(operator_id, company_id=c.id)["total"] if monthly_credits is not None else None
        label, tint = STATUS_META[key]
        cards.append({
            "company": c, "key": key, "label": label, "tint": tint,
            "plan": ", ".join(sorted({s.plan.name for s in active})) or None, "seats": seats, "monthly": monthly,
            "due": due.get(c.id, Decimal("0")), "people": len([u for u in people.get(c.id, []) if u.is_active]),
            "contact_name": contact.full_name if contact else None,
            "contact_email": contact.email if contact else c.billing_email,
            "phone": (contact.phone if contact and contact.phone else c.contact_phone),
            "state": gst.STATE_NAMES.get(gst.state_of(c.gst_state, c.tax_id) or ""),
            "ends": ends, "on_notice": on_notice, "sub_id": active[0].id if active else None,
            "credits_left": left, "credits_monthly": monthly_credits,
            "credits_pct": min(100, round(left * 100 / monthly_credits)) if left is not None and monthly_credits else None,
        })

    capacity = _q(Seat, operator_id).count()
    return {
        "cards": cards, "counts": dict(counts), "filters": [(k, STATUS_META[k][0]) for k in FILTER_ORDER if counts.get(k)],
        "total": len(companies), "active": counts.get("active", 0) + counts.get("overdue", 0) + counts.get("notice", 0),
        "seats_in_use": seats_in_use, "seat_capacity": capacity,
        "seats_pct": min(100, round(seats_in_use * 100 / capacity)) if capacity else None,
        "outstanding": sum(due.values(), Decimal("0")), "overdue_companies": counts.get("overdue", 0),
        "ending_soon": ending_soon,
    }
