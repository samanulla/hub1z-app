"""Credit pool, allocation, lots and the monthly cycle.

Every query names its operator explicitly, so these functions behave the same inside a
request and inside a scheduled job (which has no request-scoped operator filter).
"""
from __future__ import annotations

import calendar
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import func

from ..extensions import db
from ..models import (
    BUCKET_PRIORITY, CompanyCreditPolicy, ConferenceRoom, CreditAllocation, CreditBucket, CreditLedger, CreditLot,
    CreditSettings, LedgerType, Operator, OperatorStatus, RoomBooking, RoomCategory, SeatBand, UserRole,
)

SLOT_MINUTES = 30
FREE_BUCKETS = (CreditBucket.BONUS, CreditBucket.PASS, CreditBucket.COMPLIMENTARY)


class CreditError(Exception):
    """A credit rule was broken; the message is safe to show to the user."""


def _q(model, operator_id: int):
    return model.query.execution_options(skip_operator_filter=True).filter(model.operator_id == operator_id)


def _month_start(d: date) -> datetime:
    return datetime(d.year, d.month, 1)


def _next_month_start(d: date) -> datetime:
    return datetime(d.year + (d.month == 12), d.month % 12 + 1, 1)


def _subject(company_id: int | None, user_id: int | None) -> dict:
    return {"company_id": company_id} if company_id else {"user_id": user_id}


def subject_for(user) -> dict:
    """Employees draw on their company's shared pool; individuals on their own."""
    return {"company_id": user.company_id, "user_id": None} if user.company_id else {"company_id": None, "user_id": user.id}


# ------------------------------------------------------------ units --

def slots_between(start: datetime, end: datetime) -> int:
    minutes = (end - start).total_seconds() / 60
    if minutes < SLOT_MINUTES or minutes % SLOT_MINUTES or start.minute % SLOT_MINUTES or start.second:
        raise CreditError("Meeting rooms are booked in 30-minute steps (start on the hour or half hour, minimum 30 minutes).")
    return int(minutes // SLOT_MINUTES)


# ------------------------------------------------- categories / bands --

DEFAULT_CATEGORIES = (("Standard", 1, Decimal("300")), ("Executive", 2, Decimal("700")))


def seed_default_categories(operator_id: int) -> None:
    if _q(RoomCategory, operator_id).count():
        return
    for name, credits, rate in DEFAULT_CATEGORIES:
        db.session.add(RoomCategory(operator_id=operator_id, name=name, credits_per_slot=credits, hourly_rate=rate))
    db.session.flush()


def band_overlaps(operator_id: int, lo: int, hi: int, exclude_id: int | None = None) -> bool:
    q = _q(SeatBand, operator_id).filter(SeatBand.min_seats <= hi, SeatBand.max_seats >= lo)
    if exclude_id:
        q = q.filter(SeatBand.id != exclude_id)
    return db.session.query(q.exists()).scalar()


def suggest_credits(operator_id: int, seats: int) -> int:
    band = (_q(SeatBand, operator_id)
            .filter(SeatBand.min_seats <= seats, SeatBand.max_seats >= seats).first())
    return band.monthly_credits if band else 0


# -------------------------------------------------------------- pool --

def capacity_credits(operator_id: int) -> int:
    """Credits per month if every active room were booked for every bookable slot."""
    return sum(row["credits"] for row in capacity_breakdown(operator_id))


def capacity_breakdown(operator_id: int) -> list[dict]:
    settings = CreditSettings.for_operator(operator_id)
    rows = []
    for room in _q(ConferenceRoom, operator_id).filter_by(is_active=True).all():
        loc = room.location
        if not loc.is_active:
            continue
        if loc.is_247 or not (loc.open_time and loc.close_time):
            slots_per_day = 24 * 60 // SLOT_MINUTES
        else:
            minutes = (loc.close_time.hour * 60 + loc.close_time.minute) - (loc.open_time.hour * 60 + loc.open_time.minute)
            slots_per_day = max(0, minutes // SLOT_MINUTES)
        rows.append({"room": room.name, "location": loc.name, "slots": slots_per_day,
                     "days": settings.capacity_days_per_month, "per_slot": room.credits_per_slot,
                     "credits": slots_per_day * settings.capacity_days_per_month * room.credits_per_slot})
    return rows


def usage_by_subject(operator_id: int, today: date, now: datetime | None = None) -> dict:
    """Free credits used (booking already ended) and reserved (booking still ahead) this month."""
    now = now or datetime.utcnow()
    rows = (db.session.query(CreditLot.company_id, CreditLot.user_id, RoomBooking.end_at, CreditLedger.amount)
            .select_from(CreditLedger)
            .join(CreditLot, CreditLedger.lot_id == CreditLot.id)
            .join(RoomBooking, CreditLedger.room_booking_id == RoomBooking.id)
            .execution_options(skip_operator_filter=True)
            .filter(CreditLedger.operator_id == operator_id,
                    CreditLedger.entry_type.in_([LedgerType.USE, LedgerType.REFUND]),
                    CreditLot.bucket.in_(FREE_BUCKETS),
                    RoomBooking.start_at >= _month_start(today), RoomBooking.start_at < _next_month_start(today))
            .all())
    out: dict = {}
    for company_id, user_id, end_at, amount in rows:
        slot = out.setdefault((company_id, user_id), {"used": 0, "reserved": 0})
        slot["used" if end_at <= now else "reserved"] -= amount
    return out


def committed_credits(operator_id: int) -> int:
    return sum((a.pending_monthly_credits if a.pending_monthly_credits is not None else a.monthly_credits)
               for a in _q(CreditAllocation, operator_id).all())


def pool_summary(operator_id: int, today: date | None = None) -> dict:
    today = today or date.today()
    s = CreditSettings.for_operator(operator_id)
    capacity = capacity_credits(operator_id)
    pool = capacity * s.complimentary_share_pct // 100
    reserve = pool * s.reserve_pct // 100
    committed = committed_credits(operator_id)
    usage = usage_by_subject(operator_id, today)
    used = sum(v["used"] for v in usage.values())
    reserved = sum(v["reserved"] for v in usage.values())
    allocatable = pool - reserve
    return {
        "capacity": capacity, "pool": pool, "reserve": reserve, "allocatable": allocatable,
        "committed": committed, "unallocated": max(0, allocatable - committed),
        "used": used, "reserved": reserved,
        "available": max(0, committed - used - reserved),
        "over": committed > allocatable, "usage": usage,
    }


# -------------------------------------------------------- allocation --

def _lot_exists(operator_id: int, subject: dict, source: str, period: str) -> bool:
    q = _q(CreditLot, operator_id).filter_by(source=source, period=period, **subject)
    return db.session.query(q.exists()).scalar()


def _grant(operator_id: int, subject: dict, bucket: CreditBucket, credits: int, expires_at, source: str,
           period: str | None = None, actor=None, note: str | None = None) -> CreditLot:
    lot = CreditLot(operator_id=operator_id, bucket=bucket, granted=credits, remaining=credits,
                    expires_at=expires_at, source=source, period=period, note=note, **subject)
    db.session.add(lot)
    db.session.flush()
    db.session.add(CreditLedger(operator_id=operator_id, lot_id=lot.id, entry_type=LedgerType.GRANT,
                                amount=credits, actor_id=getattr(actor, "id", None), note=note or source))
    return lot


def grant_monthly(alloc: CreditAllocation, on: date, prorate: bool = False, actor=None) -> CreditLot | None:
    """Idempotent per month. A mid-month joiner gets the rest of the month, rounded down."""
    period = f"{on:%Y-%m}"
    subject = _subject(alloc.company_id, alloc.user_id)
    if _lot_exists(alloc.operator_id, subject, "monthly", period):
        return None
    credits = alloc.monthly_credits
    if prorate:
        days = calendar.monthrange(on.year, on.month)[1]
        credits = credits * (days - on.day + 1) // days
    if credits <= 0:
        if prorate:  # note that this month's grant was decided, so the cycle does not top it up to a full month
            db.session.add(CreditLot(operator_id=alloc.operator_id, bucket=CreditBucket.COMPLIMENTARY, granted=0,
                                     remaining=0, expires_at=_next_month_start(on), source="monthly",
                                     period=period, **subject))
            db.session.flush()
        return None
    return _grant(alloc.operator_id, subject, CreditBucket.COMPLIMENTARY, credits, _next_month_start(on),
                  "monthly", period, actor)


def grant_bonus(operator_id: int, *, company_id=None, user_id=None, credits: int, actor=None,
                note: str | None = None, today: date | None = None) -> CreditLot:
    """A one-off negotiation credit: expires at month end so it never becomes a standing commitment."""
    if credits <= 0:
        raise CreditError("Bonus credits must be more than zero.")
    today = today or date.today()
    return _grant(operator_id, _subject(company_id, user_id), CreditBucket.BONUS, credits,
                  _next_month_start(today), "bonus", actor=actor, note=note or "Bonus credits")


def allocate(operator_id: int, *, company_id=None, user_id=None, monthly: int, actor=None,
             today: date | None = None) -> dict:
    """Give (or change) a monthly allocation from the pool.

    A brand-new allocation starts now (prorated). Changing a running one takes effect on the
    next monthly cycle. Returns {"credits", "warning", "starts"}.
    """
    if monthly < 0:
        raise CreditError("Credits cannot be negative.")
    today = today or date.today()
    s = CreditSettings.for_operator(operator_id)
    subject = _subject(company_id, user_id)
    alloc = _q(CreditAllocation, operator_id).filter_by(**subject).first()

    current = 0 if alloc is None else (alloc.pending_monthly_credits if alloc.pending_monthly_credits is not None
                                       else alloc.monthly_credits)
    committed_after = committed_credits(operator_id) - current + monthly
    allocatable = pool_summary(operator_id, today)["allocatable"]
    over = committed_after > allocatable
    if over and s.pool_mode == "block":
        room = max(0, allocatable - (committed_credits(operator_id) - current))
        raise CreditError(f"Only {room} credits are left to allocate from the pool this month.")
    warning = (f"Allocations ({committed_after}) now exceed the pool available to give away ({allocatable})."
               if over else None)

    if alloc is None:
        alloc = CreditAllocation(operator_id=operator_id, monthly_credits=monthly, **subject)
        db.session.add(alloc)
        db.session.flush()
        grant_monthly(alloc, today, prorate=True, actor=actor)
        return {"credits": monthly, "warning": warning, "starts": "now"}

    if alloc.monthly_credits == 0 and not _lot_exists(operator_id, subject, "monthly", f"{today:%Y-%m}"):
        alloc.monthly_credits, alloc.pending_monthly_credits, alloc.pending_from = monthly, None, None
        grant_monthly(alloc, today, prorate=True, actor=actor)
        return {"credits": monthly, "warning": warning, "starts": "now"}

    alloc.pending_monthly_credits = monthly
    alloc.pending_from = _next_month_start(today).date()
    return {"credits": monthly, "warning": warning, "starts": alloc.pending_from.strftime("%d %b %Y")}


def auto_allocate_for_subscription(sub, actor=None) -> dict | None:
    """First subscription for a company: suggest the allocation from its seat band."""
    if not sub.company_id or _q(CreditAllocation, sub.operator_id).filter_by(company_id=sub.company_id).first():
        return None
    credits = suggest_credits(sub.operator_id, sub.quantity)
    try:
        return allocate(sub.operator_id, company_id=sub.company_id, monthly=credits, actor=actor)
    except CreditError as e:
        allocate(sub.operator_id, company_id=sub.company_id, monthly=0, actor=actor)
        return {"credits": 0, "warning": f"{e} Allocated 0 credits for now.", "starts": "now"}


# ---------------------------------------------------- balance / spend --

def _valid_lots(operator_id: int, subject: dict, now: datetime, lock: bool = False) -> list[CreditLot]:
    q = (_q(CreditLot, operator_id).filter_by(**subject).filter(CreditLot.remaining > 0)
         .filter((CreditLot.expires_at.is_(None)) | (CreditLot.expires_at > now)))
    if lock:
        q = q.with_for_update()
    lots = q.all()
    lots.sort(key=lambda l: (BUCKET_PRIORITY[l.bucket], l.expires_at or datetime.max, l.id))
    return lots


def balance(operator_id: int, *, company_id=None, user_id=None, now: datetime | None = None) -> dict:
    now = now or datetime.utcnow()
    out = {b.value: 0 for b in CreditBucket}
    for lot in _valid_lots(operator_id, _subject(company_id, user_id), now):
        out[lot.bucket.value] += lot.remaining
    out["total"] = sum(out.values())
    return out


def spend(operator_id: int, *, company_id=None, user_id=None, credits: int, booking=None, actor=None,
          now: datetime | None = None) -> list[tuple[CreditLot, int]]:
    """Draw credits down bonus -> pass -> complimentary -> purchased. Locks the lots so two
    bookings can never spend the same credit."""
    if credits <= 0:
        return []
    now = now or datetime.utcnow()
    lots = _valid_lots(operator_id, _subject(company_id, user_id), now, lock=True)
    if sum(l.remaining for l in lots) < credits:
        raise CreditError("Not enough credits.")
    left, taken = credits, []
    for lot in lots:
        if not left:
            break
        take = min(lot.remaining, left)
        lot.remaining -= take
        left -= take
        taken.append((lot, take))
        db.session.add(CreditLedger(operator_id=operator_id, lot_id=lot.id, entry_type=LedgerType.USE,
                                    amount=-take, room_booking_id=getattr(booking, "id", None),
                                    actor_id=getattr(actor, "id", None), note="Room booking"))
    return taken


def refund_booking(booking, actor=None, now: datetime | None = None) -> int:
    """Give a cancelled booking's credits back to the lots they came from (if still valid)."""
    now = now or datetime.utcnow()
    entries = (_q(CreditLedger, booking.operator_id).filter_by(room_booking_id=booking.id)
               .filter(CreditLedger.entry_type.in_([LedgerType.USE, LedgerType.REFUND])).all())
    net: dict[int, int] = {}
    for e in entries:
        net[e.lot_id] = net.get(e.lot_id, 0) + e.amount
    returned = 0
    for lot_id, amount in net.items():
        if amount >= 0:
            continue
        lot = db.session.get(CreditLot, lot_id)
        if lot is None or (lot.expires_at is not None and lot.expires_at <= now):
            continue  # that credit has already expired
        lot.remaining += -amount
        returned += -amount
        db.session.add(CreditLedger(operator_id=booking.operator_id, lot_id=lot.id, entry_type=LedgerType.REFUND,
                                    amount=-amount, room_booking_id=booking.id,
                                    actor_id=getattr(actor, "id", None), note="Booking cancelled"))
    return returned


def preview_spend(operator_id: int, subject: dict, credits: int, now: datetime | None = None) -> list[tuple[str, int]]:
    """What spending would draw from each bucket, without changing anything."""
    left, out = credits, {}
    for lot in _valid_lots(operator_id, subject, now or datetime.utcnow()):
        if not left:
            break
        take = min(lot.remaining, left)
        out[lot.bucket.value] = out.get(lot.bucket.value, 0) + take
        left -= take
    return list(out.items())


def forfeit_booking(booking) -> None:
    """A no-show keeps its credits spent; record that so the history explains why nothing came back."""
    if not booking.credits_used:
        return
    lot_ids = {e.lot_id for e in _q(CreditLedger, booking.operator_id)
               .filter_by(room_booking_id=booking.id, entry_type=LedgerType.USE).all()}
    for lot_id in lot_ids:
        db.session.add(CreditLedger(operator_id=booking.operator_id, lot_id=lot_id, entry_type=LedgerType.FORFEIT,
                                    amount=0, room_booking_id=booking.id, note="No-show: credits not returned"))


# ------------------------------------------------- company booking rules --

def usage_by_employee(operator_id: int, company_id: int, today: date) -> dict[int, int]:
    """Credits each person has used this month from the company's lots (cancellations netted off)."""
    rows = (db.session.query(RoomBooking.user_id, func.sum(CreditLedger.amount))
            .select_from(CreditLedger)
            .join(CreditLot, CreditLedger.lot_id == CreditLot.id)
            .join(RoomBooking, CreditLedger.room_booking_id == RoomBooking.id)
            .execution_options(skip_operator_filter=True)
            .filter(CreditLedger.operator_id == operator_id, CreditLot.company_id == company_id,
                    CreditLedger.entry_type.in_([LedgerType.USE, LedgerType.REFUND]),
                    RoomBooking.start_at >= _month_start(today), RoomBooking.start_at < _next_month_start(today))
            .group_by(RoomBooking.user_id).all())
    return {user_id: -int(total) for user_id, total in rows}


def check_company_rules(user, credits: int, on: date) -> None:
    """The company admin decides who may book rooms with company credits, and how much each person may use
    in the month the meeting falls in (``on``)."""
    if not user.company_id:
        return
    policy = (_q(CompanyCreditPolicy, user.operator_id).filter_by(company_id=user.company_id).first())
    if policy is None or user.role == UserRole.COMPANY_ADMIN:
        return
    if policy.booking_mode == "admin_only" or (policy.booking_mode == "selected" and not user.credit_booking_allowed):
        raise CreditError("Your company admin has not turned on room booking for you. Ask them to enable it.")
    cap = policy.per_employee_monthly_cap
    if cap is not None and credits:
        used = usage_by_employee(user.operator_id, user.company_id, on).get(user.id, 0)
        if used + credits > cap:
            raise CreditError(f"Your company allows {cap} credits per person each month and you have used {used}. "
                              f"This booking needs {credits} more.")


# ------------------------------------------------------ monthly cycle --

def expire_lots(operator_id: int, now: datetime) -> int:
    """Expire finished lots; optionally carry a capped part of last month's complimentary credits over."""
    s = CreditSettings.for_operator(operator_id)
    lots = (_q(CreditLot, operator_id).filter(CreditLot.remaining > 0, CreditLot.expires_at.isnot(None),
                                              CreditLot.expires_at <= now).all())
    for lot in lots:
        left = lot.remaining
        lot.remaining = 0
        db.session.add(CreditLedger(operator_id=operator_id, lot_id=lot.id, entry_type=LedgerType.EXPIRE,
                                    amount=-left, note="Expired"))
        if s.rollover_enabled and lot.bucket == CreditBucket.COMPLIMENTARY and lot.source == "monthly":
            carry = min(left, s.rollover_cap)
            if carry > 0:
                _grant(operator_id, _subject(lot.company_id, lot.user_id), CreditBucket.COMPLIMENTARY, carry,
                       _next_month_start(now.date()), "rollover", f"{now:%Y-%m}", note="Rolled over")
    return len(lots)


def run_cycle(operator_id: int, today: date | None = None) -> dict:
    """Expire old credits, start pending allocation changes, grant this month's credits. Safe to re-run."""
    today = today or date.today()
    expired = expire_lots(operator_id, datetime(today.year, today.month, today.day))
    changed = granted = 0
    for alloc in _q(CreditAllocation, operator_id).all():
        if alloc.pending_monthly_credits is not None and alloc.pending_from and alloc.pending_from <= today:
            alloc.monthly_credits, alloc.pending_monthly_credits, alloc.pending_from = (
                alloc.pending_monthly_credits, None, None)
            changed += 1
        if grant_monthly(alloc, today):
            granted += 1
    db.session.commit()
    return {"expired": expired, "changed": changed, "granted": granted}


def run_all_cycles(today: date | None = None) -> dict:
    totals = {"expired": 0, "changed": 0, "granted": 0}
    for op in (Operator.query.execution_options(skip_operator_filter=True)
               .filter(Operator.status.in_([OperatorStatus.ACTIVE, OperatorStatus.TRIAL])).all()):
        for k, v in run_cycle(op.id, today).items():
            totals[k] += v
    return totals
