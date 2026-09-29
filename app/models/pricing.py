"""Pricing plans."""
from __future__ import annotations

import enum
from sqlalchemy import Column, String, Integer, Numeric, Enum, Text, Boolean, ForeignKey, UniqueConstraint, Date
from sqlalchemy.orm import relationship

from ..extensions import db
from ._mixins import PkMixin, TimestampMixin
from .operator import OperatorScoped


class PlanType(str, enum.Enum):
    HOT_DESK = "hot_desk"
    DEDICATED_DESK = "dedicated_desk"
    PRIVATE_OFFICE = "private_office"
    MANAGED_OFFICE = "managed_office"
    ALL_ACCESS = "all_access"
    DAY_PASS = "day_pass"
    CUSTOM = "custom"


class BillingCycle(str, enum.Enum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    ANNUAL = "annual"


class PlanScope(str, enum.Enum):
    INDIVIDUAL = "individual"
    COMPANY_STANDARD = "company_standard"
    COMPANY_CUSTOM = "company_custom"


class BillingUnit(str, enum.Enum):
    PER_PERSON = "per_person"  # Legacy value; migration converts existing rows to PER_PERSON_DAY.
    PER_SEAT = "per_seat"
    PER_OFFICE = "per_office"
    PER_DAY_PASS = "per_day_pass"
    PER_PERSON_DAY = "per_person_day"
    FLAT_FEE = "flat_fee"


class LocationScope(str, enum.Enum):
    ONE = "one"
    MULTIPLE = "multiple"
    ALL = "all"


class PlanStatus(str, enum.Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    INACTIVE = "inactive"


pricing_plan_locations = db.Table(
    "pricing_plan_locations",
    Column("plan_id", Integer, ForeignKey("pricing_plans.id", ondelete="CASCADE"), primary_key=True),
    Column("location_id", Integer, ForeignKey("locations.id", ondelete="CASCADE"), primary_key=True),
)


class PricingPlan(db.Model, PkMixin, TimestampMixin, OperatorScoped):
    __tablename__ = "pricing_plans"
    __table_args__ = (
        UniqueConstraint("operator_id", "name", name="uq_pricing_plans_operator_name"),
    )


    name = Column(String(120), nullable=False)

    scope = Column(Enum(PlanScope), nullable=False, default=PlanScope.INDIVIDUAL)
    plan_type = Column(Enum(PlanType), nullable=False, default=PlanType.HOT_DESK)
    billing_unit = Column(Enum(BillingUnit), nullable=False, default=BillingUnit.PER_SEAT)
    billing_cycle = Column(Enum(BillingCycle), nullable=False, default=BillingCycle.MONTHLY)
    base_price = Column(Numeric(10, 2), nullable=False)
    included_seat_quantity = Column(Integer, default=1, nullable=False)
    included_meeting_credits = Column(Integer, default=0, nullable=False)
    additional_seat_rate = Column(Numeric(10, 2), default=0, nullable=False)
    additional_seats_allowed = Column(Boolean, default=False, nullable=False)
    maximum_additional_seats = Column(Integer)
    meeting_room_access_included = Column(Boolean, default=False, nullable=False)
    meeting_credit_unit = Column(String(20))
    meeting_credits_rollover = Column(Boolean, default=False, nullable=False)
    meeting_room_overage_allowed = Column(Boolean, default=False, nullable=False)
    meeting_room_overage_rate = Column(Numeric(10, 2), default=0, nullable=False)
    location_scope = Column(Enum(LocationScope), nullable=False, default=LocationScope.ALL)
    minimum_contract_months = Column(Integer, default=0, nullable=False)
    deposit_required = Column(Boolean, default=False, nullable=False)
    deposit_calculation = Column(String(30))
    deposit_value = Column(Numeric(10, 2), default=0, nullable=False)
    deposit_refundable = Column(Boolean, default=True, nullable=False)
    tax_applicable = Column(Boolean, default=True, nullable=False)
    tax_code = Column(String(30))
    price_includes_tax = Column(Boolean, default=False, nullable=False)
    currency = Column(String(3), default="INR", nullable=False)
    effective_from = Column(Date)
    effective_until = Column(Date)
    version = Column(Integer, default=1, nullable=False)
    status = Column(Enum(PlanStatus), nullable=False, default=PlanStatus.DRAFT)
    office_capacity = Column(Integer)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="CASCADE"), nullable=True, index=True)

    # Legacy fields remain for existing plans and historical subscriptions.
    included_print_credits = Column(Integer, default=0, nullable=False)
    guest_passes = Column(Integer, default=0, nullable=False)
    max_locations = Column(Integer, default=1, nullable=False)  # 0 = unlimited
    is_active = Column(Boolean, default=True, nullable=False)
    description = Column(Text)

    subscriptions = relationship("Subscription", back_populates="plan")
    company = relationship("Company", foreign_keys=[company_id])
    locations = relationship("Location", secondary=pricing_plan_locations, backref="pricing_plans")
    addons = relationship("PlanAddon", back_populates="plan", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<PricingPlan {self.name} ${self.base_price}/{self.billing_cycle.value}>"


class PlanAddon(db.Model, PkMixin, TimestampMixin, OperatorScoped):
    __tablename__ = "plan_addons"

    plan_id = Column(Integer, ForeignKey("pricing_plans.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(120), nullable=False)
    price = Column(Numeric(10, 2), nullable=False, default=0)
    billing_cycle = Column(Enum(BillingCycle), nullable=False, default=BillingCycle.MONTHLY)
    is_active = Column(Boolean, nullable=False, default=True)

    plan = relationship("PricingPlan", back_populates="addons")
