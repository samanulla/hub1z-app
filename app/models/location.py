"""Location, floor, and amenity models."""
from __future__ import annotations

from sqlalchemy import Column, String, Integer, ForeignKey, Text, Time, Boolean
from sqlalchemy.orm import relationship

from ..extensions import db
from ._mixins import PkMixin, TimestampMixin
from .tenant import TenantScoped


class Location(db.Model, PkMixin, TimestampMixin, TenantScoped):
    __tablename__ = "locations"

    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"),
                       nullable=True, index=True)

    name = Column(String(150), nullable=False, unique=True)
    code = Column(String(20), nullable=False, unique=True)
    address_line1 = Column(String(255), nullable=False)
    address_line2 = Column(String(255))
    city = Column(String(80), nullable=False)
    state = Column(String(80))
    country = Column(String(80), nullable=False, default="US")
    postal_code = Column(String(20))
    timezone = Column(String(64), nullable=False, default="UTC")
    open_time = Column(Time)      # e.g. 07:00
    close_time = Column(Time)     # e.g. 22:00
    is_247 = Column(Boolean, default=False, nullable=False)
    description = Column(Text)
    is_active = Column(Boolean, default=True, nullable=False)

    floors = relationship("Floor", back_populates="location", cascade="all, delete-orphan",
                          order_by="Floor.level")
    seats = relationship("Seat", back_populates="location", cascade="all, delete-orphan")
    rooms = relationship("ConferenceRoom", back_populates="location", cascade="all, delete-orphan")
    amenities = relationship("Amenity", secondary="location_amenities", backref="locations")

    def __repr__(self) -> str:
        return f"<Location {self.code}>"


class Floor(db.Model, PkMixin, TimestampMixin, TenantScoped):
    __tablename__ = "floors"

    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"),
                       nullable=True, index=True)
    location_id = Column(Integer, ForeignKey("locations.id", ondelete="CASCADE"), nullable=False)
    level = Column(Integer, nullable=False)          # e.g. 1, 2, 3
    name = Column(String(80), nullable=False)        # e.g. "Ground", "Level 5 — Sales"
    map_document_id = Column(Integer, ForeignKey("documents.id", ondelete="SET NULL"))

    location = relationship("Location", back_populates="floors")
    map_document = relationship("Document")
    seats = relationship("Seat", back_populates="floor", cascade="all, delete-orphan")
    rooms = relationship("ConferenceRoom", back_populates="floor", cascade="all, delete-orphan")


class Amenity(db.Model, PkMixin):
    __tablename__ = "amenities"
    name = Column(String(80), nullable=False, unique=True)
    icon = Column(String(80))


class LocationAmenity(db.Model):
    __tablename__ = "location_amenities"
    location_id = Column(Integer, ForeignKey("locations.id", ondelete="CASCADE"), primary_key=True)
    amenity_id = Column(Integer, ForeignKey("amenities.id", ondelete="CASCADE"), primary_key=True)
