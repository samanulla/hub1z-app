"""Invoices and payments."""
from __future__ import annotations

import enum
from sqlalchemy import Column, Integer, ForeignKey, Enum, Date, DateTime, Numeric, String, Text
from sqlalchemy.orm import relationship

from ..extensions import db
from ._mixins import PkMixin, TimestampMixin
from .operator import OperatorScoped


class InvoiceStatus(str, enum.Enum):
    DRAFT = "draft"
    ISSUED = "issued"
    PAID = "paid"
    PARTIAL = "partial"
    VOID = "void"
    OVERDUE = "overdue"


class Invoice(db.Model, PkMixin, TimestampMixin, OperatorScoped):
    __tablename__ = "invoices"


    __table_args__ = (db.UniqueConstraint("operator_id", "number", name="uq_invoices_operator_number"),)
    number = Column(String(30), nullable=False, index=True)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="CASCADE"), nullable=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    subscription_id = Column(Integer, ForeignKey("subscriptions.id", ondelete="SET NULL"),
                             nullable=True, index=True)

    period_start = Column(Date, nullable=False)
    period_end = Column(Date, nullable=False)
    issued_at = Column(DateTime)
    due_date = Column(Date, nullable=False)

    subtotal = Column(Numeric(10, 2), default=0, nullable=False)
    tax_amount = Column(Numeric(10, 2), default=0, nullable=False)
    cgst_amount = Column(Numeric(10, 2), default=0, nullable=False)
    sgst_amount = Column(Numeric(10, 2), default=0, nullable=False)
    igst_amount = Column(Numeric(10, 2), default=0, nullable=False)
    total_amount = Column(Numeric(10, 2), default=0, nullable=False)
    amount_paid = Column(Numeric(10, 2), default=0, nullable=False)
    currency = Column(String(3), default="USD", nullable=False)
    status = Column(Enum(InvoiceStatus), default=InvoiceStatus.DRAFT, nullable=False, index=True)
    notes = Column(Text)

    pdf_document_id = Column(Integer, ForeignKey("documents.id", ondelete="SET NULL"))

    billing_name = Column(String(200))
    billing_address = Column(String(255))
    billing_city = Column(String(80))
    billing_state = Column(String(80))
    billing_country = Column(String(80))
    billing_postal_code = Column(String(20))

    # Parties as they were when the invoice was raised (tax invoices must not change later).
    seller_gstin = Column(String(20))
    seller_pan = Column(String(20))
    seller_state = Column(String(2))      # GST state code
    buyer_gstin = Column(String(20))
    buyer_pan = Column(String(20))
    buyer_state = Column(String(2))

    # Late fees have been billed on this invoice up to (not including) this date.
    late_fee_charged_through = Column(Date)

    company = relationship("Company", back_populates="invoices")
    line_items = relationship("InvoiceLineItem", back_populates="invoice", cascade="all, delete-orphan")
    payments = relationship("Payment", back_populates="invoice", cascade="all, delete-orphan")
    pdf_document = relationship("Document")

    @property
    def balance_due(self):
        return (self.total_amount or 0) - (self.amount_paid or 0)


class InvoiceLineItem(db.Model, PkMixin, OperatorScoped):
    __tablename__ = "invoice_line_items"

    invoice_id = Column(Integer, ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False, index=True)
    description = Column(String(255), nullable=False)
    quantity = Column(Numeric(10, 2), default=1, nullable=False)
    unit_price = Column(Numeric(10, 2), default=0, nullable=False)
    amount = Column(Numeric(10, 2), default=0, nullable=False)      # before tax
    line_type = Column(String(20), default="other", nullable=False)  # plan / deposit / late_fee / ...
    tax_rate = Column(Numeric(5, 2), default=0, nullable=False)
    tax_amount = Column(Numeric(10, 2), default=0, nullable=False)
    sac_code = Column(String(12))

    invoice = relationship("Invoice", back_populates="line_items")


class Payment(db.Model, PkMixin, TimestampMixin, OperatorScoped):
    __tablename__ = "payments"

    invoice_id = Column(Integer, ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False, index=True)
    amount = Column(Numeric(10, 2), nullable=False)
    method = Column(String(30), nullable=False, default="manual")   # manual, stripe, ach, wire
    reference = Column(String(120))
    paid_at = Column(DateTime, nullable=False)

    invoice = relationship("Invoice", back_populates="payments")


class PaymentSubmissionStatus(str, enum.Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class PaymentSubmission(db.Model, PkMixin, TimestampMixin, OperatorScoped):
    __tablename__ = "payment_submissions"

    operator_id = Column(Integer, ForeignKey("operators.id", ondelete="CASCADE"), nullable=False, index=True)
    invoice_id = Column(Integer, ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False, index=True)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    amount = Column(Numeric(10, 2), nullable=False)
    paid_on = Column(Date, nullable=False)
    reference = Column(String(120))
    notes = Column(Text)
    status = Column(Enum(PaymentSubmissionStatus), default=PaymentSubmissionStatus.PENDING,
                    nullable=False, index=True)
    operator_message = Column(Text)
    reviewed_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reviewed_at = Column(DateTime)

    invoice = relationship("Invoice", foreign_keys=[invoice_id])
    company = relationship("Company", foreign_keys=[company_id])
    reviewed_by = relationship("User", foreign_keys=[reviewed_by_id])
