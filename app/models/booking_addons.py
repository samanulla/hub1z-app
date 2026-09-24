"""Booking add-ons: waitlist + recurring room bookings."""
from __future__ import annotations

import enum
from datetime import datetime, date

from sqlalchemy import (
    Column, String, DateTime, Date, Integer, ForeignKey, Enum, Time, Boolean,
)
from sqlalchemy.orm import relationship

from ..extensions import db
from ._mixins import PkMixin, TimestampMixin
from .tenant import TenantScoped


class WaitlistStatus(str, enum.Enum):
    WAITING = "waiting"
    NOTIFIED = "notified"
    FULFILLED = "fulfilled"
    CANCELLED = "cancelled"


class RoomWaitlist(db.Model, PkMixin, TimestampMixin, TenantScoped):
    __tablename__ = "room_waitlist"

    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"),
                       nullable=True, index=True)
    room_id = Column(Integer, ForeignKey("conference_rooms.id", ondelete="CASCADE"),
                     nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"),
                     nullable=False, index=True)
    start_at = Column(DateTime, nullable=False, index=True)
    end_at = Column(DateTime, nullable=False)
    status = Column(Enum(WaitlistStatus), nullable=False,
                    default=WaitlistStatus.WAITING, index=True)
    notified_at = Column(DateTime, nullable=True)

    room = relationship("ConferenceRoom", foreign_keys=[room_id])
    user = relationship("User", foreign_keys=[user_id])


class RecurrencePattern(str, enum.Enum):
    DAILY = "daily"
    WEEKLY = "weekly"


class RecurringRoomBooking(db.Model, PkMixin, TimestampMixin, TenantScoped):
    __tablename__ = "recurring_room_bookings"

    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"),
                       nullable=True, index=True)
    room_id = Column(Integer, ForeignKey("conference_rooms.id", ondelete="CASCADE"),
                     nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"),
                     nullable=False, index=True)
    pattern = Column(Enum(RecurrencePattern), nullable=False,
                     default=RecurrencePattern.WEEKLY)
    start_time = Column(Time, nullable=False)
    end_time = Column(Time, nullable=False)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)

    room = relationship("ConferenceRoom", foreign_keys=[room_id])
    user = relationship("User", foreign_keys=[user_id])
    instances = relationship("RoomBooking", backref="recurring_booking",
                             foreign_keys="RoomBooking.recurring_booking_id")
