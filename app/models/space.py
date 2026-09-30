"""Seat and conference room inventory."""
from __future__ import annotations

import enum
from sqlalchemy import Column, String, Integer, ForeignKey, Enum, Numeric, Boolean, Text
from sqlalchemy.orm import relationship

from ..extensions import db
from ._mixins import PkMixin, TimestampMixin
from .operator import OperatorScoped


class SeatType(str, enum.Enum):
    HOT_DESK = "hot_desk"
    DEDICATED_DESK = "dedicated_desk"
    PRIVATE_OFFICE = "private_office"


class Seat(db.Model, PkMixin, TimestampMixin, OperatorScoped):
    __tablename__ = "seats"

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


class ConferenceRoom(db.Model, PkMixin, TimestampMixin, OperatorScoped):
    __tablename__ = "conference_rooms"

    location_id = Column(Integer, ForeignKey("locations.id", ondelete="CASCADE"), nullable=False, index=True)
    floor_id = Column(Integer, ForeignKey("floors.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(120), nullable=False)
    code = Column(String(30), nullable=False)
    capacity = Column(Integer, nullable=False, default=6)
    hourly_rate = Column(Numeric(10, 2), default=0)  # cash rate when the room has no category
    category_id = Column(Integer, ForeignKey("room_categories.id", ondelete="SET NULL"), nullable=True, index=True)
    is_active = Column(Boolean, default=True, nullable=False)
    cross_location_bookable = Column(Boolean, default=False, nullable=False)
    description = Column(Text)

    location = relationship("Location", back_populates="rooms")
    floor = relationship("Floor", back_populates="rooms")
    category = relationship("RoomCategory", foreign_keys=[category_id])
    bookings = relationship("RoomBooking", back_populates="room", cascade="all, delete-orphan")
    amenities = relationship("RoomAmenity", secondary="room_amenity_link", backref="rooms")

    __table_args__ = (
        db.UniqueConstraint("location_id", "code", name="uq_room_location_code"),
    )

    def __repr__(self) -> str:
        return f"<Room {self.name} cap={self.capacity}>"

    @property
    def credits_per_slot(self) -> int:
        """Credits per 30 minutes; a room without a category costs the Standard rate of 1."""
        return self.category.credits_per_slot if self.category else 1

    @property
    def cash_rate_per_hour(self):
        return self.category.hourly_rate if self.category else (self.hourly_rate or 0)


class RoomAmenity(db.Model, PkMixin, OperatorScoped):
    __tablename__ = "room_amenities"
    __table_args__ = (db.UniqueConstraint("operator_id", "name", name="uq_room_amenities_operator_name"),)
    name = Column(String(80), nullable=False)  # e.g. TV, Whiteboard, VC


class RoomAmenityLink(db.Model):
    __tablename__ = "room_amenity_link"
    room_id = Column(Integer, ForeignKey("conference_rooms.id", ondelete="CASCADE"), primary_key=True)
    amenity_id = Column(Integer, ForeignKey("room_amenities.id", ondelete="CASCADE"), primary_key=True)
