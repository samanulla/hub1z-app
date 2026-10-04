"""Invoicing from agreements: advance monthly invoices with GST, late fees, deposits,
yearly rate revisions, and notice / early exit.

Everything takes explicit operator ids so it also runs from scheduled jobs (no request)."""
from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta
from decimal import Decimal

from dateutil.relativedelta import relativedelta

from ..extensions import db
from ..models import (
    BillingSettings, Company, DepositEntry, Invoice, InvoiceLineItem, InvoiceStatus, Operator,
    OperatorStatus, RateRevision, Subscription, SubscriptionStatus, SystemSettings,
)
from . import gst
from .gst import money

OPEN_STATUSES = (InvoiceStatus.ISSUED, InvoiceStatus.PARTIAL, InvoiceStatus.OVERDUE)
FORFEIT_NOTE = "Early exit inside the lock-in: deposit forfeited"
REVERSAL_NOTE = "Notice withdrawn: forfeited deposit restored"


class BillingError(Exception):
    """A billing rule was broken; the message is safe to show to the user."""


def _q(model, operator_id: int):
    return model.query.execution_options(skip_operator_filter=True).filter(model.operator_id == operator_id)


def _operator(operator_id: int | None) -> Operator | None:
    return db.session.get(Operator, operator_id) if operator_id else None


def _month_end(d: date) -> date:
    return d.replace(day=calendar.monthrange(d.year, d.month)[1])


# --------------------------------------------------------------- numbering --

def _prefix() -> str:
    try:
        return (SystemSettings.get().invoice_prefix or "INV").strip() or "INV"
    except Exception:
        return "INV"


def next_invoice_number(operator: Operator | None = None) -> str:
    """Next number for the operator. The operator row is locked until commit so two
    invoices raised at once cannot take the same number."""
    prefix = (operator.invoice_prefix.strip() if operator and operator.invoice_prefix else _prefix())
    ts = datetime.utcnow().strftime("%Y%m")
    q = Invoice.query.execution_options(skip_operator_filter=True).filter(Invoice.number.like(f"{prefix}-{ts}-%"))
    if operator is not None:
        (db.session.query(Operator).execution_options(skip_operator_filter=True)
         .filter(Operator.id == operator.id).with_for_update().first())
        q = q.filter(Invoice.operator_id == operator.id)
    last = q.order_by(Invoice.number.desc()).first()
    seq = 1 if last is None else int(last.number.split("-")[-1]) + 1
    return f"{prefix}-{ts}-{seq:05d}"


# ---------------------------------------------------------------- parties --

def billing_snapshot_for_operator(operator: Operator | None) -> dict:
    """The operator's address and tax identity, frozen onto each invoice."""
    location = operator.primary_location if operator else None
    details = (operator.profile_details or {}) if operator else {}
    address = ", ".join(details[name] for name in ("address_line1", "address_line2", "locality") if details.get(name))
    return {
        "billing_name": (operator.company_legal_name if operator else None),
        "billing_address": address or (location.address_line1 if location else None),
        "billing_city": details.get("city") or (location.city if location else None),
        "billing_state": details.get("state") or (location.state if location else None),
        "billing_country": location.country if location else None,
        "billing_postal_code": details.get("pin_code") or (location.postal_code if location else None),
        "seller_gstin": operator.gstin if operator else None,
        "seller_pan": operator.pan if operator else None,
        "seller_state": gst.state_of(operator.gst_state, operator.gstin) if operator else None,
    }


def buyer_snapshot(company: Company | None) -> dict:
    """The company's tax identity. An individual has none, so the sale is treated as local."""
    if company is None:
        return {}
    return {
        "buyer_gstin": company.tax_id,
        "buyer_pan": company.pan,
        "buyer_state": gst.state_of(company.gst_state, company.tax_id),
    }


# ------------------------------------------------------------ invoice core --

def open_invoice(operator: Operator | None, *, company_id, user_id, subscription_id, period_start: date,
                 period_end: date, due_date: date, status=InvoiceStatus.ISSUED, notes: str | None = None) -> Invoice:
    company = db.session.get(Company, company_id) if company_id else None
    inv = Invoice(
        number=next_invoice_number(operator),
        operator_id=operator.id if operator else None,
        subscription_id=subscription_id, company_id=company_id, user_id=user_id,
        period_start=period_start, period_end=period_end, due_date=due_date,
        issued_at=datetime.utcnow() if status == InvoiceStatus.ISSUED else None,
        status=status, notes=notes,
        currency=operator.currency_code if operator else "INR",
        **billing_snapshot_for_operator(operator), **buyer_snapshot(company),
    )
    db.session.add(inv)
    db.session.flush()
    return inv


def add_line(inv: Invoice, description: str, quantity, unit_price, line_type: str, on: date, *,
             tax_inclusive: bool = False, rate=None) -> InvoiceLineItem:
    """Add a line with GST worked out from the rate in force on ``on``."""
    operator = _operator(inv.operator_id)
    sac = None
    if rate is None:
        rate, sac = gst.rate_for(operator, line_type, on)
    rate = Decimal(rate)
    qty, price = Decimal(quantity), Decimal(unit_price)
    if tax_inclusive and rate:
        amount = money(qty * price / (1 + rate / 100))
        price = money(amount / qty) if qty else price
    else:
        amount = money(qty * price)
    line = InvoiceLineItem(
        operator_id=inv.operator_id, description=description[:255], quantity=qty, unit_price=money(price),
        amount=amount, line_type=line_type, tax_rate=rate, tax_amount=money(amount * rate / 100), sac_code=sac,
    )
    inv.line_items.append(line)
    return line


def recompute_invoice(inv: Invoice) -> None:
    """Totals from the lines, with the GST split into CGST + SGST (same state) or IGST."""
    subtotal = sum((Decimal(li.amount or 0) for li in inv.line_items), Decimal("0"))
    tax = sum((Decimal(li.tax_amount or 0) for li in inv.line_items), Decimal("0"))
    inv.subtotal = money(subtotal)
    inv.tax_amount = money(tax)
    inv.cgst_amount, inv.sgst_amount, inv.igst_amount = gst.split_gst(tax, inv.seller_state, inv.buyer_state)
    inv.total_amount = inv.subtotal + inv.tax_amount


def due_date_for(sub: Subscription, period_start: date, today: date) -> date:
    day = min(sub.due_day or 5, calendar.monthrange(period_start.year, period_start.month)[1])
    return max(period_start.replace(day=day), today)


# ------------------------------------------------------------------ pricing --

def effective_unit_price(sub: Subscription, on: date) -> Decimal:
    """The price per seat on a date: the latest *confirmed* revision, else the original price."""
    rev = (_q(RateRevision, sub.operator_id)
           .filter(RateRevision.subscription_id == sub.id, RateRevision.status == "confirmed",
                   RateRevision.effective_from <= on)
           .order_by(RateRevision.effective_from.desc()).first())
    return Decimal(rev.new_unit_price if rev else sub.unit_price)


def _plan_charge(sub: Subscription, period_start: date, period_end: date, prorate: bool):
    """(description, unit price) for the period, or None when the agreement is not running in it."""
    first = max(period_start, sub.start_date)
    last = period_end
    if sub.terminate_on:
        last = min(last, sub.terminate_on - timedelta(days=1))
    if last < first:
        return None
    price = effective_unit_price(sub, period_start)
    label = f"{sub.plan.name} × {sub.quantity} ({period_start} to {period_end})"
    if prorate:
        month_days = calendar.monthrange(period_start.year, period_start.month)[1]
        days = (last - first).days + 1
        if days < month_days:
            price = money(price * days / month_days)
            label = f"{sub.plan.name} × {sub.quantity} ({first} to {last}, {days} of {month_days} days)"
    return label, price


# ---------------------------------------------------------------- late fees --

def _add_late_fees(inv: Invoice, sub: Subscription, today: date) -> None:
    """Bill late fees on this invoice for the agreement's earlier unpaid invoices."""
    if sub.late_fee_mode == "none" or not Decimal(sub.late_fee_value or 0):
        return
    overdue = (_q(Invoice, sub.operator_id)
               .filter(Invoice.subscription_id == sub.id, Invoice.status.in_(OPEN_STATUSES),
                       Invoice.due_date < today, Invoice.id != inv.id).all())
    for old in overdue:
        if any(li.line_type == "deposit" for li in old.line_items):
            continue
        balance = Decimal(old.balance_due)
        if balance <= 0:
            continue
        start = old.due_date + timedelta(days=sub.late_fee_grace_days or 0)
        if old.late_fee_charged_through and old.late_fee_charged_through > start:
            start = old.late_fee_charged_through
        days = (today - start).days
        if days <= 0:
            continue
        value = Decimal(sub.late_fee_value)
        fee = value * days if sub.late_fee_mode == "per_day" else balance * value / 100 * days / 365
        fee = money(fee)
        if fee <= 0:
            continue
        add_line(inv, f"Late fee on {old.number} ({days} day(s) overdue)", 1, fee, "late_fee", today)
        old.late_fee_charged_through = today


# ------------------------------------------------------ monthly invoicing --

def _generate(sub: Subscription, period_start: date, period_end: date, *, prorate: bool, today: date):
    existing = (_q(Invoice, sub.operator_id)
                .filter(Invoice.subscription_id == sub.id, Invoice.period_start == period_start,
                        Invoice.period_end == period_end,
                        Invoice.status != InvoiceStatus.VOID).first())
    if existing:
        return existing, False
    charge = _plan_charge(sub, period_start, period_end, prorate)
    if charge is None:
        return None, False
    operator = _operator(sub.operator_id)
    inv = open_invoice(operator, company_id=sub.company_id, user_id=sub.user_id, subscription_id=sub.id,
                       period_start=period_start, period_end=period_end,
                       due_date=due_date_for(sub, period_start, today))
    label, price = charge
    add_line(inv, label, sub.quantity or 1, price, "plan", period_start, tax_inclusive=sub.price_includes_tax)
    _add_late_fees(inv, sub, today)
    recompute_invoice(inv)
    return inv, True


def generate_invoice_for_subscription(sub: Subscription, period_start: date, period_end: date, *,
                                      prorate: bool = False, today: date | None = None) -> Invoice | None:
    """One invoice for an agreement and period (idempotent)."""
    inv, _ = _generate(sub, period_start, period_end, prorate=prorate, today=today or date.today())
    db.session.commit()
    return inv


def run_monthly_billing(target_month: date | None = None, today: date | None = None,
                        operator_id: int | None = None, respect_issue_day: bool = True) -> list[Invoice]:
    """Advance invoices for the month. Without ``target_month`` it bills the current month, and only
    from each operator's invoice day onward. Safe to run every day."""
    today = today or date.today()
    if target_month is not None:
        respect_issue_day = False
    period_start = (target_month or today).replace(day=1)
    period_end = _month_end(period_start)
    ops = Operator.query.execution_options(skip_operator_filter=True).filter(
        Operator.status.in_([OperatorStatus.ACTIVE, OperatorStatus.TRIAL]))
    if operator_id is not None:
        ops = ops.filter(Operator.id == operator_id)
    made: list[Invoice] = []
    for op in ops.all():
        settings = BillingSettings.for_operator(op.id)
        if respect_issue_day and today.day < settings.invoice_issue_day:
            continue
        subs = _q(Subscription, op.id).filter(Subscription.status == SubscriptionStatus.ACTIVE).all()
        for sub in subs:
            inv, created = _generate(sub, period_start, period_end, prorate=True, today=today)
            if created:
                made.append(inv)
    db.session.commit()
    return made


# ---------------------------------------------------------------- deposits --

def deposit_balance(sub: Subscription) -> Decimal:
    total = Decimal("0")
    for e in _q(DepositEntry, sub.operator_id).filter(DepositEntry.subscription_id == sub.id):
        total += Decimal(e.amount) if e.entry_type in ("received", "reversal") else -Decimal(e.amount)
    return money(total)


def record_deposit(sub: Subscription, entry_type: str, amount, on: date, note: str | None = None,
                   actor=None, invoice_id: int | None = None) -> DepositEntry:
    amount = money(amount)
    if amount <= 0:
        raise BillingError("Enter an amount greater than zero.")
    if entry_type in ("deduction", "refund") and amount > deposit_balance(sub):
        raise BillingError("That is more than the deposit currently held.")
    entry = DepositEntry(operator_id=sub.operator_id, subscription_id=sub.id, entry_type=entry_type,
                         amount=amount, entry_date=on, note=note, invoice_id=invoice_id,
                         created_by_id=getattr(actor, "id", None))
    db.session.add(entry)
    db.session.flush()
    return entry


def create_deposit_invoice(sub: Subscription, today: date | None = None) -> Invoice | None:
    """The refundable deposit is billed once, with no GST, and counted as held when it is paid."""
    today = today or date.today()
    amount = Decimal(sub.deposit_amount or 0)
    if amount <= 0:
        return None
    if (_q(Invoice, sub.operator_id).join(InvoiceLineItem, InvoiceLineItem.invoice_id == Invoice.id)
            .filter(Invoice.subscription_id == sub.id, InvoiceLineItem.line_type == "deposit").first()):
        return None
    inv = open_invoice(_operator(sub.operator_id), company_id=sub.company_id, user_id=sub.user_id,
                       subscription_id=sub.id, period_start=sub.start_date, period_end=sub.start_date,
                       due_date=max(sub.start_date, today), notes="Refundable security deposit (no GST).")
    add_line(inv, "Refundable security deposit", 1, amount, "deposit", today)
    recompute_invoice(inv)
    return inv


def after_payment(inv: Invoice) -> None:
    """Call after recording a payment: a fully paid deposit invoice puts the deposit on the ledger."""
    if inv.status != InvoiceStatus.PAID or not inv.subscription_id:
        return
    held = sum((Decimal(li.amount) for li in inv.line_items if li.line_type == "deposit"), Decimal("0"))
    if held <= 0:
        return
    if _q(DepositEntry, inv.operator_id).filter(DepositEntry.invoice_id == inv.id).first():
        return
    sub = db.session.get(Subscription, inv.subscription_id)
    if sub is not None:
        record_deposit(sub, "received", held, date.today(), f"Deposit invoice {inv.number} paid", invoice_id=inv.id)


# -------------------------------------------------------- default terms --

def apply_default_terms(sub: Subscription, settings: BillingSettings | None = None) -> None:
    """Start a new agreement from the operator's default terms."""
    st = settings or BillingSettings.for_operator(sub.operator_id)
    sub.term_months = st.term_months
    sub.lock_in_months = st.lock_in_months
    sub.notice_months = st.notice_months
    sub.deposit_refund_days = st.deposit_refund_days
    sub.escalation_percent = st.escalation_percent
    sub.escalation_after_months = st.escalation_after_months
    sub.due_day = st.due_day
    sub.late_fee_mode = st.late_fee_mode
    sub.late_fee_value = st.late_fee_value
    sub.late_fee_grace_days = st.late_fee_grace_days
    sub.early_exit_rule = st.early_exit_rule
    sub.deposit_amount = money(Decimal(sub.unit_price or 0) * (sub.quantity or 1) * st.deposit_months)


# ------------------------------------------------------- rate revisions --

def _revision_anchor(sub: Subscription) -> date:
    last = (_q(RateRevision, sub.operator_id).filter(RateRevision.subscription_id == sub.id)
            .order_by(RateRevision.effective_from.desc()).first())
    if last:
        return last.effective_from + relativedelta(years=1)
    return sub.start_date + relativedelta(months=sub.escalation_after_months or 0)


def propose_revisions(today: date | None = None, operator_id: int | None = None, lead_days: int = 30) -> int:
    """Propose the yearly increase ``lead_days`` before it is due. It is only billed once confirmed."""
    today = today or date.today()
    q = Subscription.query.execution_options(skip_operator_filter=True).filter(
        Subscription.status == SubscriptionStatus.ACTIVE, Subscription.escalation_percent > 0,
        Subscription.escalation_after_months > 0)
    if operator_id is not None:
        q = q.filter(Subscription.operator_id == operator_id)
    made = 0
    for sub in q.all():
        anchor = _revision_anchor(sub)
        if today < anchor - timedelta(days=lead_days):
            continue
        if sub.terminate_on and sub.terminate_on <= anchor:
            continue
        old = effective_unit_price(sub, anchor)
        pct = Decimal(sub.escalation_percent)
        db.session.add(RateRevision(
            operator_id=sub.operator_id, subscription_id=sub.id, effective_from=anchor, percent=pct,
            old_unit_price=old, new_unit_price=money(old * (1 + pct / 100)), status="proposed"))
        made += 1
    db.session.commit()
    return made


def decide_revision(rev: RateRevision, confirm: bool, actor, percent=None) -> None:
    if rev.status != "proposed":
        raise BillingError("This revision has already been decided.")
    if confirm:
        if percent is not None:
            pct = Decimal(percent)
            if pct < 0:
                raise BillingError("The increase cannot be negative.")
            rev.percent = pct
            rev.new_unit_price = money(Decimal(rev.old_unit_price) * (1 + pct / 100))
        rev.status = "confirmed"
    else:
        rev.status = "dismissed"
    rev.decided_by_id = getattr(actor, "id", None)
    rev.decided_at = datetime.utcnow()


# ------------------------------------------------------- notice and exit --

def _months_between(start: date, end: date) -> int:
    """Whole months from ``start`` to ``end``, a part month counting as a month."""
    if end <= start:
        return 0
    rd = relativedelta(end, start)
    return rd.years * 12 + rd.months + (1 if rd.days > 0 else 0)


def give_notice(sub: Subscription, on: date, actor=None) -> dict:
    """Record notice. The agreement ends after the notice period. Leaving inside the lock-in
    costs the remaining lock-in fees or the deposit, as the agreement says."""
    if sub.status != SubscriptionStatus.ACTIVE:
        raise BillingError("Only an active agreement can be given notice.")
    if sub.terminate_on:
        raise BillingError("Notice has already been given on this agreement.")
    ends = on + relativedelta(months=sub.notice_months or 0)
    sub.notice_given_on = on
    sub.terminate_on = ends
    result = {"terminate_on": ends, "early_exit_invoice": None, "forfeited": Decimal("0"), "months": 0}
    months = _months_between(ends, sub.lock_in_ends_on)
    if months <= 0:
        return result
    result["months"] = months
    if sub.early_exit_rule == "forfeit_deposit":
        held = deposit_balance(sub)
        if held > 0:
            record_deposit(sub, "deduction", held, on, FORFEIT_NOTE, actor)
            result["forfeited"] = held
    else:
        price = effective_unit_price(sub, ends)
        inv = open_invoice(_operator(sub.operator_id), company_id=sub.company_id, user_id=sub.user_id,
                           subscription_id=sub.id, period_start=ends, period_end=sub.lock_in_ends_on,
                           due_date=due_date_for(sub, ends, on),
                           notes="Early exit: fees for the remaining lock-in period.")
        add_line(inv, f"Early exit: remaining lock-in fees ({months} month(s), {ends} to {sub.lock_in_ends_on})",
                 months * (sub.quantity or 1), price, "early_exit", on)
        recompute_invoice(inv)
        result["early_exit_invoice"] = inv
    return result


def withdraw_notice(sub: Subscription, on: date, actor=None) -> dict:
    """Take back a notice. Unpaid early-exit invoices are voided and a forfeited deposit is restored;
    a paid exit charge must be refunded through a credit note instead."""
    if sub.status != SubscriptionStatus.ACTIVE or not sub.terminate_on:
        raise BillingError("There is no notice to withdraw on this agreement.")
    exit_invoices = (_q(Invoice, sub.operator_id).join(InvoiceLineItem, InvoiceLineItem.invoice_id == Invoice.id)
                     .filter(Invoice.subscription_id == sub.id, InvoiceLineItem.line_type == "early_exit",
                             Invoice.status != InvoiceStatus.VOID).distinct().all())
    if any(Decimal(i.amount_paid or 0) > 0 for i in exit_invoices):
        raise BillingError("The early exit charge has been paid. Issue a credit note for it, then withdraw the notice.")
    for inv in exit_invoices:
        inv.status = InvoiceStatus.VOID
    forfeits = _q(DepositEntry, sub.operator_id).filter(
        DepositEntry.subscription_id == sub.id, DepositEntry.note == FORFEIT_NOTE).all()
    reversals = _q(DepositEntry, sub.operator_id).filter(
        DepositEntry.subscription_id == sub.id, DepositEntry.note == REVERSAL_NOTE).count()
    restored = Decimal("0")
    for entry in forfeits[reversals:]:
        record_deposit(sub, "reversal", entry.amount, on, REVERSAL_NOTE, actor)
        restored += Decimal(entry.amount)
    sub.notice_given_on = None
    sub.terminate_on = None
    return {"voided": len(exit_invoices), "restored": restored}


def end_terminated_subscriptions(today: date | None = None, operator_id: int | None = None) -> int:
    today = today or date.today()
    q = Subscription.query.execution_options(skip_operator_filter=True).filter(
        Subscription.status == SubscriptionStatus.ACTIVE, Subscription.terminate_on.isnot(None),
        Subscription.terminate_on <= today)
    if operator_id is not None:
        q = q.filter(Subscription.operator_id == operator_id)
    ended = 0
    for sub in q.all():
        sub.status = SubscriptionStatus.EXPIRED
        sub.end_date = sub.terminate_on
        ended += 1
    db.session.commit()
    return ended


def run_agreement_jobs(today: date | None = None) -> dict:
    """Daily: end agreements whose notice has run out, and propose due rate revisions."""
    return {"ended": end_terminated_subscriptions(today), "proposed": propose_revisions(today)}
