"""Numbers for the Platform Owner dashboard. Reads across every operator, so it skips the operator filter."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal

from ..models import (
    Company, Invoice, Location, Operator, OperatorStatus, OperatorSubscription, PlatformInvoice,
    PlatformInvoiceStatus, PricingTier, User, UserRole,
)

MONTHS = 12


def _all(model):
    return model.query.execution_options(skip_operator_filter=True)


def _month_start(d: date, back: int = 0) -> date:
    index = d.year * 12 + d.month - 1 - back
    return date(index // 12, index % 12 + 1, 1)


def _pct_change(now: float, before: float):
    if not before:
        return None
    return round((now - before) / before * 100, 1)


def build(today: date | None = None) -> dict:
    today = today or date.today()
    now = datetime.combine(today, datetime.min.time())
    operators = _all(Operator).order_by(Operator.created_at.desc()).all()
    by_id = {o.id: o for o in operators}

    active = [o for o in operators if o.status == OperatorStatus.ACTIVE]
    trials = [o for o in operators if o.status == OperatorStatus.TRIAL]
    week_ago, month_ago, two_months_ago = now - timedelta(days=7), now - timedelta(days=30), now - timedelta(days=60)
    new_30 = sum(1 for o in operators if o.created_at and o.created_at >= month_ago)
    new_prev_30 = sum(1 for o in operators if o.created_at and two_months_ago <= o.created_at < month_ago)
    ending_soon = [o for o in trials if o.trial_ends_at and now <= o.trial_ends_at <= now + timedelta(days=7)]

    # Billed and collected per month, from the platform's own invoices to operators.
    first = _month_start(today, MONTHS - 1)
    billed, collected = defaultdict(Decimal), defaultdict(Decimal)
    invoices = _all(PlatformInvoice).filter(PlatformInvoice.period_start >= first).all()
    for inv in invoices:
        if inv.status == PlatformInvoiceStatus.VOID:
            continue
        key = inv.period_start.replace(day=1)
        billed[key] += Decimal(inv.amount)
        if inv.status == PlatformInvoiceStatus.PAID:
            collected[key] += Decimal(inv.amount)
    month_starts = [_month_start(today, MONTHS - 1 - i) for i in range(MONTHS)]
    this_month, last_month = month_starts[-1], month_starts[-2]

    tier_names = {t.key: t.name for t in _all(PricingTier).all()}
    plan_counts: dict[str, int] = defaultdict(int)
    for o in active + trials:
        plan_counts[tier_names.get(o.plan_tier, (o.plan_tier or "Other").title())] += 1

    recent_invoices = _all(PlatformInvoice).order_by(PlatformInvoice.created_at.desc()).limit(6).all()
    for inv in recent_invoices:
        inv.operator_name = by_id[inv.operator_id].name if inv.operator_id in by_id else "Unknown"

    attention = []
    for o in trials:
        if o.trial_ends_at and o.trial_ends_at <= now + timedelta(days=14):
            days = (o.trial_ends_at.date() - today).days
            attention.append({"operator": o, "kind": "Trial", "when": o.trial_ends_at.date(), "days": days})
    subs = (_all(OperatorSubscription).filter(OperatorSubscription.contract_end_date.isnot(None),
                                              OperatorSubscription.contract_end_date <= today + timedelta(days=30),
                                              OperatorSubscription.contract_end_date >= today - timedelta(days=30))
            .all())
    for s in subs:
        o = by_id.get(s.operator_id)
        if o is not None:
            attention.append({"operator": o, "kind": "Contract", "when": s.contract_end_date,
                              "days": (s.contract_end_date - today).days})
    attention.sort(key=lambda a: a["when"])

    return {
        "today": today,
        "operators_total": len(operators), "operators_new_30": new_30,
        "operators_change": _pct_change(new_30, new_prev_30),
        "active": len(active), "active_share": round(len(active) / len(operators) * 100) if operators else 0,
        "trials": len(trials), "trials_ending_7": len(ending_soon),
        "signed_up_week": sum(1 for o in operators if o.created_at and o.created_at >= week_ago),
        "members": _all(User).filter(User.role.in_([UserRole.EMPLOYEE, UserRole.INDIVIDUAL])).count(),
        "companies": _all(Company).count(), "locations": _all(Location).count(),
        "invoices_total": _all(Invoice).count(),
        "billed_this_month": billed[this_month], "collected_this_month": collected[this_month],
        "collected_change": _pct_change(float(collected[this_month]), float(collected[last_month])),
        "chart": {
            "labels": [m.strftime("%b %y") for m in month_starts],
            "billed": [float(billed[m]) for m in month_starts],
            "collected": [float(collected[m]) for m in month_starts],
        },
        "plans": sorted(plan_counts.items(), key=lambda kv: -kv[1]),
        "recent_invoices": recent_invoices,
        "recent_operators": operators[:6],
        "attention": attention[:8],
    }
