"""Booking service — conflict detection, quoting, and lifecycle.

All time inputs are ``datetime`` in UTC.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from flask import current_app
from sqlalchemy import and_, or_

from ..extensions import db
from ..models import (
    Seat, SeatBooking, ConferenceRoom, RoomBooking, BookingStatus,
    User, Subscription, SubscriptionStatus,
    SeatAllocation, AllocationStatus, Location,
)


class BookingError(Exception):
    """Raised when a booking cannot be created (conflict, policy violation, etc.)."""


@dataclass
class Quote:
    hours: Decimal
    subtotal: Decimal
    credits_used: int
    credits_available: int


# ------------------------------------------------------------------ policy --

def _validate_window(start: datetime, end: datetime) -> None:
    if end <= start:
        raise BookingError("End time must be after start time.")

    now = datetime.utcnow()
    min_advance = current_app.config["BOOKING_MIN_ADVANCE_MINUTES"]
    max_advance = current_app.config["BOOKING_MAX_ADVANCE_DAYS"]

    if start < now - timedelta(minutes=1):
        raise BookingError("Cannot book in the past.")
    if start < now + timedelta(minutes=min_advance):
        raise BookingError(f"Bookings must start at least {min_advance} minutes in advance.")
    if start > now + timedelta(days=max_advance):
        raise BookingError(f"Bookings can be at most {max_advance} days in advance.")


def _hours_between(start: datetime, end: datetime) -> Decimal:
    seconds = (end - start).total_seconds()
    return (Decimal(seconds) / Decimal(3600)).quantize(Decimal("0.01"))


def _validate_location_hours(location: Location, start: datetime, end: datetime) -> None:
    """Ensure the booking window falls inside the location's operating hours.
    Times are compared after converting the UTC window to the location's tz."""
    if location.is_247 or not (location.open_time and location.close_time):
        return
    try:
        from zoneinfo import ZoneInfo
    except ImportError:  # pragma: no cover
        return
    tz = ZoneInfo(location.timezone or "UTC")
    local_start = start.replace(tzinfo=ZoneInfo("UTC")).astimezone(tz)
    local_end = end.replace(tzinfo=ZoneInfo("UTC")).astimezone(tz)
    if local_start.time() < location.open_time or local_end.time() > location.close_time:
        raise BookingError(
            f"Bookings must be between {location.open_time.strftime('%H:%M')} "
            f"and {location.close_time.strftime('%H:%M')} at {location.name}."
        )


def _seat_allocation_conflict(seat_id: int, start: datetime, end: datetime,
                              booker: User | None) -> bool:
    """Return True if an active SeatAllocation blocks this booking.

    A booking is allowed if there is no active allocation overlapping the window,
    OR the booker is the allocated user, OR the booker's company is the allocated
    company."""
    start_d = start.date()
    end_d = end.date()
    allocs = SeatAllocation.query.filter(
        SeatAllocation.seat_id == seat_id,
        SeatAllocation.status == AllocationStatus.ACTIVE,
        SeatAllocation.start_date <= end_d,
        or_(SeatAllocation.end_date.is_(None), SeatAllocation.end_date >= start_d),
    ).all()
    if not allocs:
        return False
    if booker is None:
        return True
    for a in allocs:
        if a.user_id and a.user_id == booker.id:
            return False
        if a.company_id and a.company_id == booker.company_id and booker.company_id:
            return False
    return True


# -------------------------------------------------------------- seat book --

def check_seat_conflict(seat_id: int, start: datetime, end: datetime,
                        exclude_id: int | None = None,
                        booker: User | None = None) -> bool:
    q = SeatBooking.query.filter(
        SeatBooking.seat_id == seat_id,
        SeatBooking.status.in_([BookingStatus.CONFIRMED, BookingStatus.CHECKED_IN]),
        and_(SeatBooking.start_at < end, SeatBooking.end_at > start),
    )
    if exclude_id:
        q = q.filter(SeatBooking.id != exclude_id)
    if db.session.query(q.exists()).scalar():
        return True
    # Also blocked if the seat is exclusively allocated to someone else
    return _seat_allocation_conflict(seat_id, start, end, booker)


def quote_seat(seat: Seat, start: datetime, end: datetime) -> Quote:
    hours = _hours_between(start, end)
    # Simple pricing: hourly * hours (round to nearest hour up)
    rate = Decimal(seat.hourly_rate or 0)
    subtotal = (rate * hours).quantize(Decimal("0.01"))
    return Quote(hours=hours, subtotal=subtotal, credits_used=0, credits_available=0)


def create_seat_booking(*, user: User, seat: Seat, start: datetime, end: datetime,
                        notes: str | None = None) -> SeatBooking:
    _validate_window(start, end)
    if not seat.is_active:
        raise BookingError("Seat is inactive.")
    if seat.tenant_id and user.tenant_id and seat.tenant_id != user.tenant_id:
        raise BookingError("Seat does not belong to your workspace.")
    _validate_location_hours(seat.location, start, end)
    if check_seat_conflict(seat.id, start, end, booker=user):
        raise BookingError("Seat is unavailable for the selected time.")

    q = quote_seat(seat, start, end)
    booking = SeatBooking(
        tenant_id=seat.tenant_id or user.tenant_id,
        seat_id=seat.id,
        user_id=user.id,
        company_id=user.company_id,
        start_at=start,
        end_at=end,
        status=BookingStatus.CONFIRMED,
        total_amount=q.subtotal,
        notes=notes,
    )
    db.session.add(booking)
    db.session.commit()
    return booking


# -------------------------------------------------------------- room book --

def check_room_conflict(room_id: int, start: datetime, end: datetime,
                        exclude_id: int | None = None) -> bool:
    q = RoomBooking.query.filter(
        RoomBooking.room_id == room_id,
        RoomBooking.status.in_([BookingStatus.CONFIRMED, BookingStatus.CHECKED_IN]),
        and_(RoomBooking.start_at < end, RoomBooking.end_at > start),
    )
    if exclude_id:
        q = q.filter(RoomBooking.id != exclude_id)
    return db.session.query(q.exists()).scalar()


def _active_subscription_for(user: User) -> Subscription | None:
    """Return the highest-credit active subscription the user can draw from."""
    q = Subscription.query.filter(Subscription.status == SubscriptionStatus.ACTIVE)
    if user.company_id:
        q = q.filter(or_(Subscription.user_id == user.id,
                         Subscription.company_id == user.company_id))
    else:
        q = q.filter(Subscription.user_id == user.id)
    return q.order_by(Subscription.meeting_credits_balance.desc()).first()


def quote_room(user: User, room: ConferenceRoom, start: datetime, end: datetime) -> Quote:
    hours = _hours_between(start, end)
    hourly_rate = Decimal(room.hourly_rate or 0)

    sub = _active_subscription_for(user)
    credits_available = sub.meeting_credits_balance if sub else 0
    credits_needed = int((hours * room.credit_cost_per_hour).to_integral_value(rounding="ROUND_UP"))
    credits_used = min(credits_needed, credits_available)

    # 1 credit = 1 hour of room use in this model
    billable_hours = max(hours - Decimal(credits_used) / Decimal(room.credit_cost_per_hour or 1),
                         Decimal(0))
    subtotal = (hourly_rate * billable_hours).quantize(Decimal("0.01"))

    return Quote(
        hours=hours,
        subtotal=subtotal,
        credits_used=credits_used,
        credits_available=credits_available,
    )


def create_room_booking(*, user: User, room: ConferenceRoom, start: datetime, end: datetime,
                        title: str | None = None, attendees: int = 1,
                        notes: str | None = None,
                        recurring_booking_id: int | None = None) -> RoomBooking:
    _validate_window(start, end)
    if not room.is_active:
        raise BookingError("Room is inactive.")
    if room.tenant_id and user.tenant_id and room.tenant_id != user.tenant_id:
        raise BookingError("Room does not belong to your workspace.")
    if attendees > room.capacity:
        raise BookingError(f"Room capacity is {room.capacity}.")
    _validate_location_hours(room.location, start, end)
    if check_room_conflict(room.id, start, end):
        raise BookingError("Room already booked for this time.")

    q = quote_room(user, room, start, end)
    booking = RoomBooking(
        tenant_id=room.tenant_id or user.tenant_id,
        room_id=room.id,
        user_id=user.id,
        company_id=user.company_id,
        start_at=start,
        end_at=end,
        status=BookingStatus.CONFIRMED,
        title=title,
        attendee_count=attendees,
        notes=notes,
        total_amount=q.subtotal,
        credits_used=q.credits_used,
        recurring_booking_id=recurring_booking_id,
    )
    db.session.add(booking)

    if q.credits_used:
        sub = _active_subscription_for(user)
        if sub:
            sub.meeting_credits_balance = max(0, sub.meeting_credits_balance - q.credits_used)

    db.session.commit()
    return booking


# ------------------------------------------------------------- lifecycle --

def cancel_booking(booking, actor: User) -> None:
    """Works for SeatBooking or RoomBooking."""
    if booking.status in {BookingStatus.CANCELLED, BookingStatus.COMPLETED}:
        raise BookingError("Booking cannot be cancelled in its current state.")

    is_owner = booking.user_id == actor.id
    is_admin = actor.is_admin or (actor.is_company_admin and booking.company_id == actor.company_id)
    if not (is_owner or is_admin):
        raise BookingError("You do not have permission to cancel this booking.")

    window = current_app.config["BOOKING_CANCEL_WINDOW_MINUTES"]
    if booking.start_at - datetime.utcnow() < timedelta(minutes=window) and not actor.is_admin:
        raise BookingError(f"Bookings must be cancelled at least {window} minutes before start.")

    # Refund credits for room bookings
    if isinstance(booking, RoomBooking) and booking.credits_used:
        sub = _active_subscription_for(booking.user)
        if sub:
            sub.meeting_credits_balance += booking.credits_used

    booking.status = BookingStatus.CANCELLED
    db.session.commit()


def check_in(booking) -> None:
    if booking.status != BookingStatus.CONFIRMED:
        raise BookingError("Only confirmed bookings can be checked in.")
    booking.status = BookingStatus.CHECKED_IN
    db.session.commit()


def complete(booking) -> None:
    booking.status = BookingStatus.COMPLETED
    db.session.commit()


def materialize_recurring_room_bookings(as_of: datetime | None = None,
                                        horizon_days: int = 1) -> int:
    """Create the next day of concrete bookings for active recurring series.

    The operation is idempotent because each generated instance is identified
    by its series and start time. A scheduler can safely run this more than once.
    """
    from zoneinfo import ZoneInfo
    from ..models import RecurringRoomBooking, RecurrencePattern

    now = as_of or datetime.utcnow()
    window_start = now.date()
    window_end = window_start + timedelta(days=horizon_days)
    created = 0

    for series in RecurringRoomBooking.query.filter_by(is_active=True).all():
        first = max(series.start_date, window_start)
        last = min(series.end_date, window_end)
        current = first
        while current <= last:
            matches = (series.pattern == RecurrencePattern.DAILY
                       or current.weekday() == series.start_date.weekday())
            if matches:
                local_start = datetime.combine(current, series.start_time)
                local_end = datetime.combine(current, series.end_time)
                tz = ZoneInfo(series.room.location.timezone or "UTC")
                start = local_start.replace(tzinfo=tz).astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
                end = local_end.replace(tzinfo=tz).astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
                exists = RoomBooking.query.filter_by(
                    recurring_booking_id=series.id, start_at=start,
                ).first()
                if not exists and start >= now:
                    try:
                        create_room_booking(
                            user=series.user, room=series.room, start=start, end=end,
                            title="Recurring room booking", recurring_booking_id=series.id,
                        )
                        created += 1
                    except BookingError:
                        # Conflicts and exhausted/invalid booking windows are
                        # left for the operator to resolve without stopping
                        # other recurring series from being processed.
                        pass
            current += timedelta(days=1)
    return created
