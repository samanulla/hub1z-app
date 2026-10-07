"""Marketplace booking engine: availability rules, capacity, holds, payment/approval state and commission.

Members always come first: the allotment (daily caps) is only a ceiling for marketplace buyers, a slot is
blocked for members only once a marketplace booking is confirmed or held, and every write takes the same
row lock the member booking flow takes (the room row), so the two can never double-book.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

from flask import current_app
from sqlalchemy import func

from ..extensions import db
from ..models import (
    CommissionLedgerEntry, ConferenceRoom, Location, MarketplaceBooking, MarketplaceCustomer,
    MarketplaceListing, OperatorMarketplaceTerms, RoomBlock, RoomBooking,
)
from ..models.booking import BookingStatus
from ..models.marketplace import ACTIVE_BOOKING_STATUSES, CANCELLATION_PRESETS, SOURCE_MARKETPLACE

CENT = Decimal("0.01")
INSTANT_HOLD = timedelta(minutes=30)       # unpaid instant booking
REQUEST_WINDOW = timedelta(hours=24)       # operator decision window
APPROVED_PAY_WINDOW = timedelta(hours=24)  # payment window after approval
MAX_OPEN_HOLDS = 3                         # unpaid/undecided bookings per customer


class MarketplaceError(Exception):
    """A rule the buyer or operator broke; the message is safe to show."""


def enabled() -> bool:
    return bool(current_app.config.get("MARKETPLACE_ENABLED"))


def money(value) -> Decimal:
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def terms_for(operator_id: int) -> OperatorMarketplaceTerms | None:
    return (OperatorMarketplaceTerms.query.execution_options(skip_operator_filter=True)
            .filter_by(operator_id=operator_id).first())


def listing_is_bookable(listing: MarketplaceListing) -> bool:
    terms = terms_for(listing.operator_id)
    return bool(enabled() and listing.status == "live" and terms and terms.enabled and terms.kyc_approved)


def _tz(location: Location) -> ZoneInfo:
    try:
        return ZoneInfo(location.timezone or "UTC")
    except Exception:  # noqa: BLE001 - bad legacy timezone data must not break booking
        return ZoneInfo("UTC")


def to_local(location: Location, value: datetime) -> datetime:
    return value.replace(tzinfo=ZoneInfo("UTC")).astimezone(_tz(location))


def local_to_utc(location: Location, day: date, at: time) -> datetime:
    return datetime.combine(day, at, tzinfo=_tz(location)).astimezone(ZoneInfo("UTC")).replace(tzinfo=None)


def is_member_of(operator_id: int, email: str) -> bool:
    """True when this email already has an active account at the operator (they should book as a member)."""
    from ..models import User
    return db.session.query(User.query.execution_options(skip_operator_filter=True).filter(
        User.operator_id == operator_id, func.lower(User.email) == email.lower().strip(),
        User.is_active.is_(True)).exists()).scalar()


def local_day_bounds_utc(location: Location, day: date) -> tuple[datetime, datetime]:
    tz = _tz(location)

    def utc(d: date) -> datetime:
        return datetime.combine(d, time.min, tzinfo=tz).astimezone(ZoneInfo("UTC")).replace(tzinfo=None)

    return utc(day), utc(day + timedelta(days=1))


def _open_hours_per_day(location: Location) -> Decimal:
    if location.is_247 or not (location.open_time and location.close_time):
        return Decimal(24)
    span = (datetime.combine(date.min, location.close_time) - datetime.combine(date.min, location.open_time))
    return Decimal(span.total_seconds()) / Decimal(3600)


# -------------------------------------------------------------- pricing --

def quote(listing: MarketplaceListing, start: datetime, end: datetime, units: int = 1) -> dict:
    if listing.resource_type == "room":
        quantity = Decimal((end - start).total_seconds()) / Decimal(3600)
    else:
        quantity = Decimal(units)
    subtotal = money(listing.price * quantity)
    gst = money(subtotal * listing.gst_rate_pct / 100)
    return {"subtotal": subtotal, "gst": gst, "total": subtotal + gst}


# ---------------------------------------------------------------- rules --

def _in_windows(listing: MarketplaceListing, location: Location, start: datetime, end: datetime) -> bool:
    windows = listing.availability_windows or []
    if not windows:
        return True
    ls, le = to_local(location, start), to_local(location, end)
    if ls.date() != le.date() and le.time() != time.min:
        return False
    for w in windows:
        if ls.weekday() in w.get("days", range(7)):
            lo = time.fromisoformat(w.get("from", "00:00"))
            hi = time.fromisoformat(w.get("to", "23:59"))
            if lo <= ls.time() and (le.time() <= hi or le.time() == time.min):
                return True
    return False


def validate_request(listing: MarketplaceListing, start: datetime, end: datetime, *, units: int = 1,
                     guests: int = 1, now: datetime | None = None) -> None:
    """Static rules only (no capacity); raises MarketplaceError."""
    now = now or datetime.utcnow()
    if not listing_is_bookable(listing):
        raise MarketplaceError("This listing is not available for booking.")
    if end <= start:
        raise MarketplaceError("End time must be after the start time.")
    if units < 1 or guests < 1:
        raise MarketplaceError("Quantity and guests must be at least 1.")
    location = listing.location
    if start < now + timedelta(hours=listing.min_lead_hours):
        raise MarketplaceError(f"Bookings need at least {listing.min_lead_hours} hours' notice.")
    if listing.resource_type == "room":
        if (end - start) > timedelta(hours=listing.max_length_hours):
            raise MarketplaceError(f"The longest booking is {listing.max_length_hours} hours.")
        room = listing.room
        if room is None or not room.is_active:
            raise MarketplaceError("This room is not available.")
        if guests > room.capacity:
            raise MarketplaceError(f"This room seats {room.capacity}.")
    max_guests = (listing.guest_rules or {}).get("max_guests")
    if max_guests and guests > int(max_guests):
        raise MarketplaceError(f"At most {max_guests} guests are allowed.")
    ls = to_local(location, start)
    if ls.date().isoformat() in (listing.blackout_dates or []):
        raise MarketplaceError("This date is not available.")
    if not _in_windows(listing, location, start, end):
        raise MarketplaceError("That time is outside the available hours.")


def _day_used(listing: MarketplaceListing, day: date, exclude_id: int | None = None) -> tuple[int, Decimal]:
    """Units and hours of this listing's marketplace bookings that occupy the local day."""
    lo, hi = local_day_bounds_utc(listing.location, day)
    q = (MarketplaceBooking.query.execution_options(skip_operator_filter=True)
         .filter(MarketplaceBooking.listing_id == listing.id,
                 MarketplaceBooking.status.in_(("held", "confirmed", "checked_in")),
                 MarketplaceBooking.start_at < hi, MarketplaceBooking.end_at > lo))
    if exclude_id:
        q = q.filter(MarketplaceBooking.id != exclude_id)
    units, hours = 0, Decimal(0)
    for b in q.all():
        units += b.units
        overlap = min(b.end_at, hi) - max(b.start_at, lo)
        hours += Decimal(overlap.total_seconds()) / Decimal(3600)
    return units, hours


def _check_capacity(listing: MarketplaceListing, start: datetime, end: datetime, units: int,
                    exclude_id: int | None = None) -> None:
    """Raise unless the booking fits the caps and (for rooms) nothing else holds the room."""
    location = listing.location
    first = to_local(location, start).date()
    last = to_local(location, end - timedelta(seconds=1)).date()
    day = first
    while day <= last:
        used_units, used_hours = _day_used(listing, day, exclude_id)
        if listing.resource_type == "day_access":
            cap = listing.daily_cap_units
            if cap is not None and used_units + units > cap:
                raise MarketplaceError("No more passes are available for that day.")
        elif listing.daily_cap_hours_pct is not None:
            lo, hi = local_day_bounds_utc(location, day)
            mine = Decimal((min(end, hi) - max(start, lo)).total_seconds()) / Decimal(3600)
            allowed = _open_hours_per_day(location) * Decimal(listing.daily_cap_hours_pct) / 100
            if used_hours + mine > allowed:
                raise MarketplaceError("The room's marketplace hours for that day are fully used.")
        day += timedelta(days=1)
    if listing.resource_type == "room":
        busy = RoomBooking.query.execution_options(skip_operator_filter=True).filter(
            RoomBooking.room_id == listing.room_id, RoomBooking.start_at < end, RoomBooking.end_at > start,
            RoomBooking.status.in_((BookingStatus.CONFIRMED, BookingStatus.CHECKED_IN)))
        blocked = RoomBlock.query.execution_options(skip_operator_filter=True).filter(
            RoomBlock.room_id == listing.room_id, RoomBlock.start_at < end, RoomBlock.end_at > start)
        if exclude_id:
            blocked = blocked.filter(RoomBlock.id.notin_(
                db.session.query(MarketplaceBooking.room_block_id).filter(
                    MarketplaceBooking.id == exclude_id, MarketplaceBooking.room_block_id.isnot(None))))
        if db.session.query(busy.exists()).scalar() or db.session.query(blocked.exists()).scalar():
            raise MarketplaceError("That time is no longer free.")


def _lock(listing: MarketplaceListing) -> None:
    """Same room row lock the member flow takes; day access serialises on the listing row."""
    if listing.resource_type == "room":
        db.session.query(ConferenceRoom.id).filter(ConferenceRoom.id == listing.room_id).with_for_update().first()
    db.session.query(MarketplaceListing.id).filter(MarketplaceListing.id == listing.id).with_for_update().first()


def _hold_slot(booking: MarketplaceBooking, listing: MarketplaceListing) -> None:
    if listing.resource_type != "room" or booking.room_block_id:
        return
    block = RoomBlock(operator_id=booking.operator_id, room_id=listing.room_id, start_at=booking.start_at,
                      end_at=booking.end_at, reason=f"Marketplace booking {booking.code}")
    db.session.add(block)
    db.session.flush()
    booking.room_block_id = block.id


def _release_slot(booking: MarketplaceBooking) -> None:
    if booking.room_block_id:
        block = db.session.get(RoomBlock, booking.room_block_id)
        booking.room_block_id = None
        db.session.flush()
        if block is not None:
            db.session.delete(block)


# --------------------------------------------------------------- booking --

def payment_methods_for(listing: MarketplaceListing) -> list[str]:
    terms = terms_for(listing.operator_id)
    return list(listing.payment_methods or (terms.payment_methods if terms else []) or [])


def create_booking(*, listing: MarketplaceListing, customer: MarketplaceCustomer, start: datetime, end: datetime,
                   idempotency_key: str, payment_method: str, units: int = 1, guests: int = 1,
                   billing_name: str | None = None, billing_gstin: str | None = None,
                   allow_membership_contact: bool = False, now: datetime | None = None) -> MarketplaceBooking:
    now = now or datetime.utcnow()
    existing = MarketplaceBooking.query.execution_options(skip_operator_filter=True).filter_by(
        customer_id=customer.id, idempotency_key=idempotency_key).first()
    if existing:
        return existing
    if not customer.is_active:
        raise MarketplaceError("This account cannot make bookings.")
    if payment_method not in payment_methods_for(listing):
        raise MarketplaceError("That payment option is not offered.")
    validate_request(listing, start, end, units=units, guests=guests, now=now)
    if listing.resource_type == "room":
        units = 1
    open_holds = MarketplaceBooking.query.execution_options(skip_operator_filter=True).filter(
        MarketplaceBooking.customer_id == customer.id, MarketplaceBooking.status.in_(("requested", "held"))).count()
    if open_holds >= MAX_OPEN_HOLDS:
        raise MarketplaceError("Please complete or cancel your pending bookings first.")

    _lock(listing)
    _check_capacity(listing, start, end, units)
    terms = terms_for(listing.operator_id)
    amounts = quote(listing, start, end, units)
    instant = listing.approval_mode == "instant"
    booking = MarketplaceBooking(
        operator_id=listing.operator_id, listing_id=listing.id, customer_id=customer.id,
        idempotency_key=idempotency_key, source=SOURCE_MARKETPLACE, payment_method=payment_method,
        start_at=start, end_at=end, units=units, guests=guests,
        customer_name=customer.full_name, customer_email=customer.email, customer_phone=customer.phone,
        billing_name=billing_name, billing_gstin=billing_gstin, allow_membership_contact=allow_membership_contact,
        id_status="pending_upload" if (listing.guest_rules or {}).get("id_required") else "not_required",
        subtotal=amounts["subtotal"], gst_amount=amounts["gst"], total=amounts["total"],
        commission_pct=terms.commission_pct, cancellation_preset=listing.cancellation_preset,
        status="requested", expires_at=now + REQUEST_WINDOW)
    db.session.add(booking)
    db.session.flush()
    if instant:
        _advance_after_approval(booking, listing, now)
    db.session.commit()
    return booking


def _advance_after_approval(booking: MarketplaceBooking, listing: MarketplaceListing, now: datetime) -> None:
    """Instant booking or operator approval: pay-at-venue confirms now, other methods hold for payment."""
    _hold_slot(booking, listing)
    if booking.payment_method == "pay_at_venue":
        _confirm(booking, now)
    else:
        booking.status = "held"
        booking.expires_at = now + (INSTANT_HOLD if listing.approval_mode == "instant" else APPROVED_PAY_WINDOW)


def _confirm(booking: MarketplaceBooking, now: datetime) -> None:
    booking.status = "confirmed"
    booking.expires_at = None
    if not CommissionLedgerEntry.query.execution_options(skip_operator_filter=True).filter_by(
            booking_id=booking.id, entry_type="accrual").first():
        db.session.add(CommissionLedgerEntry(
            operator_id=booking.operator_id, booking_id=booking.id, entry_type="accrual",
            gross_amount=booking.subtotal, commission_pct=booking.commission_pct,
            amount=money(booking.subtotal * booking.commission_pct / 100), note="Booking confirmed"))


def approve(booking: MarketplaceBooking, now: datetime | None = None) -> MarketplaceBooking:
    now = now or datetime.utcnow()
    if booking.status != "requested":
        raise MarketplaceError("This request has already been handled.")
    listing = booking.listing
    _lock(listing)
    try:
        _check_capacity(listing, booking.start_at, booking.end_at, booking.units, exclude_id=booking.id)
    except MarketplaceError:
        raise MarketplaceError("That slot is no longer free, so the request can't be approved.")
    _advance_after_approval(booking, listing, now)
    db.session.commit()
    return booking


def decline(booking: MarketplaceBooking, reason: str | None = None) -> None:
    if booking.status != "requested":
        raise MarketplaceError("This request has already been handled.")
    booking.status = "declined"
    booking.cancel_reason = (reason or "")[:300] or None
    booking.expires_at = None
    _purge_id(booking)
    db.session.commit()


def submit_payment(booking: MarketplaceBooking, reference: str) -> None:
    if booking.status != "held" or booking.payment_status != "unpaid":
        raise MarketplaceError("No payment is due for this booking.")
    booking.payment_reference = (reference or "").strip()[:120] or None
    if not booking.payment_reference:
        raise MarketplaceError("Enter the payment reference.")
    booking.payment_status = "pending_verification"
    db.session.commit()


def confirm_payment(booking: MarketplaceBooking, now: datetime | None = None) -> None:
    if booking.status != "held" or booking.payment_status == "paid":
        raise MarketplaceError("There is no payment to confirm.")
    booking.payment_status = "paid"
    _confirm(booking, now or datetime.utcnow())
    db.session.commit()


def access_revealed(booking: MarketplaceBooking) -> bool:
    """Address and access instructions are shown only once confirmed and paid (or pay at venue), and, when the
    listing asks for ID, once the operator has approved it."""
    return (booking.status in ("confirmed", "checked_in", "completed")
            and (booking.payment_status == "paid" or booking.payment_method == "pay_at_venue")
            and booking.id_status in ("not_required", "approved"))


# ----------------------------------------------------------- cancellation --

def refund_pct(booking: MarketplaceBooking, by_operator: bool, now: datetime | None = None) -> int:
    if by_operator:
        return 100
    preset = CANCELLATION_PRESETS.get(booking.cancellation_preset, CANCELLATION_PRESETS["flexible"])
    now = now or datetime.utcnow()
    return 100 if booking.start_at - now >= timedelta(hours=preset["free_hours"]) else preset["late_refund_pct"]


def cancel(booking: MarketplaceBooking, *, by_operator: bool, reason: str | None = None,
           now: datetime | None = None, refund_override: int | None = None) -> int:
    """Cancel an upcoming booking and return the refund percentage; commission reverses in proportion."""
    now = now or datetime.utcnow()
    if booking.status not in ACTIVE_BOOKING_STATUSES or booking.status == "checked_in":
        raise MarketplaceError("This booking can't be cancelled.")
    if refund_override is not None:
        pct = max(0, min(100, int(refund_override)))
    else:
        pct = refund_pct(booking, by_operator, now) if booking.status == "confirmed" else 100
    was_paid = booking.payment_status in ("paid", "pending_verification")
    booking.status = "cancelled_operator" if by_operator else "cancelled_customer"
    booking.cancelled_at = now
    booking.cancel_reason = (reason or "")[:300] or None
    booking.expires_at = None
    _release_slot(booking)
    _purge_id(booking)
    if was_paid and booking.payment_status == "paid":
        booking.payment_status = "refunded" if pct == 100 else "part_refunded"
    elif booking.payment_status == "pending_verification":
        booking.payment_status = "unpaid"
    accrued = (db.session.query(func.coalesce(func.sum(CommissionLedgerEntry.amount), 0))
               .execution_options(skip_operator_filter=True)
               .filter(CommissionLedgerEntry.booking_id == booking.id).scalar())
    if accrued and pct:
        db.session.add(CommissionLedgerEntry(
            operator_id=booking.operator_id, booking_id=booking.id, entry_type="reversal",
            gross_amount=-money(booking.subtotal * pct / 100), commission_pct=booking.commission_pct,
            amount=-money(Decimal(accrued) * pct / 100), note=f"Cancelled, {pct}% refunded"))
    db.session.commit()
    return pct


# --------------------------------------------------------------- lifecycle --

def check_in(booking: MarketplaceBooking) -> None:
    if booking.status != "confirmed" or not access_revealed(booking):
        raise MarketplaceError("Only a paid, confirmed booking can be checked in.")
    booking.status = "checked_in"
    db.session.commit()


def mark_no_show(booking: MarketplaceBooking, now: datetime | None = None) -> None:
    if booking.status != "confirmed" or booking.start_at > (now or datetime.utcnow()):
        raise MarketplaceError("A no-show can only be recorded after the start time.")
    booking.status = "no_show"
    booking.customer.reliability_strikes += 1
    _purge_id(booking)
    db.session.commit()


def complete(booking: MarketplaceBooking) -> None:
    if booking.status not in ("confirmed", "checked_in"):
        raise MarketplaceError("This booking can't be completed.")
    booking.status = "completed"
    _purge_id(booking)
    db.session.commit()


def release_expired(now: datetime | None = None) -> int:
    """Free holds and requests nobody paid for or decided on in time."""
    now = now or datetime.utcnow()
    rows = (MarketplaceBooking.query.execution_options(skip_operator_filter=True)
            .filter(MarketplaceBooking.status.in_(("requested", "held")), MarketplaceBooking.expires_at.isnot(None),
                    MarketplaceBooking.expires_at <= now).all())
    for booking in rows:
        booking.status = "expired"
        booking.expires_at = None
        _release_slot(booking)
        _purge_id(booking)
    db.session.commit()
    return len(rows)

# ---------------------------------------------------------- guest ID check --

ID_EXTENSIONS = {"jpg", "jpeg", "png", "pdf"}
ID_MAX_BYTES = 5 * 1024 * 1024


def _purge_id(booking: MarketplaceBooking) -> None:
    """The ID image is only kept while the booking is live."""
    if booking.id_document_key:
        from .storage import storage_service
        try:
            storage_service.delete(booking.id_document_key, scope="operator")
        except Exception:  # noqa: BLE001 - a missing file must not block the booking lifecycle
            current_app.logger.warning("Could not delete marketplace ID %s", booking.id_document_key)
        booking.id_document_key = None


def upload_id(booking: MarketplaceBooking, file_storage) -> None:
    """Guest uploads a photo ID for the operator to review."""
    if booking.id_status == "not_required" or booking.status not in ("requested", "held", "confirmed"):
        raise MarketplaceError("No ID is needed for this booking.")
    if booking.id_status == "approved":
        raise MarketplaceError("Your ID has already been approved.")
    name = (getattr(file_storage, "filename", "") or "").strip()
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext not in ID_EXTENSIONS:
        raise MarketplaceError("Upload a JPG, PNG or PDF.")
    data = file_storage.stream.read(ID_MAX_BYTES + 1)
    if not data or len(data) > ID_MAX_BYTES:
        raise MarketplaceError("The file must be under 5 MB.")
    import io
    from .storage import storage_service
    stored = storage_service.upload(namespace=f"operators/{booking.operator_id}/marketplace-ids", filename=f"id.{ext}",
                                    stream=io.BytesIO(data), content_type=file_storage.mimetype, scope="operator")
    _purge_id(booking)
    booking.id_document_key = stored.key
    booking.id_document_name = f"ID-{booking.code}.{ext}"
    booking.id_status = "pending_review"
    booking.id_reject_reason = None
    db.session.commit()


def review_id(booking: MarketplaceBooking, approve: bool, reason: str | None = None) -> None:
    """Operator approves or rejects the uploaded ID before the guest arrives."""
    if booking.id_status != "pending_review":
        raise MarketplaceError("There is no ID waiting for review.")
    if not approve and not (reason or "").strip():
        raise MarketplaceError("Tell the guest why the ID was not accepted.")
    booking.id_status = "approved" if approve else "rejected"
    booking.id_reviewed_at = datetime.utcnow()
    booking.id_reject_reason = None if approve else reason.strip()[:300]
    db.session.commit()


def reject_id_at_venue(booking: MarketplaceBooking, reason: str, refund_pct_value: int = 0) -> int:
    """The ID doesn't check out when the guest arrives: the booking is cancelled, refund as the operator decides."""
    if booking.status != "confirmed" or booking.id_status == "not_required":
        raise MarketplaceError("This booking can't be turned away for ID.")
    if not (reason or "").strip():
        raise MarketplaceError("Record why the ID was not accepted.")
    booking.id_status = "rejected"
    booking.id_reviewed_at = datetime.utcnow()
    booking.id_reject_reason = reason.strip()[:300]
    return cancel(booking, by_operator=True, reason=f"ID not accepted at the space: {reason.strip()}",
                  refund_override=refund_pct_value)


# ----------------------------------------------------- listing lifecycle --

def set_listing_status(listing: MarketplaceListing, status: str) -> None:
    """Pause or unlist takes effect for new bookings at once; existing bookings are honoured.
    Unlisting also declines requests that haven't been decided."""
    if status not in ("live", "paused", "unlisted", "draft"):
        raise MarketplaceError("Unknown status.")
    listing.status = status
    listing.paused_at = datetime.utcnow() if status in ("paused", "unlisted") else None
    if status == "unlisted":
        for booking in MarketplaceBooking.query.execution_options(skip_operator_filter=True).filter_by(
                listing_id=listing.id, status="requested").all():
            booking.status = "declined"
            booking.cancel_reason = "Listing withdrawn"
    db.session.commit()
