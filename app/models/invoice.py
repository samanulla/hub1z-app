"""Invoices and payments."""
from __future__ import annotations

import enum
from sqlalchemy import Column, Integer, ForeignKey, Enum, Date, DateTime, Numeric, String, Text
from sqlalchemy.orm import relationship

from ..extensions import db
from ._mixins import PkMixin, TimestampMixin
from .tenant import TenantScoped


class InvoiceStatus(str, enum.Enum):
    DRAFT = "draft"
    ISSUED = "issued"
    PAID = "paid"
    PARTIAL = "partial"
    VOID = "void"
    OVERDUE = "overdue"


class Invoice(db.Model, PkMixin, TimestampMixin, TenantScoped):
    __tablename__ = "invoices"

    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"),
                       nullable=True, index=True)

    number = Column(String(30), unique=True, nullable=False, index=True)
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

    company = relationship("Company", back_populates="invoices")
    line_items = relationship("InvoiceLineItem", back_populates="invoice", cascade="all, delete-orphan")
    payments = relationship("Payment", back_populates="invoice", cascade="all, delete-orphan")
    pdf_document = relationship("Document")

    @property
    def balance_due(self):
        return (self.total_amount or 0) - (self.amount_paid or 0)


class InvoiceLineItem(db.Model, PkMixin):
    __tablename__ = "invoice_line_items"

    invoice_id = Column(Integer, ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False, index=True)
    description = Column(String(255), nullable=False)
    quantity = Column(Numeric(10, 2), default=1, nullable=False)
    unit_price = Column(Numeric(10, 2), default=0, nullable=False)
    amount = Column(Numeric(10, 2), default=0, nullable=False)

    invoice = relationship("Invoice", back_populates="line_items")


class Payment(db.Model, PkMixin, TimestampMixin):
    __tablename__ = "payments"

    invoice_id = Column(Integer, ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False, index=True)
    amount = Column(Numeric(10, 2), nullable=False)
    method = Column(String(30), nullable=False, default="manual")   # manual, stripe, ach, wire
    reference = Column(String(120))
    paid_at = Column(DateTime, nullable=False)

    invoice = relationship("Invoice", back_populates="payments")
