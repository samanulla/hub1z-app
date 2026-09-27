"""Pricing tiers — platform-defined tenant plan tiers with resource limits.

Distinct from a tenant's own PricingPlan (what a tenant charges ITS
companies/individuals for desks and rooms) — this is what the platform
itself sells to tenants, and what caps a tenant's own inventory size.
Introducing a new tier, or editing an existing one's limits/price, is a
Platform Super Admin-only action; a tenant's plan_tier just references
PricingTier.key by string (no hard FK, so retiring a tier never breaks an
existing tenant already on it).
"""
from __future__ import annotations

import enum

from sqlalchemy import Column, String, Integer, Numeric, Boolean, Enum, ForeignKey, Date, Text
from sqlalchemy.orm import relationship

from ..extensions import db
from ._mixins import PkMixin, TimestampMixin


class TierStatus(str, enum.Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    INACTIVE = "inactive"


class PricingTier(db.Model, PkMixin, TimestampMixin):
    __tablename__ = "pricing_tiers"

    key = Column(String(30), unique=True, nullable=False, index=True)
    name = Column(String(80), nullable=False)
    monthly_price = Column(Numeric(10, 2), nullable=True)  # null = custom/contact us
    annual_price = Column(Numeric(10, 2), nullable=True)
    annual_discount = Column(Numeric(10, 2), nullable=False, default=0)
    is_active = Column(Boolean, default=True, nullable=False)  # retired tiers stay valid for tenants already on them
    status = Column(Enum(TierStatus), nullable=False, default=TierStatus.DRAFT)

    # Resource caps for tenants on this tier. null = unlimited.
    max_locations = Column(Integer, nullable=True)
    max_seats = Column(Integer, nullable=True)              # hot + dedicated desks
    included_active_contracted_seats = Column(Integer, nullable=True)
    additional_seat_rate = Column(Numeric(10, 2), nullable=False, default=0)
    additional_location_rate = Column(Numeric(10, 2), nullable=False, default=0)
    included_features = Column(Text)
    premium_modules = Column(Text)
    trial_period_days = Column(Integer, nullable=False, default=0)
    max_private_offices = Column(Integer, nullable=True)    # "manager cabins"
    max_rooms = Column(Integer, nullable=True)               # conference rooms

    def __repr__(self) -> str:
        return f"<PricingTier {self.key}>"


class OperatorSubscription(db.Model, PkMixin, TimestampMixin):
    """Negotiated Hub1 commercial terms for one coworking operator.

    This is deliberately independent from platform invoices and the standard
    tier catalog so a contract can be customized without mutating a tier.
    """
    __tablename__ = "operator_subscriptions"

    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False,
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

    tenant = relationship("Tenant", foreign_keys=[tenant_id])
    tier = relationship("PricingTier", foreign_keys=[tier_id])
