"""Marketplace commission: operator statements and the monthly GST invoice Hub1z raises for it."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func

from ..extensions import db
from ..models import CommissionLedgerEntry, MarketplaceBooking, Operator, PlatformInvoice
from .operator_billing import _invoice, money

ZERO = Decimal("0.00")


def month_start(day: date) -> date:
    return day.replace(day=1)


def next_month(day: date) -> date:
    return (day.replace(day=28) + timedelta(days=4)).replace(day=1)


def previous_month(today: date | None = None) -> date:
    return month_start(month_start(today or date.today()) - timedelta(days=1))


def _bounds(month: date) -> tuple[datetime, datetime]:
    return datetime.combine(month, datetime.min.time()), datetime.combine(next_month(month), datetime.min.time())


def _entries(operator_id: int):
    return CommissionLedgerEntry.query.execution_options(skip_operator_filter=True).filter(
        CommissionLedgerEntry.operator_id == operator_id)


def statement(operator_id: int, month: date) -> dict:
    """Commission accrued in a month, with the bookings behind it."""
    start, end = _bounds(month)
    rows = (_entries(operator_id).filter(CommissionLedgerEntry.created_at >= start, CommissionLedgerEntry.created_at < end)
            .order_by(CommissionLedgerEntry.created_at).all())
    invoices = sorted({r.invoiced_in for r in rows if r.invoiced_in})
    codes = {}
    if rows:
        codes = {b.id: b.code for b in MarketplaceBooking.query.execution_options(skip_operator_filter=True).filter(
            MarketplaceBooking.id.in_({r.booking_id for r in rows})).all()}
    return {"month": month, "gross": money(sum((r.gross_amount for r in rows), ZERO)),
            "commission": money(sum((r.amount for r in rows), ZERO)),
            "bookings": len({r.booking_id for r in rows}), "invoices": invoices,
            "rows": [{"entry": r, "code": codes.get(r.booking_id, "")} for r in rows]}


def history(operator_id: int, months: int = 6, today: date | None = None) -> list[dict]:
    month = month_start(today or date.today())
    out = []
    for _ in range(months):
        out.append(statement(operator_id, month))
        month = month_start(month - timedelta(days=1))
    return out


def pending_total(operator_id: int) -> Decimal:
    """Commission accrued but not yet on an invoice."""
    total = (db.session.query(func.coalesce(func.sum(CommissionLedgerEntry.amount), 0))
             .execution_options(skip_operator_filter=True)
             .filter(CommissionLedgerEntry.operator_id == operator_id,
                     CommissionLedgerEntry.invoiced_in.is_(None)).scalar())
    return money(total)


def generate_invoices(month: date, today: date | None = None) -> list[PlatformInvoice]:
    """One GST invoice per operator for everything accrued up to the end of ``month`` and not invoiced yet.
    A net amount of zero or less carries forward; late cancellations land on the next run."""
    today = today or date.today()
    _, end = _bounds(month)
    operator_ids = [oid for (oid,) in (db.session.query(CommissionLedgerEntry.operator_id).execution_options(
        skip_operator_filter=True).filter(CommissionLedgerEntry.invoiced_in.is_(None),
                                          CommissionLedgerEntry.created_at < end).distinct().all())]
    made = []
    for oid in operator_ids:
        entries = _entries(oid).filter(CommissionLedgerEntry.invoiced_in.is_(None),
                                       CommissionLedgerEntry.created_at < end).with_for_update().all()
        total = money(sum((e.amount for e in entries), ZERO))
        if total <= 0:
            continue
        operator = db.session.get(Operator, oid)
        base = f"commission-{oid}-{month:%Y-%m}"
        n = 1
        while PlatformInvoice.query.filter_by(idempotency_key=base if n == 1 else f"{base}-{n}").first():
            n += 1
        count = len({e.booking_id for e in entries})
        lines = [{"description": f"Hub1z marketplace commission, {month:%B %Y} ({count} booking{'s' if count != 1 else ''})",
                  "amount": total}]
        invoice = _invoice(operator, lines, month, end.date() - timedelta(days=1), "commission",
                           key=base if n == 1 else f"{base}-{n}", today=today)
        for e in entries:
            e.invoiced_in = invoice.number
        made.append(invoice)
    db.session.commit()
    return made
