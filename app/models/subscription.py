"""Subscriptions link a plan to a company or an individual user."""
from __future__ import annotations

import enum
from sqlalchemy import Column, Integer, ForeignKey, Enum, Date, DateTime, Numeric, Text, CheckConstraint, String, Boolean
from sqlalchemy.orm import relationship

from ..extensions import db
from ._mixins import PkMixin, TimestampMixin
from .operator import OperatorScoped


class SubscriptionStatus(str, enum.Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class SubscriptionRequestStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"


class Subscription(db.Model, PkMixin, TimestampMixin, OperatorScoped):
    __tablename__ = "subscriptions"


    plan_id = Column(Integer, ForeignKey("pricing_plans.id", ondelete="RESTRICT"), nullable=False, index=True)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="CASCADE"), nullable=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)

    quantity = Column(Integer, default=1, nullable=False)      # seats
    unit_price = Column(Numeric(10, 2), nullable=False)         # snapshot of plan price at subscribe time
    start_date = Column(Date, nullable=False)
    end_date = Column(Date)                                     # NULL = auto-renew
    status = Column(Enum(SubscriptionStatus), default=SubscriptionStatus.ACTIVE, nullable=False)

    pricing_snapshot = Column(Text)

    # ---- Agreement terms (per subscription, so they also work for individuals) ----
    term_months = Column(Integer, default=11, nullable=False, server_default="11")
    lock_in_months = Column(Integer, default=6, nullable=False, server_default="6")
    notice_months = Column(Integer, default=3, nullable=False, server_default="3")
    deposit_amount = Column(Numeric(10, 2), default=0, nullable=False, server_default="0")
    deposit_refund_days = Column(Integer, default=15, nullable=False, server_default="15")
    escalation_percent = Column(Numeric(5, 2), default=0, nullable=False, server_default="0")
    escalation_after_months = Column(Integer, default=11, nullable=False, server_default="11")
    due_day = Column(Integer, default=5, nullable=False, server_default="5")
    late_fee_mode = Column(String(10), default="none", nullable=False, server_default="none")  # none / per_day / interest
    late_fee_value = Column(Numeric(10, 2), default=0, nullable=False, server_default="0")   # Rs per day, or % a year
    late_fee_grace_days = Column(Integer, default=0, nullable=False, server_default="0")
    early_exit_rule = Column(String(20), default="remaining_fees", nullable=False,
                             server_default="remaining_fees")  # remaining_fees / forfeit_deposit
    price_includes_tax = Column(Boolean, default=False, nullable=False, server_default=db.false())
    notice_given_on = Column(Date)
    terminate_on = Column(Date)
    agreement_document_id = Column(Integer, ForeignKey("documents.id", ondelete="SET NULL"))

    plan = relationship("PricingPlan", back_populates="subscriptions")
    company = relationship("Company", back_populates="subscriptions", foreign_keys=[company_id])
    user = relationship("User", back_populates="subscriptions", foreign_keys=[user_id])

    __table_args__ = (
        CheckConstraint(
            "(company_id IS NOT NULL) OR (user_id IS NOT NULL)",
            name="ck_subscription_target_present",
        ),
    )

    @property
    def monthly_total(self):
        return (self.unit_price or 0) * (self.quantity or 1)

    @property
    def lock_in_ends_on(self):
        from dateutil.relativedelta import relativedelta
        return self.start_date + relativedelta(months=self.lock_in_months or 0)

    @property
    def term_ends_on(self):
        from dateutil.relativedelta import relativedelta
        return self.start_date + relativedelta(months=self.term_months or 0)


class SubscriptionChangeRequest(db.Model, PkMixin, TimestampMixin, OperatorScoped):
    __tablename__ = "subscription_change_requests"

    operator_id = Column(Integer, ForeignKey("operators.id", ondelete="CASCADE"), nullable=False, index=True)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    subscription_id = Column(Integer, ForeignKey("subscriptions.id", ondelete="SET NULL"), nullable=True)
    requested_plan_id = Column(Integer, ForeignKey("pricing_plans.id", ondelete="RESTRICT"), nullable=False)
    requested_quantity = Column(Integer, nullable=False)
    status = Column(Enum(SubscriptionRequestStatus), default=SubscriptionRequestStatus.PENDING,
                    nullable=False, index=True)
    company_message = Column(Text)
    operator_message = Column(Text)
    requested_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reviewed_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reviewed_at = Column(DateTime)

    company = relationship("Company", foreign_keys=[company_id])
    subscription = relationship("Subscription", foreign_keys=[subscription_id])
    requested_plan = relationship("PricingPlan", foreign_keys=[requested_plan_id])
    requested_by = relationship("User", foreign_keys=[requested_by_id])
    reviewed_by = relationship("User", foreign_keys=[reviewed_by_id])
