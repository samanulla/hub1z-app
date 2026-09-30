"""Credit notes and refunds — issued against invoices or payments."""
from __future__ import annotations

import enum
from sqlalchemy import Column, Integer, ForeignKey, Enum, DateTime, Numeric, String, Text
from sqlalchemy.orm import relationship

from ..extensions import db
from ._mixins import PkMixin, TimestampMixin
from .operator import OperatorScoped


class CreditNoteStatus(str, enum.Enum):
    ISSUED = "issued"
    APPLIED = "applied"
    CANCELLED = "cancelled"


class CreditNote(db.Model, PkMixin, TimestampMixin, OperatorScoped):
    __tablename__ = "credit_notes"


    __table_args__ = (db.UniqueConstraint("operator_id", "number", name="uq_credit_notes_operator_number"),)
    number = Column(String(30), nullable=False, index=True)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="CASCADE"), nullable=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    invoice_id = Column(Integer, ForeignKey("invoices.id", ondelete="SET NULL"), nullable=True, index=True)

    amount = Column(Numeric(12, 2), nullable=False)
    currency = Column(String(3), default="USD", nullable=False)
    reason = Column(String(255), nullable=False)
    notes = Column(Text)

    status = Column(Enum(CreditNoteStatus), default=CreditNoteStatus.ISSUED, nullable=False, index=True)
    issued_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"))
    issued_at = Column(DateTime)
    applied_at = Column(DateTime)

    company = relationship("Company", foreign_keys=[company_id])
    user = relationship("User", foreign_keys=[user_id])
    invoice = relationship("Invoice", foreign_keys=[invoice_id])
    issued_by = relationship("User", foreign_keys=[issued_by_id])


class RefundStatus(str, enum.Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Refund(db.Model, PkMixin, TimestampMixin, OperatorScoped):
    __tablename__ = "refunds"

    payment_id = Column(Integer, ForeignKey("payments.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    amount = Column(Numeric(12, 2), nullable=False)
    reason = Column(String(255), nullable=False)
    method = Column(String(30), default="manual", nullable=False)
    reference = Column(String(120))
    status = Column(Enum(RefundStatus), default=RefundStatus.PENDING, nullable=False, index=True)

    processed_at = Column(DateTime)
    processed_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"))
    notes = Column(Text)

    payment = relationship("Payment", foreign_keys=[payment_id])
    processed_by = relationship("User", foreign_keys=[processed_by_id])
