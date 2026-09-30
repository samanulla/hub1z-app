"""Billing configuration and agreement bookkeeping: operator defaults, GST rates, deposits, rate revisions."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Column, Integer, ForeignKey, Date, DateTime, Numeric, String, Text
from sqlalchemy.orm import relationship

from ..extensions import db
from ._mixins import PkMixin, TimestampMixin
from .operator import OperatorScoped


class BillingSettings(db.Model, PkMixin, TimestampMixin, OperatorScoped):
    """One row per operator: when invoices go out, and the starting terms offered on a new agreement."""
    __tablename__ = "billing_settings"
    __table_args__ = (db.UniqueConstraint("operator_id", name="uq_billing_settings_operator"),)

    invoice_issue_day = Column(Integer, default=1, nullable=False, server_default="1")
    due_day = Column(Integer, default=5, nullable=False, server_default="5")
    late_fee_mode = Column(String(10), default="none", nullable=False, server_default="none")
    late_fee_value = Column(Numeric(10, 2), default=0, nullable=False, server_default="0")
    late_fee_grace_days = Column(Integer, default=0, nullable=False, server_default="0")

    term_months = Column(Integer, default=11, nullable=False, server_default="11")
    lock_in_months = Column(Integer, default=6, nullable=False, server_default="6")
    notice_months = Column(Integer, default=3, nullable=False, server_default="3")
    deposit_months = Column(Integer, default=3, nullable=False, server_default="3")
    deposit_refund_days = Column(Integer, default=15, nullable=False, server_default="15")
    escalation_percent = Column(Numeric(5, 2), default=10, nullable=False, server_default="10")
    escalation_after_months = Column(Integer, default=11, nullable=False, server_default="11")
    early_exit_rule = Column(String(20), default="remaining_fees", nullable=False,
                             server_default="remaining_fees")

    @classmethod
    def for_operator(cls, operator_id: int) -> "BillingSettings":
        row = (cls.query.execution_options(skip_operator_filter=True)
               .filter_by(operator_id=operator_id).first())
        if row is None:
            row = cls(operator_id=operator_id)
            db.session.add(row)
            db.session.flush()
        return row


class TaxRate(db.Model, PkMixin, TimestampMixin, OperatorScoped):
    """GST rate for a kind of charge, valid from a date (so a rate change never rewrites old invoices)."""
    __tablename__ = "tax_rates"
    __table_args__ = (db.UniqueConstraint("operator_id", "charge_type", "effective_from",
                                          name="uq_tax_rates_operator_type_from"),)

    charge_type = Column(String(20), nullable=False)
    rate = Column(Numeric(5, 2), nullable=False)
    sac_code = Column(String(12))
    effective_from = Column(Date, nullable=False, default=date(2017, 7, 1))


class RateRevision(db.Model, PkMixin, TimestampMixin, OperatorScoped):
    """A yearly price change on an agreement. Only confirmed revisions are ever billed."""
    __tablename__ = "rate_revisions"

    subscription_id = Column(Integer, ForeignKey("subscriptions.id", ondelete="CASCADE"),
                             nullable=False, index=True)
    effective_from = Column(Date, nullable=False)
    percent = Column(Numeric(5, 2), nullable=False)
    old_unit_price = Column(Numeric(10, 2), nullable=False)
    new_unit_price = Column(Numeric(10, 2), nullable=False)
    status = Column(String(10), default="proposed", nullable=False, index=True)  # proposed / confirmed / dismissed
    decided_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"))
    decided_at = Column(DateTime)

    subscription = relationship("Subscription", backref="rate_revisions")


class DepositEntry(db.Model, PkMixin, TimestampMixin, OperatorScoped):
    """Security-deposit ledger: money received, deducted (damages, dues, forfeiture) and refunded."""
    __tablename__ = "deposit_entries"

    subscription_id = Column(Integer, ForeignKey("subscriptions.id", ondelete="CASCADE"),
                             nullable=False, index=True)
    entry_type = Column(String(10), nullable=False)      # received / deduction / refund
    amount = Column(Numeric(10, 2), nullable=False)
    entry_date = Column(Date, nullable=False, default=date.today)
    note = Column(String(255))
    invoice_id = Column(Integer, ForeignKey("invoices.id", ondelete="SET NULL"))
    created_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"))

    subscription = relationship("Subscription", backref="deposit_entries")
