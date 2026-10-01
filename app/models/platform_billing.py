"""The platform's own commercial relationship with its operators — what an
operator owes hub1z.com for their subscription. Separate from an operator's own
/admin billing models (app/models/invoice.py, finance.py), which track what
an operator charges its member companies/individuals.

Not OperatorScoped on purpose: platform staff must see records across every
operator, not just the ambient request operator.
"""
from __future__ import annotations

import enum
from sqlalchemy import Column, Integer, ForeignKey, Enum, Date, DateTime, Numeric, String, Text
from sqlalchemy.orm import relationship

from ..extensions import db
from ._mixins import PkMixin, TimestampMixin


class PlatformInvoiceStatus(str, enum.Enum):
    ISSUED = "issued"
    PAID = "paid"
    OVERDUE = "overdue"
    VOID = "void"


class PlatformInvoice(db.Model, PkMixin, TimestampMixin):
    __tablename__ = "platform_invoices"

    operator_id = Column(Integer, ForeignKey("operators.id", ondelete="CASCADE"), nullable=False, index=True)
    number = Column(String(30), unique=True, nullable=False, index=True)
    period_start = Column(Date, nullable=False)
    period_end = Column(Date, nullable=False)
    due_date = Column(Date, nullable=False)
    amount = Column(Numeric(10, 2), nullable=False)
    currency = Column(String(3), default="INR", nullable=False)
    status = Column(Enum(PlatformInvoiceStatus), default=PlatformInvoiceStatus.ISSUED, nullable=False, index=True)
    notes = Column(Text)

    operator = relationship("Operator")
    credit_notes = relationship("PlatformCreditNote", back_populates="invoice")
    refunds = relationship("PlatformRefund", back_populates="invoice")


class PlatformCreditNote(db.Model, PkMixin, TimestampMixin):
    __tablename__ = "platform_credit_notes"

    operator_id = Column(Integer, ForeignKey("operators.id", ondelete="CASCADE"), nullable=False, index=True)
    invoice_id = Column(Integer, ForeignKey("platform_invoices.id", ondelete="SET NULL"), nullable=True, index=True)
    number = Column(String(30), unique=True, nullable=False, index=True)
    amount = Column(Numeric(10, 2), nullable=False)
    reason = Column(String(255), nullable=False)
    issued_at = Column(DateTime)

    operator = relationship("Operator")
    invoice = relationship("PlatformInvoice", back_populates="credit_notes")


class PlatformRefund(db.Model, PkMixin, TimestampMixin):
    __tablename__ = "platform_refunds"

    operator_id = Column(Integer, ForeignKey("operators.id", ondelete="CASCADE"), nullable=False, index=True)
    invoice_id = Column(Integer, ForeignKey("platform_invoices.id", ondelete="SET NULL"), nullable=True, index=True)
    number = Column(String(30), unique=True, nullable=False, index=True)
    amount = Column(Numeric(10, 2), nullable=False)
    reason = Column(String(255), nullable=False)
    processed_at = Column(DateTime)

    operator = relationship("Operator")
    invoice = relationship("PlatformInvoice", back_populates="refunds")


class PlatformExpense(db.Model, PkMixin, TimestampMixin):
    """Platform's own operating expenses (infra, support, etc.) — not tied
    to a specific operator, tracked for the platform's own books."""
    __tablename__ = "platform_expenses"

    category = Column(String(60), nullable=False)
    description = Column(String(255), nullable=False)
    amount = Column(Numeric(10, 2), nullable=False)
    incurred_on = Column(Date, nullable=False)
    notes = Column(Text)


class PlatformProfile(db.Model, PkMixin, TimestampMixin):
    """Hub1z's own business and payment details (a single row), shown to operators and on Hub1z documents."""
    __tablename__ = "platform_profile"

    legal_name = Column(String(200), nullable=False, default="Hub1z Technologies Private Limited")
    gstin = Column(String(20))
    pan = Column(String(20))
    address = Column(String(300))
    billing_email = Column(String(255))
    upi_id = Column(String(120))
    gpay = Column(String(120))
    bank_details = Column(String(500))
    payment_instructions = Column(String(500))

    @classmethod
    def get(cls) -> "PlatformProfile":
        row = cls.query.order_by(cls.id).first()
        if row is None:
            row = cls()
            db.session.add(row)
            db.session.flush()
        return row


class PlatformPaymentReport(db.Model, PkMixin, TimestampMixin):
    """An operator telling Hub1z it has paid a Hub1z invoice (by UPI or bank), for Hub1z to confirm."""
    __tablename__ = "platform_payment_reports"

    operator_id = Column(Integer, ForeignKey("operators.id", ondelete="CASCADE"), nullable=False, index=True)
    invoice_id = Column(Integer, ForeignKey("platform_invoices.id", ondelete="CASCADE"), nullable=False, index=True)
    amount = Column(Numeric(10, 2), nullable=False)
    paid_on = Column(Date, nullable=False)
    reference = Column(String(120))
    notes = Column(Text)
    status = Column(String(12), nullable=False, default="pending", index=True)  # pending / accepted / rejected
    platform_message = Column(Text)
    reported_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"))
    reviewed_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"))
    reviewed_at = Column(DateTime)

    operator = relationship("Operator")
    invoice = relationship("PlatformInvoice")
    reported_by = relationship("User", foreign_keys=[reported_by_id])
    reviewed_by = relationship("User", foreign_keys=[reviewed_by_id])
