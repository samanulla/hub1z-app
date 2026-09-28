"""Subscriptions link a plan to a company or an individual user."""
from __future__ import annotations

import enum
from sqlalchemy import Column, Integer, ForeignKey, Enum, Date, DateTime, Numeric, Text, CheckConstraint
from sqlalchemy.orm import relationship

from ..extensions import db
from ._mixins import PkMixin, TimestampMixin
from .tenant import TenantScoped


class SubscriptionStatus(str, enum.Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class SubscriptionRequestStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"


class Subscription(db.Model, PkMixin, TimestampMixin, TenantScoped):
    __tablename__ = "subscriptions"

    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"),
                       nullable=True, index=True)

    plan_id = Column(Integer, ForeignKey("pricing_plans.id", ondelete="RESTRICT"), nullable=False, index=True)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="CASCADE"), nullable=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)

    quantity = Column(Integer, default=1, nullable=False)      # seats
    unit_price = Column(Numeric(10, 2), nullable=False)         # snapshot of plan price at subscribe time
    start_date = Column(Date, nullable=False)
    end_date = Column(Date)                                     # NULL = auto-renew
    status = Column(Enum(SubscriptionStatus), default=SubscriptionStatus.ACTIVE, nullable=False)

    # Consumable credits pool
    meeting_credits_balance = Column(Integer, default=0, nullable=False)
    pricing_snapshot = Column(Text)

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


class SubscriptionChangeRequest(db.Model, PkMixin, TimestampMixin, TenantScoped):
    __tablename__ = "subscription_change_requests"

    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
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
