"""Seat allocations — dedicated desks and private offices assigned to companies or individuals."""
from __future__ import annotations

import enum
from sqlalchemy import Column, Integer, ForeignKey, Enum, Date, CheckConstraint
from sqlalchemy.orm import relationship

from ..extensions import db
from ._mixins import PkMixin, TimestampMixin
from .operator import OperatorScoped


class AllocationStatus(str, enum.Enum):
    ACTIVE = "active"
    PENDING = "pending"
    ENDED = "ended"


class SeatAllocation(db.Model, PkMixin, TimestampMixin, OperatorScoped):
    """A dedicated seat/office assignment. Either to a company (any employee can use)
    or to a specific user (individual member or a named employee)."""
    __tablename__ = "seat_allocations"

    seat_id = Column(Integer, ForeignKey("seats.id", ondelete="CASCADE"), nullable=False, index=True)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="CASCADE"), nullable=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    status = Column(Enum(AllocationStatus), default=AllocationStatus.ACTIVE, nullable=False)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date)  # NULL = open-ended

    seat = relationship("Seat", back_populates="allocations")
    company = relationship("Company", back_populates="allocations")
    user = relationship("User", back_populates="allocations")

    __table_args__ = (
        CheckConstraint(
            "(company_id IS NOT NULL) OR (user_id IS NOT NULL)",
            name="ck_allocation_target_present",
        ),
    )
