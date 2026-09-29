"""Audit log — who did what, when, to which entity."""
from __future__ import annotations

from sqlalchemy import Column, Integer, ForeignKey, String, Text
from sqlalchemy.orm import relationship

from ..extensions import db
from ._mixins import PkMixin, TimestampMixin
from .operator import OperatorScoped


class AuditLog(db.Model, PkMixin, TimestampMixin, OperatorScoped):
    __tablename__ = "audit_logs"
    __operator_nullable__ = True


    actor_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    action = Column(String(80), nullable=False, index=True)      # e.g. 'invoice.void'
    entity_type = Column(String(50), nullable=False, index=True)  # e.g. 'invoice'
    entity_id = Column(Integer, index=True)
    details = Column(Text)          # JSON blob (optional)
    ip_address = Column(String(45))
    user_agent = Column(String(255))

    actor = relationship("User", foreign_keys=[actor_id])

    def __repr__(self) -> str:
        return f"<AuditLog {self.action} {self.entity_type}#{self.entity_id}>"
