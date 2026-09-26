"""The platform's own commercial relationship with its tenants — what an
operator owes hub1z.com for their subscription. Separate from a tenant's own
/admin billing models (app/models/invoice.py, finance.py), which track what
a tenant charges its member companies/individuals.

Not TenantScoped on purpose: platform staff must see records across every
tenant, not just the ambient request tenant.
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

    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    number = Column(String(30), unique=True, nullable=False, index=True)
    period_start = Column(Date, nullable=False)
    period_end = Column(Date, nullable=False)
    due_date = Column(Date, nullable=False)
    amount = Column(Numeric(10, 2), nullable=False)
    currency = Column(String(3), default="INR", nullable=False)
    status = Column(Enum(PlatformInvoiceStatus), default=PlatformInvoiceStatus.ISSUED, nullable=False, index=True)
    notes = Column(Text)

    tenant = relationship("Tenant")
    credit_notes = relationship("PlatformCreditNote", back_populates="invoice")
    refunds = relationship("PlatformRefund", back_populates="invoice")


class PlatformCreditNote(db.Model, PkMixin, TimestampMixin):
    __tablename__ = "platform_credit_notes"

    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    invoice_id = Column(Integer, ForeignKey("platform_invoices.id", ondelete="SET NULL"), nullable=True, index=True)
    number = Column(String(30), unique=True, nullable=False, index=True)
    amount = Column(Numeric(10, 2), nullable=False)
    reason = Column(String(255), nullable=False)
    issued_at = Column(DateTime)

    tenant = relationship("Tenant")
    invoice = relationship("PlatformInvoice", back_populates="credit_notes")


class PlatformRefund(db.Model, PkMixin, TimestampMixin):
    __tablename__ = "platform_refunds"

    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    invoice_id = Column(Integer, ForeignKey("platform_invoices.id", ondelete="SET NULL"), nullable=True, index=True)
    number = Column(String(30), unique=True, nullable=False, index=True)
    amount = Column(Numeric(10, 2), nullable=False)
    reason = Column(String(255), nullable=False)
    processed_at = Column(DateTime)

    tenant = relationship("Tenant")
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
