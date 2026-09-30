"""Leads: prospects for one operator, or for the Platform itself (operator_id is NULL)."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, String, Integer, ForeignKey, Text, Date, DateTime, Numeric
from sqlalchemy.orm import relationship

from ..extensions import db
from ._mixins import PkMixin, TimestampMixin
from .operator import OperatorScoped


class Lead(db.Model, PkMixin, TimestampMixin, OperatorScoped):
    __tablename__ = "leads"
    __operator_nullable__ = True  # NULL = a Hub1z Platform lead, invisible to every operator

    name = Column(String(160), nullable=False)
    company_name = Column(String(200))
    email = Column(String(255))
    phone = Column(String(40))
    interest = Column(String(200))           # what they want, e.g. "3 dedicated desks"
    seats = Column(Integer)
    expected_value = Column(Numeric(12, 2), nullable=False, default=0)  # rupees per month
    source = Column(String(40))
    stage = Column(String(20), nullable=False, default="new", index=True)
    temperature = Column(String(10), nullable=False, default="warm")
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    next_follow_up = Column(Date, nullable=True, index=True)
    notes = Column(Text)
    lost_reason = Column(String(200))
    closed_at = Column(DateTime, nullable=True)

    owner = relationship("User", foreign_keys=[owner_id])
    activities = relationship("LeadActivity", back_populates="lead", cascade="all, delete-orphan",
                              order_by="LeadActivity.created_at.desc()")

    def __repr__(self) -> str:
        return f"<Lead {self.id} {self.name}>"

    @property
    def whatsapp_number(self) -> str:
        """Digits for a wa.me link; a bare 10-digit number is taken as Indian."""
        digits = "".join(c for c in (self.phone or "") if c.isdigit())
        if len(digits) == 10:
            digits = "91" + digits
        elif len(digits) == 11 and digits.startswith("0"):
            digits = "91" + digits[1:]
        return digits if len(digits) >= 11 else ""


class LeadActivity(db.Model, PkMixin, OperatorScoped):
    __tablename__ = "lead_activities"
    __operator_nullable__ = True

    lead_id = Column(Integer, ForeignKey("leads.id", ondelete="CASCADE"), nullable=False, index=True)
    kind = Column(String(20), nullable=False, default="note")   # note, call, email, meeting, stage
    body = Column(Text, nullable=False)
    created_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    lead = relationship("Lead", back_populates="activities")
    created_by = relationship("User", foreign_keys=[created_by_id])
