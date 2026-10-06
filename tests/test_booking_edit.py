"""Editing and cancelling single meetings and recurring series."""
import os
from datetime import date, datetime, time, timedelta

os.environ.setdefault("FLASK_ENV", "testing")

import pytest

from app.extensions import db
from app.models import BookingStatus, RecurrencePattern, RecurringRoomBooking, RoomBooking
from app.services.booking_service import (
    BookingError, cancel_series, create_room_booking, update_room_booking, update_series)

from tests.test_requested_workflows import _workspace, app  # noqa: F401


def _at(days, hour):
    return datetime.combine(date.today() + timedelta(days=days), time(hour))


def test_update_single_meeting_moves_time_and_rejects_conflicts(app):
    operator, user, room = _workspace()
    b = create_room_booking(user=user, room=room, start=_at(2, 9), end=_at(2, 10), title="Sync")
    other = create_room_booking(user=user, room=room, start=_at(2, 12), end=_at(2, 13))

    update_room_booking(b, user, start=_at(2, 10), end=_at(2, 11), title="Planning", attendees=3)
    assert (b.start_at, b.end_at, b.title, b.attendee_count) == (_at(2, 10), _at(2, 11), "Planning", 3)

    with pytest.raises(BookingError):
        update_room_booking(b, user, start=_at(2, 12), end=_at(2, 13))
    assert b.start_at == _at(2, 10)
    with pytest.raises(BookingError):
        update_room_booking(b, user, start=_at(2, 10), end=_at(2, 11), attendees=room.capacity + 1)
    assert other.status == BookingStatus.CONFIRMED


def test_cancelled_meeting_cannot_be_edited(app):
    operator, user, room = _workspace()
    b = create_room_booking(user=user, room=room, start=_at(2, 9), end=_at(2, 10))
    b.status = BookingStatus.CANCELLED
    db.session.commit()
    with pytest.raises(BookingError):
        update_room_booking(b, user, start=_at(2, 10), end=_at(2, 11))


def _series(operator, user, room):
    series = RecurringRoomBooking(
        operator_id=operator.id, room_id=room.id, user_id=user.id, pattern=RecurrencePattern.DAILY,
        start_time=time(9), end_time=time(10), start_date=date.today() + timedelta(days=2),
        end_date=date.today() + timedelta(days=4), is_active=True)
    db.session.add(series)
    db.session.flush()
    for d in (2, 3, 4):
        create_room_booking(user=user, room=room, start=_at(d, 9), end=_at(d, 10), recurring_booking_id=series.id)
    return series


def test_update_series_moves_every_upcoming_meeting_and_trims_end_date(app):
    operator, user, room = _workspace()
    series = _series(operator, user, room)

    result = update_series(series, user, start_time=time(14), end_time=time(15),
                           end_date=date.today() + timedelta(days=3))
    assert result == {"updated": 2, "cancelled": 1, "failed": []}
    live = RoomBooking.query.filter_by(recurring_booking_id=series.id, status=BookingStatus.CONFIRMED) \
        .order_by(RoomBooking.start_at).all()
    assert [b.start_at for b in live] == [_at(2, 14), _at(3, 14)]
    assert series.start_time == time(14)


def test_cancel_series_stops_it_and_cancels_upcoming_meetings(app):
    operator, user, room = _workspace()
    series = _series(operator, user, room)

    result = cancel_series(series, user)
    assert result == {"cancelled": 3, "kept": 0}
    assert series.is_active is False
    assert RoomBooking.query.filter_by(recurring_booking_id=series.id, status=BookingStatus.CONFIRMED).count() == 0
