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

from sqlalchemy import Column, String, Integer, Numeric, Boolean

from ..extensions import db
from ._mixins import PkMixin, TimestampMixin


class PricingTier(db.Model, PkMixin, TimestampMixin):
    __tablename__ = "pricing_tiers"

    key = Column(String(30), unique=True, nullable=False, index=True)
    name = Column(String(80), nullable=False)
    monthly_price = Column(Numeric(10, 2), nullable=True)  # null = custom/contact us
    is_active = Column(Boolean, default=True, nullable=False)  # retired tiers stay valid for tenants already on them

    # Resource caps for tenants on this tier. null = unlimited.
    max_locations = Column(Integer, nullable=True)
    max_seats = Column(Integer, nullable=True)              # hot + dedicated desks
    max_private_offices = Column(Integer, nullable=True)    # "manager cabins"
    max_rooms = Column(Integer, nullable=True)               # conference rooms

    def __repr__(self) -> str:
        return f"<PricingTier {self.key}>"
