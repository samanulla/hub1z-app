"""Renewals, lock-ins, move-outs, overdue invoices and other things an operator should act on soon.

``operator_alerts`` builds the list shown on the Alerts page and dashboard; ``run_alert_emails`` (hourly, from the
scheduler) emails each new item once: a digest to the operator's team and reminders to the customer.
Every query names the operator, because the scheduler runs without the per-request operator filter.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

from flask import current_app, url_for

from ..extensions import db
from ..models import (AlertNotice, Invoice, InvoiceStatus, Lead, Operator, OperatorStatus, PaymentSubmission,
                      PaymentSubmissionStatus, RateRevision, Subscription, SubscriptionStatus, User, UserRole)
from . import mail_service, parcels
from .formatting import format_inr

RENEWAL_DAYS, LOCK_IN_DAYS, LEAVING_DAYS = 60, 30, 60
SEVERITY_ORDER = {"danger": 0, "warn": 1, "info": 2}
OPEN_INVOICE = [InvoiceStatus.ISSUED, InvoiceStatus.PARTIAL, InvoiceStatus.OVERDUE]


def _who(sub) -> str:
    return sub.company.name if sub.company else (sub.user.full_name if sub.user else "Member")


def _days(d: date, today: date) -> int:
    return (d - today).days


def _in(days: int) -> str:
    return "today" if days == 0 else ("tomorrow" if days == 1 else f"in {days} days")


def subscription_items(operator_id: int, today: date, links: bool = True) -> list[dict]:
    items = []
    subs = Subscription.query.filter(Subscription.operator_id == operator_id,
                                     Subscription.status == SubscriptionStatus.ACTIVE).all()
    for sub in subs:
        href = url_for("admin.subscription_agreement", sub_id=sub.id) if links else None
        who, plan = _who(sub), sub.plan.name
        if sub.terminate_on:
            days = _days(sub.terminate_on, today)
            if 0 <= days <= LEAVING_DAYS:
                refund_by = sub.terminate_on + timedelta(days=sub.deposit_refund_days or 0)
                items.append({"key": f"leaving:{sub.id}:{sub.terminate_on}", "kind": "leaving", "date": sub.terminate_on,
                              "severity": "warn" if days <= 15 else "info", "sub": sub, "href": href,
                              "title": f"{who} moves out {_in(days)}",
                              "detail": f"{plan} · last day {sub.terminate_on:%d %b %Y} · refund deposit by {refund_by:%d %b}"})
            continue
        term_end = sub.term_ends_on
        days = _days(term_end, today)
        if 0 <= days <= RENEWAL_DAYS:
            bucket = 30 if days <= 30 else 60
            items.append({"key": f"renewal{bucket}:{sub.id}:{term_end}", "kind": "renewal", "date": term_end,
                          "severity": "danger" if days <= 15 else ("warn" if days <= 30 else "info"), "sub": sub,
                          "href": href, "title": f"{who}: agreement ends {_in(days)}",
                          "detail": f"{plan} · ends {term_end:%d %b %Y} · renew or confirm the move-out"})
        lock_end = sub.lock_in_ends_on
        days = _days(lock_end, today)
        if 0 <= days <= LOCK_IN_DAYS and sub.lock_in_months:
            items.append({"key": f"lockin:{sub.id}:{lock_end}", "kind": "lock_in", "date": lock_end,
                          "severity": "info", "sub": sub, "href": href,
                          "title": f"{who}: lock-in ends {_in(days)}",
                          "detail": f"{plan} · after {lock_end:%d %b %Y} they can leave with {sub.notice_months} months' notice"})
    revisions = (RateRevision.query.join(Subscription, RateRevision.subscription_id == Subscription.id)
                 .filter(Subscription.operator_id == operator_id, RateRevision.status == "proposed").all())
    for rev in revisions:
        sub = db.session.get(Subscription, rev.subscription_id)
        items.append({"key": f"revision:{rev.id}", "kind": "revision", "date": rev.effective_from, "severity": "warn",
                      "sub": sub, "href": url_for("admin.subscription_agreement", sub_id=sub.id) if links else None,
                      "title": f"{_who(sub)}: rate revision to confirm",
                      "detail": f"{rev.percent}% from {rev.effective_from:%d %b %Y}"})
    return items


def overdue_items(operator_id: int, today: date, links: bool = True) -> list[dict]:
    rows = (Invoice.query.filter(Invoice.operator_id == operator_id, Invoice.status.in_(OPEN_INVOICE),
                                 Invoice.due_date < today).order_by(Invoice.due_date).all())
    items = []
    for inv in rows:
        if Decimal(inv.balance_due) <= 0:
            continue
        late = (today - inv.due_date).days
        who = inv.company.name if inv.company else (inv.user.full_name if inv.user else "Customer")
        items.append({"key": f"overdue:{inv.id}", "kind": "overdue", "date": inv.due_date, "invoice": inv,
                      "severity": "danger", "href": url_for("admin.invoice_detail", invoice_id=inv.id) if links else None,
                      "title": f"{who}: invoice {inv.number} overdue",
                      "detail": f"{format_inr(inv.balance_due)} unpaid · {late} day{'s' if late != 1 else ''} late"})
    return items


def operator_alerts(operator_id: int, today: date | None = None) -> list[dict]:
    """Everything to act on, most urgent first (used in requests: links are built)."""
    today = today or date.today()
    items = subscription_items(operator_id, today) + overdue_items(operator_id, today)
    pending = PaymentSubmission.query.filter(PaymentSubmission.operator_id == operator_id,
                                             PaymentSubmission.status == PaymentSubmissionStatus.PENDING).count()
    if pending:
        items.append({"key": "payments", "kind": "payments", "date": today, "severity": "warn",
                      "href": url_for("admin.invoices_list"), "title": f"{pending} reported payment{'s' if pending != 1 else ''} to confirm",
                      "detail": "Members told you they paid by UPI or bank transfer"})
    stale = parcels.stale_count(operator_id)
    if stale:
        items.append({"key": "parcels", "kind": "parcels", "date": today, "severity": "info",
                      "href": url_for("admin.parcels"), "title": f"{stale} parcel{'s' if stale != 1 else ''} waiting over 3 days",
                      "detail": "Send a reminder or return to sender"})
    follow_ups = Lead.query.filter(Lead.operator_id == operator_id, Lead.stage.notin_(["won", "lost"]),
                                   Lead.next_follow_up.isnot(None), Lead.next_follow_up <= today).count()
    if follow_ups:
        items.append({"key": "leads", "kind": "leads", "date": today, "severity": "info",
                      "href": url_for("admin.leads"), "title": f"{follow_ups} lead follow-up{'s' if follow_ups != 1 else ''} due",
                      "detail": "Call or message them today"})
    return sorted(items, key=lambda i: (SEVERITY_ORDER[i["severity"]], i["date"]))


def customer_agreements(today: date | None = None, **owner) -> list[dict]:
    """A company's or an individual's active agreements, with the dates that matter to them."""
    today = today or date.today()
    rows = Subscription.query.filter_by(status=SubscriptionStatus.ACTIVE, **owner).order_by(Subscription.start_date).all()
    out = []
    for sub in rows:
        end = sub.terminate_on or sub.term_ends_on
        out.append({"sub": sub, "end": end, "days_left": _days(end, today), "leaving": bool(sub.terminate_on),
                    "lock_in_end": sub.lock_in_ends_on, "locked": sub.lock_in_ends_on > today,
                    "virtual_office": sub.plan.plan_type.value == "virtual_office"})
    return out


# --------------------------------------------------------------- emails --

def _sent(operator_id: int) -> set[str]:
    return {k for (k,) in db.session.query(AlertNotice.key).filter(AlertNotice.operator_id == operator_id).all()}


def _send(subject: str, to: str, template: str, **ctx) -> None:
    try:
        mail_service.send(subject, to, template, **ctx)
    except Exception:  # one bad address must not stop the rest
        current_app.logger.exception("alert email to %s failed", to)


def _customer_emails(sub=None, invoice=None) -> list[str]:
    company = (sub.company if sub else invoice.company)
    person = (sub.user if sub else invoice.user)
    if company is not None:
        admins = User.query.filter(User.company_id == company.id, User.role == UserRole.COMPANY_ADMIN,
                                   User.is_active.is_(True)).all()
        return [u.email for u in admins] or ([company.billing_email] if company.billing_email else [])
    return [person.email] if person is not None else []


def run_alert_emails(today: date | None = None) -> dict:
    """Email every new renewal, lock-in, move-out and overdue item once. Safe to run every hour."""
    today = today or date.today()
    sent_digests = sent_customer = 0
    operators = Operator.query.filter(Operator.status.in_([OperatorStatus.ACTIVE, OperatorStatus.TRIAL])).all()
    for op in operators:
        already = _sent(op.id)
        items = subscription_items(op.id, today, links=False) + overdue_items(op.id, today, links=False)
        new = [i for i in items if i["key"] not in already]
        if not new:
            continue
        site = f"https://{op.primary_domain}" if op.primary_domain else ""
        team = User.query.filter(User.operator_id == op.id, User.role.in_([UserRole.SUPER_ADMIN, UserRole.MANAGER]),
                                 User.is_active.is_(True)).all()
        for member in team:
            _send(f"{len(new)} thing{'s' if len(new) != 1 else ''} to act on at {op.name}", member.email,
                  "operator_alerts", operator=op, items=new, site=site)
        sent_digests += bool(team)
        for item in new:
            if item["kind"] == "renewal":
                for email in _customer_emails(sub=item["sub"]):
                    _send(f"Your {op.name} agreement ends on {item['date']:%d %b %Y}", email, "agreement_reminder",
                          operator=op, sub=item["sub"], end=item["date"], site=site)
                    sent_customer += 1
            elif item["kind"] == "overdue":
                inv = item["invoice"]
                path = "/company/invoices" if inv.company_id else "/me/invoices"
                for email in _customer_emails(invoice=inv):
                    _send(f"Payment reminder: invoice {inv.number} from {op.name}", email, "payment_reminder",
                          operator=op, invoice=inv, link=f"{site}{path}")
                    sent_customer += 1
            db.session.add(AlertNotice(operator_id=op.id, key=item["key"], sent_at=datetime.utcnow()))
        db.session.commit()
    return {"digests": sent_digests, "customer": sent_customer}
