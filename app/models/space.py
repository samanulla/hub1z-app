"""Seat and conference room inventory."""
from __future__ import annotations

import enum
from sqlalchemy import Column, String, Integer, ForeignKey, Enum, Numeric, Boolean, Text
from sqlalchemy.orm import relationship

from ..extensions import db
from ._mixins import PkMixin, TimestampMixin
from .tenant import TenantScoped


class SeatType(str, enum.Enum):
    HOT_DESK = "hot_desk"
    DEDICATED_DESK = "dedicated_desk"
    PRIVATE_OFFICE = "private_office"


class Seat(db.Model, PkMixin, TimestampMixin, TenantScoped):
    __tablename__ = "seats"

    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"),
                       nullable=True, index=True)
    location_id = Column(Integer, ForeignKey("locations.id", ondelete="CASCADE"), nullable=False, index=True)
    floor_id = Column(Integer, ForeignKey("floors.id", ondelete="CASCADE"), nullable=False, index=True)
    code = Column(String(30), nullable=False, index=True)   # e.g. "L5-HD-014"
    seat_type = Column(Enum(SeatType), nullable=False, default=SeatType.HOT_DESK)
    capacity = Column(Integer, default=1, nullable=False)   # for private office
    hourly_rate = Column(Numeric(10, 2), default=0)
    daily_rate = Column(Numeric(10, 2), default=0)
    monthly_rate = Column(Numeric(10, 2), default=0)
    is_active = Column(Boolean, default=True, nullable=False)
    notes = Column(Text)

    location = relationship("Location", back_populates="seats")
    floor = relationship("Floor", back_populates="seats")
    bookings = relationship("SeatBooking", back_populates="seat", cascade="all, delete-orphan")
    allocations = relationship("SeatAllocation", back_populates="seat", cascade="all, delete-orphan")

    __table_args__ = (
        db.UniqueConstraint("location_id", "code", name="uq_seat_location_code"),
    )

    @property
    def is_shared(self) -> bool:
        return self.seat_type == SeatType.HOT_DESK

    def __repr__(self) -> str:
        return f"<Seat {self.code} ({self.seat_type.value})>"


class ConferenceRoom(db.Model, PkMixin, TimestampMixin, TenantScoped):
    __tablename__ = "conference_rooms"

    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"),
                       nullable=True, index=True)
    location_id = Column(Integer, ForeignKey("locations.id", ondelete="CASCADE"), nullable=False, index=True)
    floor_id = Column(Integer, ForeignKey("floors.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(120), nullable=False)
    code = Column(String(30), nullable=False)
    capacity = Column(Integer, nullable=False, default=6)
    hourly_rate = Column(Numeric(10, 2), default=0)
    credit_cost_per_hour = Column(Integer, default=1, nullable=False)  # meeting-room credits
    is_active = Column(Boolean, default=True, nullable=False)
    description = Column(Text)

    location = relationship("Location", back_populates="rooms")
    floor = relationship("Floor", back_populates="rooms")
    bookings = relationship("RoomBooking", back_populates="room", cascade="all, delete-orphan")
    amenities = relationship("RoomAmenity", secondary="room_amenity_link", backref="rooms")

    __table_args__ = (
        db.UniqueConstraint("location_id", "code", name="uq_room_location_code"),
    )

    def __repr__(self) -> str:
        return f"<Room {self.name} cap={self.capacity}>"


class RoomAmenity(db.Model, PkMixin):
    __tablename__ = "room_amenities"
    name = Column(String(80), nullable=False, unique=True)  # e.g. TV, Whiteboard, VC


class RoomAmenityLink(db.Model):
    __tablename__ = "room_amenity_link"
    room_id = Column(Integer, ForeignKey("conference_rooms.id", ondelete="CASCADE"), primary_key=True)
    amenity_id = Column(Integer, ForeignKey("room_amenities.id", ondelete="CASCADE"), primary_key=True)
