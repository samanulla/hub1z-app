"""Pricing tiers — platform-defined operator plan tiers with resource limits.

Distinct from an operator's own PricingPlan (what an operator charges ITS
companies/individuals for desks and rooms) — this is what the platform
itself sells to operators, and what caps an operator's own inventory size.
Introducing a new tier, or editing an existing one's limits/price, is a
Platform Super Admin-only action; an operator's plan_tier just references
PricingTier.key by string (no hard FK, so retiring a tier never breaks an
existing operator already on it).
"""
from __future__ import annotations

import enum
from decimal import Decimal

from sqlalchemy import Column, String, Integer, Numeric, Boolean, Enum, ForeignKey, Date, Text
from sqlalchemy.orm import relationship

from ..extensions import db
from ._mixins import PkMixin, TimestampMixin


class TierStatus(str, enum.Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    INACTIVE = "inactive"


class OveragePolicy(str, enum.Enum):
    ALLOW_AND_CHARGE = "allow_and_charge"
    BLOCK_ADDITIONAL_USAGE = "block_additional_usage"
    REQUIRE_PLAN_UPGRADE = "require_plan_upgrade"
    CUSTOM_APPROVAL = "custom_approval"


class SeatUsageMethod(str, enum.Enum):
    MAXIMUM_DURING_BILLING_PERIOD = "maximum_during_billing_period"
    AVERAGE_DAILY_USAGE = "average_daily_usage"
    END_OF_PERIOD_USAGE = "end_of_period_usage"


tier_modules = db.Table(
    "tier_modules",
    Column("tier_id", Integer, ForeignKey("pricing_tiers.id", ondelete="CASCADE"), primary_key=True),
    Column("module_id", Integer, ForeignKey("platform_modules.id", ondelete="CASCADE"), primary_key=True),
)


class PricingTier(db.Model, PkMixin, TimestampMixin):
    __tablename__ = "pricing_tiers"

    key = Column(String(30), unique=True, nullable=False, index=True)
    name = Column(String(80), nullable=False)
    monthly_price = Column(Numeric(10, 2), nullable=True)  # null = custom/contact us
    annual_price = Column(Numeric(10, 2), nullable=True)
    annual_discount = Column(Numeric(10, 2), nullable=False, default=0)
    is_active = Column(Boolean, default=True, nullable=False)  # retired tiers stay valid for operators already on them
    status = Column(Enum(TierStatus), nullable=False, default=TierStatus.DRAFT)

    # Resource caps for operators on this tier. null = unlimited.
    max_locations = Column(Integer, nullable=True)
    max_seats = Column(Integer, nullable=True)              # hot + dedicated desks
    included_active_contracted_seats = Column(Integer, nullable=True)
    additional_seat_rate = Column(Numeric(10, 2), nullable=False, default=0)
    additional_location_rate = Column(Numeric(10, 2), nullable=False, default=0)
    included_features = Column(Text)
    premium_modules = Column(Text)
    trial_period_days = Column(Integer, nullable=False, default=0)
    seat_overage_policy = Column(Enum(OveragePolicy), nullable=False, default=OveragePolicy.ALLOW_AND_CHARGE)
    location_overage_policy = Column(Enum(OveragePolicy), nullable=False, default=OveragePolicy.REQUIRE_PLAN_UPGRADE)
    effective_from = Column(Date)
    effective_to = Column(Date)
    seat_usage_method = Column(Enum(SeatUsageMethod), nullable=False,
                               default=SeatUsageMethod.MAXIMUM_DURING_BILLING_PERIOD)
    pricing_version = Column(Integer, nullable=False, default=1)
    max_private_offices = Column(Integer, nullable=True)    # "manager cabins"
    max_rooms = Column(Integer, nullable=True)               # conference rooms

    def __repr__(self) -> str:
        return f"<PricingTier {self.key}>"

    def calculate_annual_price(self):
        if self.monthly_price is None:
            return None
        discount = Decimal(self.annual_discount or 0)
        return self.monthly_price * (Decimal(12) - discount / Decimal(100))


class PlatformModule(db.Model, PkMixin, TimestampMixin):
    __tablename__ = "platform_modules"

    code = Column(String(50), unique=True, nullable=False, index=True)
    name = Column(String(120), nullable=False)
    monthly_price = Column(Numeric(10, 2), nullable=False, default=0)
    kind = Column(String(20), nullable=False, default="module")
    is_active = Column(Boolean, nullable=False, default=True)

    tiers = relationship("PricingTier", secondary=tier_modules, backref="module_catalog")


class OperatorSubscription(db.Model, PkMixin, TimestampMixin):
    """Negotiated Hub1 commercial terms for one coworking operator.

    This is deliberately independent from platform invoices and the standard
    tier catalog so a contract can be customized without mutating a tier.
    """
    __tablename__ = "operator_subscriptions"

    operator_id = Column(Integer, ForeignKey("operators.id", ondelete="CASCADE"), nullable=False,
                       unique=True, index=True)
    tier_id = Column(Integer, ForeignKey("pricing_tiers.id", ondelete="SET NULL"), nullable=True)
    billing_cycle = Column(String(10), nullable=False, default="monthly")
    negotiated_base_price = Column(Numeric(10, 2), nullable=True)
    additional_free_seats = Column(Integer, nullable=False, default=0)
    additional_free_locations = Column(Integer, nullable=False, default=0)
    custom_additional_seat_rate = Column(Numeric(10, 2), nullable=True)
    custom_additional_location_rate = Column(Numeric(10, 2), nullable=True)
    discount_amount = Column(Numeric(10, 2), nullable=False, default=0)
    premium_modules_amount = Column(Numeric(10, 2), nullable=False, default=0)
    implementation_charge = Column(Numeric(10, 2), nullable=False, default=0)
    tax_rate = Column(Numeric(5, 2), nullable=False, default=0)
    negotiated_features = Column(Text)
    contract_start_date = Column(Date)
    contract_end_date = Column(Date)
    pricing_snapshot = Column(Text)

    operator = relationship("Operator", foreign_keys=[operator_id])
    tier = relationship("PricingTier", foreign_keys=[tier_id])


class OperatorUsageSnapshot(db.Model, PkMixin, TimestampMixin):
    __tablename__ = "operator_usage_snapshots"

    operator_id = Column(Integer, ForeignKey("operators.id", ondelete="CASCADE"), nullable=False, index=True)
    recorded_on = Column(Date, nullable=False, index=True)
    active_contracted_seats = Column(Integer, nullable=False, default=0)

    operator = relationship("Operator", foreign_keys=[operator_id])
