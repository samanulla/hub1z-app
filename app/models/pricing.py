"""Pricing plans."""
from __future__ import annotations

import enum
from sqlalchemy import Column, String, Integer, Numeric, Enum, Text, Boolean, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship

from ..extensions import db
from ._mixins import PkMixin, TimestampMixin
from .tenant import TenantScoped


class PlanType(str, enum.Enum):
    HOT_DESK = "hot_desk"
    DEDICATED_DESK = "dedicated_desk"
    PRIVATE_OFFICE = "private_office"
    ALL_ACCESS = "all_access"
    DAY_PASS = "day_pass"
    CUSTOM = "custom"


class BillingCycle(str, enum.Enum):
    DAILY = "daily"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    ANNUAL = "annual"


class PricingPlan(db.Model, PkMixin, TimestampMixin, TenantScoped):
    __tablename__ = "pricing_plans"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_pricing_plans_tenant_name"),
    )

    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"),
                       nullable=True, index=True)

    name = Column(String(120), nullable=False)

    plan_type = Column(Enum(PlanType), nullable=False, default=PlanType.HOT_DESK)
    billing_cycle = Column(Enum(BillingCycle), nullable=False, default=BillingCycle.MONTHLY)
    base_price = Column(Numeric(10, 2), nullable=False)
    included_meeting_credits = Column(Integer, default=0, nullable=False)
    included_print_credits = Column(Integer, default=0, nullable=False)
    guest_passes = Column(Integer, default=0, nullable=False)
    max_locations = Column(Integer, default=1, nullable=False)  # 0 = unlimited
    is_active = Column(Boolean, default=True, nullable=False)
    description = Column(Text)

    subscriptions = relationship("Subscription", back_populates="plan")

    def __repr__(self) -> str:
        return f"<PricingPlan {self.name} ${self.base_price}/{self.billing_cycle.value}>"
