"""Operator marketplace: opt-in listings, platform-level customers, bookings and the commission ledger.

A room booking holds its slot with a RoomBlock (same room row lock as member bookings), so no operator
User is needed for a marketplace guest."""
from __future__ import annotations

import secrets
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    JSON, Boolean, CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, Numeric, String,
    Text, UniqueConstraint,
)
from sqlalchemy.orm import relationship

from ..extensions import db
from ._mixins import PkMixin, TimestampMixin
from .operator import OperatorScoped

# Booking origin; set by the server only, never from user input (drives commission).
SOURCE_MARKETPLACE = "hub1z_marketplace"
SOURCE_OPERATOR_SITE = "operator_site"
SOURCE_OPERATOR_MEMBER = "operator_member"
BOOKING_SOURCES = (SOURCE_MARKETPLACE, SOURCE_OPERATOR_SITE, SOURCE_OPERATOR_MEMBER)

RESOURCE_TYPES = ("room", "day_access")          # VO is an enquiry (Lead), never bookable
LISTING_STATUSES = ("draft", "live", "paused", "unlisted")
APPROVAL_MODES = ("instant", "request")
BOOKING_STATUSES = ("requested", "held", "confirmed", "checked_in", "completed", "declined",
                    "expired", "cancelled_customer", "cancelled_operator", "no_show")
PAYMENT_STATUSES = ("unpaid", "pending_verification", "paid", "part_refunded", "refunded")
PAYMENT_METHODS = ("manual_upi", "bank_transfer", "pay_at_venue", "razorpay")
SETTLEMENT_MODES = ("operator_collects", "platform_collects")
LEDGER_ENTRY_TYPES = ("accrual", "reversal", "adjustment")
# Statuses that still occupy inventory.
ACTIVE_BOOKING_STATUSES = ("requested", "held", "confirmed", "checked_in")

CANCELLATION_PRESETS = {
    "flexible": {"label": "Flexible", "free_hours": 24, "late_refund_pct": 50},
}


def _in(column: str, values) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class OperatorMarketplaceTerms(db.Model, PkMixin, TimestampMixin, OperatorScoped):
    """Per-operator opt-in and commission rate, with effective date; the rate used is snapshotted on each booking."""
    __tablename__ = "operator_marketplace_terms"
    __table_args__ = (UniqueConstraint("operator_id", name="uq_marketplace_terms_operator"),)

    enabled = Column(Boolean, nullable=False, default=False)
    commission_pct = Column(Numeric(5, 2), nullable=False, default=Decimal("10.00"))
    effective_from = Column(DateTime, nullable=False, default=datetime.utcnow)
    accepted_terms_at = Column(DateTime)
    kyc_approved = Column(Boolean, nullable=False, default=False)
    payment_methods = Column(JSON, nullable=False, default=lambda: ["manual_upi", "pay_at_venue"])
    operator_cancel_compensation_pct = Column(Numeric(5, 2), nullable=False, default=Decimal("0"))


class MarketplaceListing(db.Model, PkMixin, TimestampMixin, OperatorScoped):
    __tablename__ = "marketplace_listings"
    __table_args__ = (
        CheckConstraint(_in("resource_type", RESOURCE_TYPES), name="ck_mkt_listing_resource"),
        CheckConstraint(_in("status", LISTING_STATUSES), name="ck_mkt_listing_status"),
        CheckConstraint(_in("approval_mode", APPROVAL_MODES), name="ck_mkt_listing_approval"),
        Index("ix_mkt_listing_public", "status", "location_id"),
    )

    location_id = Column(Integer, ForeignKey("locations.id", ondelete="RESTRICT"), nullable=False, index=True)
    resource_type = Column(String(20), nullable=False)
    room_id = Column(Integer, ForeignKey("conference_rooms.id", ondelete="RESTRICT"), nullable=True, index=True)
    title = Column(String(160), nullable=False)
    description = Column(Text)
    status = Column(String(12), nullable=False, default="draft")
    approval_mode = Column(String(10), nullable=False, default="request")

    price = Column(Numeric(10, 2), nullable=False, default=0)    # per hour (room) or per day (day access)
    gst_rate_pct = Column(Numeric(5, 2), nullable=False, default=Decimal("18.00"))

    # Allotment: ceiling for the marketplace, never a reservation against members.
    daily_cap_units = Column(Integer)            # day access: max passes per day
    daily_cap_hours_pct = Column(Integer)        # room: max % of open hours per day
    availability_windows = Column(JSON, nullable=False, default=list)   # [{"days":[0-4],"from":"09:00","to":"18:00"}]
    blackout_dates = Column(JSON, nullable=False, default=list)         # ["2026-12-25"]
    min_lead_hours = Column(Integer, nullable=False, default=2)
    max_length_hours = Column(Integer, nullable=False, default=8)

    visibility = Column(JSON, nullable=False, default=dict)   # which details/photos are public
    guest_rules = Column(JSON, nullable=False, default=dict)  # id_required, max_guests, house_rules
    access_instructions = Column(Text)                        # revealed only after confirmed AND (paid OR pay_at_venue)
    cancellation_preset = Column(String(20), nullable=False, default="flexible")
    payment_methods = Column(JSON)                            # null = operator default

    paused_at = Column(DateTime)

    location = relationship("Location")
    room = relationship("ConferenceRoom")


class MarketplaceCustomer(db.Model, PkMixin, TimestampMixin):
    """Platform-level buyer account. Never an operator User, so it is not operator scoped."""
    __tablename__ = "marketplace_customers"

    email = Column(String(255), nullable=False, unique=True, index=True)
    full_name = Column(String(150), nullable=False)
    phone = Column(String(30))
    email_verified_at = Column(DateTime)
    password_hash = Column(String(255))
    is_active = Column(Boolean, nullable=False, default=True)
    billing_profiles = Column(JSON, nullable=False, default=list)   # [{"name","gstin","address"}]
    reliability_strikes = Column(Integer, nullable=False, default=0)   # internal to Hub1z, never shown to operators
    consented_at = Column(DateTime)
    auth_version = Column(Integer, nullable=False, default=0)


class MarketplaceBooking(db.Model, PkMixin, TimestampMixin, OperatorScoped):
    """The money side of a marketplace booking; rooms also hold a RoomBooking row so one lock guards the slot."""
    __tablename__ = "marketplace_bookings"
    __table_args__ = (
        CheckConstraint(_in("source", BOOKING_SOURCES), name="ck_mkt_booking_source"),
        CheckConstraint(_in("status", BOOKING_STATUSES), name="ck_mkt_booking_status"),
        CheckConstraint(_in("payment_status", PAYMENT_STATUSES), name="ck_mkt_booking_payment_status"),
        CheckConstraint(_in("settlement_mode", SETTLEMENT_MODES), name="ck_mkt_booking_settlement"),
        UniqueConstraint("customer_id", "idempotency_key", name="uq_mkt_booking_idempotency"),
        Index("ix_mkt_booking_slot", "listing_id", "start_at", "end_at"),
    )

    listing_id = Column(Integer, ForeignKey("marketplace_listings.id", ondelete="RESTRICT"), nullable=False, index=True)
    customer_id = Column(Integer, ForeignKey("marketplace_customers.id", ondelete="RESTRICT"), nullable=False, index=True)
    room_block_id = Column(Integer, ForeignKey("room_blocks.id", ondelete="SET NULL"), nullable=True, index=True)
    code = Column(String(16), nullable=False, unique=True, index=True, default=lambda: secrets.token_hex(4).upper())
    idempotency_key = Column(String(64), nullable=False)

    source = Column(String(24), nullable=False, default=SOURCE_MARKETPLACE)
    status = Column(String(24), nullable=False, default="requested")
    payment_status = Column(String(24), nullable=False, default="unpaid")
    payment_method = Column(String(20))
    payment_reference = Column(String(120))
    settlement_mode = Column(String(20), nullable=False, default="operator_collects")

    start_at = Column(DateTime, nullable=False, index=True)
    end_at = Column(DateTime, nullable=False)
    units = Column(Integer, nullable=False, default=1)
    guests = Column(Integer, nullable=False, default=1)
    expires_at = Column(DateTime, index=True)       # unpaid/unapproved holds release at this time

    # Customer details copied at booking time; operators only ever see these.
    customer_name = Column(String(150), nullable=False)
    customer_email = Column(String(255), nullable=False)
    customer_phone = Column(String(30))
    billing_name = Column(String(200))
    billing_gstin = Column(String(20))
    allow_membership_contact = Column(Boolean, nullable=False, default=False)

    subtotal = Column(Numeric(10, 2), nullable=False, default=0)
    gst_amount = Column(Numeric(10, 2), nullable=False, default=0)
    total = Column(Numeric(10, 2), nullable=False, default=0)
    commission_pct = Column(Numeric(5, 2), nullable=False, default=0)   # snapshot at booking time
    cancellation_preset = Column(String(20), nullable=False, default="flexible")
    cancelled_at = Column(DateTime)
    cancel_reason = Column(String(300))

    listing = relationship("MarketplaceListing")
    customer = relationship("MarketplaceCustomer")
    room_block = relationship("RoomBlock")


class CommissionLedgerEntry(db.Model, PkMixin, TimestampMixin, OperatorScoped):
    """Append-only: corrections are reversal or adjustment rows, never edits."""
    __tablename__ = "commission_ledger"
    __table_args__ = (
        CheckConstraint(_in("entry_type", LEDGER_ENTRY_TYPES), name="ck_commission_entry_type"),
    )

    booking_id = Column(Integer, ForeignKey("marketplace_bookings.id", ondelete="RESTRICT"), nullable=False, index=True)
    entry_type = Column(String(12), nullable=False)
    gross_amount = Column(Numeric(10, 2), nullable=False)
    commission_pct = Column(Numeric(5, 2), nullable=False)
    amount = Column(Numeric(10, 2), nullable=False)       # signed: reversals are negative
    note = Column(String(300))
    invoiced_in = Column(String(40))                      # monthly commission invoice reference

    booking = relationship("MarketplaceBooking")
