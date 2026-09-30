"""Payroll: SalaryStructure, PayrollRun, Payslip."""
from __future__ import annotations

import enum
from decimal import Decimal
from sqlalchemy import Column, Integer, ForeignKey, Enum, Date, DateTime, Numeric, String, Text
from sqlalchemy.orm import relationship

from ..extensions import db
from ._mixins import PkMixin, TimestampMixin
from .operator import OperatorScoped


class PayFrequency(str, enum.Enum):
    MONTHLY = "monthly"
    BIWEEKLY = "biweekly"
    WEEKLY = "weekly"


class PayrollStatus(str, enum.Enum):
    DRAFT = "draft"
    APPROVED = "approved"
    PAID = "paid"
    CANCELLED = "cancelled"


class SalaryStructure(db.Model, PkMixin, TimestampMixin, OperatorScoped):
    __tablename__ = "salary_structures"

    staff_id = Column(Integer, ForeignKey("staff_members.id", ondelete="CASCADE"),
                      nullable=False, index=True)
    currency = Column(String(3), default="INR", nullable=False)
    pay_frequency = Column(Enum(PayFrequency), default=PayFrequency.MONTHLY, nullable=False)

    basic = Column(Numeric(12, 2), default=0, nullable=False)
    house_allowance = Column(Numeric(12, 2), default=0, nullable=False)
    transport_allowance = Column(Numeric(12, 2), default=0, nullable=False)
    other_allowances = Column(Numeric(12, 2), default=0, nullable=False)

    tax_deduction = Column(Numeric(12, 2), default=0, nullable=False)
    pf_deduction = Column(Numeric(12, 2), default=0, nullable=False)
    other_deductions = Column(Numeric(12, 2), default=0, nullable=False)

    effective_from = Column(Date, nullable=False)
    effective_to = Column(Date)  # NULL = current
    notes = Column(Text)

    staff = relationship("StaffMember", back_populates="salary_structures")

    @property
    def gross(self) -> Decimal:
        return (Decimal(self.basic or 0) + Decimal(self.house_allowance or 0)
                + Decimal(self.transport_allowance or 0) + Decimal(self.other_allowances or 0))

    @property
    def total_deductions(self) -> Decimal:
        return (Decimal(self.tax_deduction or 0) + Decimal(self.pf_deduction or 0)
                + Decimal(self.other_deductions or 0))

    @property
    def net(self) -> Decimal:
        return self.gross - self.total_deductions


class PayrollRun(db.Model, PkMixin, TimestampMixin, OperatorScoped):
    __tablename__ = "payroll_runs"


    period_start = Column(Date, nullable=False)
    period_end = Column(Date, nullable=False)
    status = Column(Enum(PayrollStatus), default=PayrollStatus.DRAFT, nullable=False, index=True)
    total_gross = Column(Numeric(14, 2), default=0, nullable=False)
    total_deductions = Column(Numeric(14, 2), default=0, nullable=False)
    total_net = Column(Numeric(14, 2), default=0, nullable=False)
    generated_at = Column(DateTime)
    paid_at = Column(DateTime)
    notes = Column(Text)

    payslips = relationship("Payslip", back_populates="run", cascade="all, delete-orphan")


class Payslip(db.Model, PkMixin, TimestampMixin, OperatorScoped):
    __tablename__ = "payslips"

    run_id = Column(Integer, ForeignKey("payroll_runs.id", ondelete="CASCADE"),
                    nullable=False, index=True)
    staff_id = Column(Integer, ForeignKey("staff_members.id", ondelete="CASCADE"),
                      nullable=False, index=True)

    basic = Column(Numeric(12, 2), default=0, nullable=False)
    allowances = Column(Numeric(12, 2), default=0, nullable=False)
    deductions = Column(Numeric(12, 2), default=0, nullable=False)
    gross = Column(Numeric(12, 2), default=0, nullable=False)
    net = Column(Numeric(12, 2), default=0, nullable=False)
    currency = Column(String(3), default="INR", nullable=False)

    pdf_document_id = Column(Integer, ForeignKey("documents.id", ondelete="SET NULL"))

    run = relationship("PayrollRun", back_populates="payslips")
    staff = relationship("StaffMember", back_populates="payslips")
    pdf_document = relationship("Document")
