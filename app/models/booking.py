"""Seat and conference-room bookings."""
from __future__ import annotations

import enum
from sqlalchemy import Column, Integer, ForeignKey, Enum, DateTime, Numeric, String, Text, Index
from sqlalchemy.orm import relationship

from ..extensions import db
from ._mixins import PkMixin, TimestampMixin
from .tenant import TenantScoped


class BookingStatus(str, enum.Enum):
    CONFIRMED = "confirmed"
    CHECKED_IN = "checked_in"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    NO_SHOW = "no_show"


class SeatBooking(db.Model, PkMixin, TimestampMixin, TenantScoped):
    __tablename__ = "seat_bookings"

    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"),
                       nullable=True, index=True)
    seat_id = Column(Integer, ForeignKey("seats.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="SET NULL"))

    start_at = Column(DateTime, nullable=False, index=True)
    end_at = Column(DateTime, nullable=False, index=True)
    status = Column(Enum(BookingStatus), default=BookingStatus.CONFIRMED, nullable=False)

    total_amount = Column(Numeric(10, 2), default=0)
    notes = Column(Text)

    seat = relationship("Seat", back_populates="bookings")
    user = relationship("User", back_populates="seat_bookings")

    __table_args__ = (
        Index("ix_seat_booking_conflict", "seat_id", "start_at", "end_at"),
    )


class RoomBooking(db.Model, PkMixin, TimestampMixin, TenantScoped):
    __tablename__ = "room_bookings"

    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"),
                       nullable=True, index=True)
    room_id = Column(Integer, ForeignKey("conference_rooms.id", ondelete="CASCADE"), nullable=False, index=True)
    recurring_booking_id = Column(Integer, ForeignKey("recurring_room_bookings.id", ondelete="SET NULL"),
                                   nullable=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="SET NULL"))

    start_at = Column(DateTime, nullable=False, index=True)
    end_at = Column(DateTime, nullable=False, index=True)
    status = Column(Enum(BookingStatus), default=BookingStatus.CONFIRMED, nullable=False)

    attendee_count = Column(Integer, default=1, nullable=False)
    title = Column(String(200))
    notes = Column(Text)

    total_amount = Column(Numeric(10, 2), default=0)
    credits_used = Column(Integer, default=0, nullable=False)

    room = relationship("ConferenceRoom", back_populates="bookings")
    user = relationship("User", back_populates="room_bookings")

    __table_args__ = (
        Index("ix_room_booking_conflict", "room_id", "start_at", "end_at"),
    )
