"""Attendance: who was in the space (or at work, for the Platform team), and when."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, String, Integer, ForeignKey, DateTime, Index
from sqlalchemy.orm import relationship

from ..extensions import db
from ._mixins import PkMixin, TimestampMixin
from .operator import OperatorScoped

METHOD_QR_SELF = "qr_self"            # scanned the location QR with their own phone
METHOD_QR_RECEPTION = "qr_reception"  # reception scanned the person's QR
METHOD_MANUAL = "manual"              # staff marked it by hand
METHOD_WEB = "web"                    # Platform team: the check-in button
METHOD_LABELS = {
    METHOD_QR_SELF: "Location QR", METHOD_QR_RECEPTION: "Reception scan",
    METHOD_MANUAL: "Marked by staff", METHOD_WEB: "Web",
}


class AttendanceRecord(db.Model, PkMixin, TimestampMixin, OperatorScoped):
    __tablename__ = "attendance_records"
    __operator_nullable__ = True  # NULL = Hub1z Platform team, invisible to every operator
    __table_args__ = (Index("ix_attendance_operator_checkin", "operator_id", "check_in_at"),)

    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    location_id = Column(Integer, ForeignKey("locations.id", ondelete="SET NULL"), nullable=True, index=True)
    check_in_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    check_out_at = Column(DateTime, nullable=True)
    method = Column(String(20), nullable=False, default=METHOD_MANUAL)
    recorded_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    note = Column(String(200))

    user = relationship("User", foreign_keys=[user_id])
    location = relationship("Location", foreign_keys=[location_id])
    recorded_by = relationship("User", foreign_keys=[recorded_by_id])

    @property
    def is_open(self) -> bool:
        return self.check_out_at is None

    @property
    def minutes(self) -> int | None:
        if self.check_out_at is None:
            return None
        return max(0, int((self.check_out_at - self.check_in_at).total_seconds() // 60))

    @property
    def method_label(self) -> str:
        return METHOD_LABELS.get(self.method, self.method)
