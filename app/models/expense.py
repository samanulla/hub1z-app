"""Expense categories and expense records for the coworking space's own operations."""
from __future__ import annotations

import enum
from sqlalchemy import Column, Integer, ForeignKey, Enum, Date, DateTime, Numeric, String, Text, Boolean
from sqlalchemy.orm import relationship

from ..extensions import db
from ._mixins import PkMixin, TimestampMixin
from .operator import OperatorScoped


class ExpenseStatus(str, enum.Enum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    APPROVED = "approved"
    REJECTED = "rejected"
    PAID = "paid"


class ExpenseCategory(db.Model, PkMixin, TimestampMixin, OperatorScoped):
    __tablename__ = "expense_categories"


    __table_args__ = (db.UniqueConstraint("operator_id", "name", name="uq_expense_categories_operator_name"),)
    name = Column(String(120), nullable=False)
    description = Column(Text)
    is_active = Column(Boolean, default=True, nullable=False)

    expenses = relationship("Expense", back_populates="category")


class Expense(db.Model, PkMixin, TimestampMixin, OperatorScoped):
    __tablename__ = "expenses"


    category_id = Column(Integer, ForeignKey("expense_categories.id", ondelete="RESTRICT"),
                         nullable=False, index=True)
    location_id = Column(Integer, ForeignKey("locations.id", ondelete="SET NULL"))
    staff_id = Column(Integer, ForeignKey("staff_members.id", ondelete="SET NULL"))

    amount = Column(Numeric(12, 2), nullable=False)
    currency = Column(String(3), default="USD", nullable=False)
    expense_date = Column(Date, nullable=False)
    vendor = Column(String(200))
    description = Column(Text)
    payment_method = Column(String(30))  # cash, card, bank_transfer, cheque

    status = Column(Enum(ExpenseStatus), default=ExpenseStatus.DRAFT, nullable=False, index=True)
    receipt_document_id = Column(Integer, ForeignKey("documents.id", ondelete="SET NULL"))

    submitted_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"))
    approved_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"))
    approved_at = Column(DateTime)
    paid_at = Column(DateTime)
    rejection_reason = Column(Text)

    category = relationship("ExpenseCategory", back_populates="expenses")
    location = relationship("Location")
    staff = relationship("StaffMember", foreign_keys=[staff_id])
    receipt_document = relationship("Document")
    submitted_by = relationship("User", foreign_keys=[submitted_by_id])
    approved_by = relationship("User", foreign_keys=[approved_by_id])
