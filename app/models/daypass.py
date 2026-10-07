"""Day-pass model — a one-day access ticket with a QR code for reception check-in."""
from __future__ import annotations

import enum
import secrets
from datetime import date

from sqlalchemy import Column, String, Date, DateTime, Integer, ForeignKey, Enum
from sqlalchemy.orm import relationship

from ..extensions import db
from ._mixins import PkMixin, TimestampMixin
from .operator import OperatorScoped


class DayPassStatus(str, enum.Enum):
    ISSUED = "issued"
    CHECKED_IN = "checked_in"
    CANCELLED = "cancelled"


class DayPass(db.Model, PkMixin, TimestampMixin, OperatorScoped):
    __tablename__ = "day_passes"

    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"),
                     nullable=False, index=True)
    location_id = Column(Integer, ForeignKey("locations.id", ondelete="CASCADE"),
                         nullable=False, index=True)
    pass_date = Column(Date, nullable=False, default=date.today, index=True)
    code = Column(String(32), nullable=False, unique=True, index=True)
    status = Column(Enum(DayPassStatus), nullable=False,
                    default=DayPassStatus.ISSUED, index=True)
    checked_in_at = Column(DateTime, nullable=True)
    booking_source = Column(String(24), nullable=False, default="operator_member", server_default="operator_member")

    user = relationship("User", foreign_keys=[user_id])
    location = relationship("Location", foreign_keys=[location_id])

    @staticmethod
    def new_code() -> str:
        return secrets.token_urlsafe(9)  # ~12 char short code
