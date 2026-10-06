"""Booking service — conflict detection, quoting, and lifecycle.

All time inputs are ``datetime`` in UTC.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from flask import current_app
from sqlalchemy import and_, or_
from sqlalchemy.exc import IntegrityError

from ..extensions import db
from ..models import (
    Seat, SeatBooking, ConferenceRoom, RoomBooking, RoomBlock, BookingStatus,
    User, CreditSettings, Operator, OperatorStatus,
    SeatAllocation, AllocationStatus, Location,
)
from . import credit_service


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
    try:
        tz = ZoneInfo(location.timezone or "UTC")
    except Exception:  # noqa: BLE001 - bad/legacy timezone data shouldn't break booking
        tz = ZoneInfo("UTC")
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
    if seat.operator_id and user.operator_id and seat.operator_id != user.operator_id:
        raise BookingError("Seat does not belong to your workspace.")
    _validate_location_hours(seat.location, start, end)
    if check_seat_conflict(seat.id, start, end, booker=user):
        raise BookingError("Seat is unavailable for the selected time.")

    q = quote_seat(seat, start, end)
    booking = SeatBooking(
        operator_id=seat.operator_id or user.operator_id,
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


def quote_room(user: User, room: ConferenceRoom, start: datetime, end: datetime) -> Quote:
    """Credits cover what they can (bonus, complimentary, then purchased); the rest is cash at the
    room's rate, or the booking is refused when the operator turned pay-per-use off."""
    try:
        slots = credit_service.slots_between(start, end)
    except credit_service.CreditError as e:
        raise BookingError(str(e))
    needed = slots * room.credits_per_slot
    hours = Decimal(slots) / 2
    available = credit_service.balance(room.operator_id, **credit_service.subject_for(user))["total"]
    used = min(needed, available)
    shortfall = needed - used
    if shortfall and not CreditSettings.for_operator(room.operator_id).pay_per_use_enabled:
        raise BookingError(f"This booking needs {needed} credits and you have {available}. "
                           "Buy more credits to book it.")
    subtotal = (Decimal(room.cash_rate_per_hour) * hours * Decimal(shortfall) / Decimal(needed)
                ).quantize(Decimal("0.01"))
    return Quote(hours=hours, subtotal=subtotal, credits_used=used, credits_available=available)


def create_room_booking(*, user: User, room: ConferenceRoom, start: datetime, end: datetime,
                        title: str | None = None, attendees: int = 1,
                        notes: str | None = None,
                        recurring_booking_id: int | None = None,
                        for_user: User | None = None,
                        waive_charge: bool = False) -> RoomBooking:
    """``user`` is the actor performing the booking (used for the operator/
    permission check). ``for_user`` is who the meeting is actually for —
    defaults to ``user`` for a normal self-booking. Only an admin actor may
    book on behalf of someone else or waive the charge/credits.
    """
    # First come, first served: bookings of one room queue up on its row lock, and the
    # database's no-overlap rule is the backstop.
    db.session.query(ConferenceRoom.id).filter(ConferenceRoom.id == room.id).with_for_update().first()
    booked_for, q = _prepare_room_booking(user=user, room=room, start=start, end=end, attendees=attendees,
                                          for_user=for_user, waive_charge=waive_charge)

    booking = RoomBooking(
        operator_id=room.operator_id or booked_for.operator_id,
        room_id=room.id,
        user_id=booked_for.id,
        company_id=booked_for.company_id,
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
    try:
        db.session.flush()
        if q.credits_used:
            credit_service.spend(booking.operator_id, **credit_service.subject_for(booked_for),
                                 credits=q.credits_used, booking=booking, actor=user)
        db.session.commit()
    except credit_service.CreditError as e:
        db.session.rollback()
        raise BookingError(str(e))
    except IntegrityError:
        db.session.rollback()
        raise BookingError("Room already booked for this time.")
    return booking


def room_blocked(room_id: int, start: datetime, end: datetime) -> bool:
    return db.session.query(RoomBlock.query.filter(
        RoomBlock.room_id == room_id, RoomBlock.start_at < end, RoomBlock.end_at > start).exists()).scalar()


def _prepare_room_booking(*, user: User, room: ConferenceRoom, start: datetime, end: datetime,
                          attendees: int, for_user: User | None, waive_charge: bool) -> tuple[User, Quote]:
    """Every rule a room booking must pass, in one place, so the live preview and the real booking agree."""
    booked_for = for_user or user
    _validate_window(start, end)
    if not room.is_active:
        raise BookingError("Room is inactive.")
    if room.operator_id and user.operator_id and room.operator_id != user.operator_id:
        raise BookingError("Room does not belong to your workspace.")
    if for_user is not None:
        if not user.is_admin:
            raise BookingError("Only an operator admin/manager can book on behalf of someone else.")
        if room.operator_id and booked_for.operator_id != room.operator_id:
            raise BookingError("That person does not belong to your workspace.")
    if attendees > room.capacity:
        raise BookingError(f"Room capacity is {room.capacity}.")
    try:
        credit_service.slots_between(start, end)
    except credit_service.CreditError as e:
        raise BookingError(str(e))
    _validate_location_hours(room.location, start, end)
    if room_blocked(room.id, start, end):
        raise BookingError("This room is not available at that time.")
    if check_room_conflict(room.id, start, end):
        raise BookingError("Room already booked for this time.")
    if waive_charge and not user.is_admin:
        raise BookingError("Only an operator admin/manager can waive credits/charges.")

    if waive_charge:
        return booked_for, Quote(hours=_hours_between(start, end), subtotal=Decimal("0"),
                                 credits_used=0, credits_available=0)
    q = quote_room(booked_for, room, start, end)
    if not user.is_admin:  # an operator booking for someone is not held to the company's own rules
        try:
            credit_service.check_company_rules(booked_for, q.credits_used, start.date())
        except credit_service.CreditError as e:
            raise BookingError(str(e))
    return booked_for, q


def preview_room(*, user: User, room: ConferenceRoom, start: datetime, end: datetime, attendees: int = 1,
                 for_user: User | None = None, waive_charge: bool = False) -> dict:
    """What booking this room would do, without booking it (drives the calendar's side panel)."""
    try:
        booked_for, q = _prepare_room_booking(user=user, room=room, start=start, end=end, attendees=attendees,
                                              for_user=for_user, waive_charge=waive_charge)
    except BookingError as e:
        return {"ok": False, "message": str(e)}
    needed = 0 if waive_charge else credit_service.slots_between(start, end) * room.credits_per_slot
    breakdown = credit_service.preview_spend(room.operator_id, credit_service.subject_for(booked_for), q.credits_used)
    return {"ok": True, "credits_needed": needed, "credits_used": q.credits_used, "breakdown": breakdown,
            "cash": str(q.subtotal), "hours": str(q.hours), "available": q.credits_available}


# ------------------------------------------------------------- lifecycle --

def cancel_booking(booking, actor: User) -> None:
    """Works for SeatBooking or RoomBooking."""
    if booking.status in {BookingStatus.CANCELLED, BookingStatus.COMPLETED, BookingStatus.NO_SHOW}:
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
        credit_service.refund_booking(booking, actor)

    booking.status = BookingStatus.CANCELLED
    db.session.commit()


_KEEP = object()


def can_manage_booking(booking, actor: User) -> bool:
    """The organiser, an operator admin, or the organiser's company admin."""
    return bool(booking.user_id == actor.id or actor.is_admin
                or (actor.is_company_admin and getattr(booking, "company_id", None) == actor.company_id))


def _local_tz(location):
    from zoneinfo import ZoneInfo
    try:
        return ZoneInfo(location.timezone or "UTC")
    except Exception:  # noqa: BLE001 - bad/legacy timezone data
        return ZoneInfo("UTC")


def _reprice_room_booking(booking: RoomBooking, actor: User, start: datetime, end: datetime) -> None:
    """Give back the credits of the old time, then charge the new one as a fresh booking would be."""
    booked_for = db.session.get(User, booking.user_id)
    if not booking.credits_used and not (booking.total_amount or 0):
        return  # waived or free: stays free
    credit_service.refund_booking(booking, actor)
    db.session.flush()
    q = quote_room(booked_for, booking.room, start, end)
    if not actor.is_admin:
        try:
            credit_service.check_company_rules(booked_for, q.credits_used, start.date())
        except credit_service.CreditError as e:
            raise BookingError(str(e))
    if q.credits_used:
        try:
            credit_service.spend(booking.operator_id, **credit_service.subject_for(booked_for),
                                 credits=q.credits_used, booking=booking, actor=actor)
        except credit_service.CreditError as e:
            raise BookingError(str(e))
    booking.credits_used, booking.total_amount = q.credits_used, q.subtotal


def update_room_booking(booking: RoomBooking, actor: User, *, start: datetime, end: datetime,
                        title=_KEEP, attendees=_KEEP, notes=_KEEP) -> RoomBooking:
    """Change one meeting. A new time is re-checked like a new booking and re-priced in credits."""
    if booking.status != BookingStatus.CONFIRMED:
        raise BookingError("Only upcoming, confirmed meetings can be changed.")
    if not can_manage_booking(booking, actor):
        raise BookingError("You do not have permission to change this booking.")
    now = datetime.utcnow()
    if booking.start_at <= now:
        raise BookingError("This meeting has already started.")
    window = current_app.config["BOOKING_CANCEL_WINDOW_MINUTES"]
    if booking.start_at - now < timedelta(minutes=window) and not actor.is_admin:
        raise BookingError(f"Bookings must be changed at least {window} minutes before start.")

    room = booking.room
    people = booking.attendee_count if attendees is _KEEP or attendees is None else attendees
    if people > room.capacity:
        raise BookingError(f"Room capacity is {room.capacity}.")
    try:
        db.session.query(ConferenceRoom.id).filter(ConferenceRoom.id == room.id).with_for_update().first()
        if (start, end) != (booking.start_at, booking.end_at):
            _validate_window(start, end)
            try:
                credit_service.slots_between(start, end)
            except credit_service.CreditError as e:
                raise BookingError(str(e))
            _validate_location_hours(room.location, start, end)
            if room_blocked(room.id, start, end):
                raise BookingError("This room is not available at that time.")
            if check_room_conflict(room.id, start, end, exclude_id=booking.id):
                raise BookingError("Room already booked for this time.")
            _reprice_room_booking(booking, actor, start, end)
            booking.start_at, booking.end_at = start, end
        booking.attendee_count = people
        if title is not _KEEP:
            booking.title = title
        if notes is not _KEEP:
            booking.notes = notes
        db.session.commit()
    except BookingError:
        db.session.rollback()
        raise
    except IntegrityError:
        db.session.rollback()
        raise BookingError("Room already booked for this time.")
    return booking


def _can_manage_series(series, actor: User) -> bool:
    return bool(series.user_id == actor.id or actor.is_admin
                or (actor.is_company_admin and series.user and series.user.company_id == actor.company_id))


def _future_instances(series) -> list[RoomBooking]:
    return (RoomBooking.query.filter(RoomBooking.recurring_booking_id == series.id,
                                     RoomBooking.status == BookingStatus.CONFIRMED,
                                     RoomBooking.start_at > datetime.utcnow())
            .order_by(RoomBooking.start_at).all())


def cancel_series(series, actor: User) -> dict:
    """Stop the series and cancel its upcoming meetings (those inside a member's cancel window are kept)."""
    if not _can_manage_series(series, actor):
        raise BookingError("You do not have permission to cancel this series.")
    series.is_active = False
    db.session.commit()
    cancelled = kept = 0
    for b in _future_instances(series):
        try:
            cancel_booking(b, actor)
            cancelled += 1
        except BookingError:
            kept += 1
    return {"cancelled": cancelled, "kept": kept}


def update_series(series, actor: User, *, start_time: time, end_time: time, end_date: date | None = None,
                  title=_KEEP, attendees=_KEEP, notes=_KEEP) -> dict:
    """Move every upcoming meeting to a new time of day (and optionally end the series earlier)."""
    from zoneinfo import ZoneInfo
    if not _can_manage_series(series, actor):
        raise BookingError("You do not have permission to change this series.")
    if end_time <= start_time:
        raise BookingError("End time must be after start time.")
    if end_date is not None and end_date < series.start_date:
        raise BookingError("The series cannot end before it starts.")
    series.start_time, series.end_time = start_time, end_time
    if end_date is not None:
        series.end_date = end_date
    db.session.commit()

    tz, utc = _local_tz(series.room.location), ZoneInfo("UTC")
    updated, cancelled, failed = 0, 0, []
    for b in _future_instances(series):
        day = b.start_at.replace(tzinfo=utc).astimezone(tz).date()
        if day > series.end_date:
            try:
                cancel_booking(b, actor)
                cancelled += 1
            except BookingError:
                failed.append(day)
            continue
        new_start = datetime.combine(day, start_time).replace(tzinfo=tz).astimezone(utc).replace(tzinfo=None)
        new_end = datetime.combine(day, end_time).replace(tzinfo=tz).astimezone(utc).replace(tzinfo=None)
        try:
            update_room_booking(b, actor, start=new_start, end=new_end, title=title, attendees=attendees, notes=notes)
            updated += 1
        except BookingError:
            failed.append(day)
    return {"updated": updated, "cancelled": cancelled, "failed": failed}


CHECK_IN_OPENS = timedelta(minutes=15)


def can_check_in(booking, actor: User, now: datetime | None = None) -> bool:
    """Whether this person may check in to this room booking right now."""
    now = now or datetime.utcnow()
    return (booking.status == BookingStatus.CONFIRMED and booking.start_at - CHECK_IN_OPENS <= now < booking.end_at
            and (booking.user_id == actor.id or actor.is_admin
                 or (actor.is_company_admin and booking.company_id == actor.company_id)))


def check_in(booking, now: datetime | None = None) -> None:
    now = now or datetime.utcnow()
    if booking.status != BookingStatus.CONFIRMED:
        raise BookingError("Only confirmed bookings can be checked in.")
    if now < booking.start_at - CHECK_IN_OPENS:
        raise BookingError("Check-in opens 15 minutes before the start.")
    if now >= booking.end_at:
        raise BookingError("This booking has already ended.")
    booking.status = BookingStatus.CHECKED_IN
    db.session.commit()


def release_no_shows(now: datetime | None = None) -> dict:
    """Free rooms nobody checked in to (their credits stay spent) and close finished meetings."""
    now = now or datetime.utcnow()
    released = completed = 0
    for op in (Operator.query.execution_options(skip_operator_filter=True)
               .filter(Operator.status.in_([OperatorStatus.ACTIVE, OperatorStatus.TRIAL])).all()):
        wait = timedelta(minutes=CreditSettings.for_operator(op.id).no_show_minutes)
        rows = (RoomBooking.query.execution_options(skip_operator_filter=True)
                .filter(RoomBooking.operator_id == op.id))
        for b in rows.filter(RoomBooking.status == BookingStatus.CONFIRMED, RoomBooking.start_at <= now - wait).all():
            b.status = BookingStatus.NO_SHOW
            credit_service.forfeit_booking(b)
            released += 1
        for b in rows.filter(RoomBooking.status == BookingStatus.CHECKED_IN, RoomBooking.end_at <= now).all():
            b.status = BookingStatus.COMPLETED
            completed += 1
    db.session.commit()
    return {"released": released, "completed": completed}


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
                try:
                    tz = ZoneInfo(series.room.location.timezone or "UTC")
                except Exception:  # noqa: BLE001 - bad/legacy timezone data shouldn't break materialization
                    tz = ZoneInfo("UTC")
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
