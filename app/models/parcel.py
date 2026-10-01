"""Mail and parcels received at reception for a member or a company."""
from __future__ import annotations

import secrets
from datetime import datetime

from sqlalchemy import Column, String, Integer, ForeignKey, DateTime, Index
from sqlalchemy.orm import relationship

from ..extensions import db
from ._mixins import PkMixin, TimestampMixin
from .operator import OperatorScoped

PARCEL_KINDS = [("parcel", "Parcel"), ("letter", "Letter"), ("document", "Courier document"),
                ("food", "Food delivery"), ("other", "Other")]
WAITING, COLLECTED, RETURNED = "waiting", "collected", "returned"


class Parcel(db.Model, PkMixin, TimestampMixin, OperatorScoped):
    __tablename__ = "parcels"
    __table_args__ = (Index("ix_parcels_operator_status", "operator_id", "status"),)

    location_id = Column(Integer, ForeignKey("locations.id", ondelete="SET NULL"), nullable=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="CASCADE"), nullable=True, index=True)
    kind = Column(String(20), nullable=False, default="parcel")
    carrier = Column(String(60))
    reference = Column(String(120))        # tracking or AWB number
    sender = Column(String(120))
    note = Column(String(255))
    received_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    received_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    status = Column(String(12), nullable=False, default=WAITING)
    pickup_code = Column(String(6), nullable=False, default=lambda: f"{secrets.randbelow(10**6):06d}")
    notified_at = Column(DateTime)
    collected_at = Column(DateTime)
    collected_by = Column(String(120))     # who took it, as told to reception
    handed_over_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    location = relationship("Location", foreign_keys=[location_id])
    user = relationship("User", foreign_keys=[user_id])
    company = relationship("Company", foreign_keys=[company_id])
    received_by = relationship("User", foreign_keys=[received_by_id])
    handed_over_by = relationship("User", foreign_keys=[handed_over_by_id])

    @property
    def recipient_name(self) -> str:
        if self.user is not None:
            return self.user.full_name
        return self.company.name if self.company is not None else "Unknown"

    @property
    def kind_label(self) -> str:
        return dict(PARCEL_KINDS).get(self.kind, self.kind.title())


class AlertNotice(db.Model, PkMixin, OperatorScoped):
    """One row per reminder already emailed, so the hourly job never sends it twice."""
    __tablename__ = "alert_notices"
    __table_args__ = (db.UniqueConstraint("operator_id", "key", name="uq_alert_notices_operator_key"),)

    key = Column(String(120), nullable=False)
    sent_at = Column(DateTime, nullable=False, default=datetime.utcnow)
