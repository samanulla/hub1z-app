"""Meeting-room credits. 1 credit = 30 minutes of a Standard room.

Balances are never a single number: they are lots (a grant with an expiry) and every
change is a ledger entry, so usage, refunds, expiry and invoicing stay explainable.
"""
from __future__ import annotations

import enum

from sqlalchemy import (
    Boolean, CheckConstraint, Column, Date, DateTime, Enum, ForeignKey, Integer, Numeric, String,
)
from sqlalchemy.orm import relationship

from ..extensions import db
from ._mixins import PkMixin, TimestampMixin
from .operator import OperatorScoped


class CreditBucket(str, enum.Enum):
    BONUS = "bonus"                  # one-time, expires at month end
    PASS = "pass"                    # included with a day pass, same-day only
    COMPLIMENTARY = "complimentary"  # the monthly allocation from the pool
    PURCHASED = "purchased"


# Spend order: earliest-expiring free credits first, paid credits last.
BUCKET_PRIORITY = {
    CreditBucket.BONUS: 0, CreditBucket.PASS: 1,
    CreditBucket.COMPLIMENTARY: 2, CreditBucket.PURCHASED: 3,
}


class LedgerType(str, enum.Enum):
    GRANT = "grant"
    USE = "use"
    REFUND = "refund"
    PURCHASE = "purchase"
    EXPIRE = "expire"
    FORFEIT = "forfeit"
    ADJUST = "adjust"


class CreditSettings(db.Model, PkMixin, TimestampMixin, OperatorScoped):
    """One row per operator: how the credit pool and its rules behave."""
    __tablename__ = "credit_settings"
    __table_args__ = (db.UniqueConstraint("operator_id", name="uq_credit_settings_operator"),)

    complimentary_share_pct = Column(Integer, nullable=False, default=50)   # of room capacity
    reserve_pct = Column(Integer, nullable=False, default=20)               # of the pool kept for new signups
    pool_mode = Column(String(10), nullable=False, default="warn")          # warn | block
    capacity_days_per_month = Column(Integer, nullable=False, default=26)
    rollover_enabled = Column(Boolean, nullable=False, default=False)
    rollover_cap = Column(Integer, nullable=False, default=0)               # max credits carried one month
    purchased_expiry_months = Column(Integer, nullable=False, default=3)
    pay_per_use_enabled = Column(Boolean, nullable=False, default=True)     # cash for what credits don't cover

    @classmethod
    def for_operator(cls, operator_id: int) -> "CreditSettings":
        row = (cls.query.execution_options(skip_operator_filter=True)
               .filter_by(operator_id=operator_id).first())
        if row is None:
            row = cls(operator_id=operator_id)
            db.session.add(row)
            db.session.flush()
        return row


class RoomCategory(db.Model, PkMixin, TimestampMixin, OperatorScoped):
    """Standard / Executive / ...: what a room costs in credits and in rupees."""
    __tablename__ = "room_categories"
    __table_args__ = (db.UniqueConstraint("operator_id", "name", name="uq_room_categories_operator_name"),)

    name = Column(String(80), nullable=False)
    credits_per_slot = Column(Integer, nullable=False, default=1)           # per 30 minutes
    hourly_rate = Column(Numeric(10, 2), nullable=False, default=0)         # cash rate per hour
    is_active = Column(Boolean, nullable=False, default=True)


class SeatBand(db.Model, PkMixin, TimestampMixin, OperatorScoped):
    """Suggested monthly credits for a company by its number of seats."""
    __tablename__ = "credit_seat_bands"

    min_seats = Column(Integer, nullable=False)
    max_seats = Column(Integer, nullable=False)
    monthly_credits = Column(Integer, nullable=False)


class CreditAllocation(db.Model, PkMixin, TimestampMixin, OperatorScoped):
    """What the operator gives one company or individual from the pool each month."""
    __tablename__ = "credit_allocations"
    __table_args__ = (
        db.UniqueConstraint("operator_id", "company_id", name="uq_credit_alloc_operator_company"),
        db.UniqueConstraint("operator_id", "user_id", name="uq_credit_alloc_operator_user"),
        CheckConstraint("(company_id IS NOT NULL) OR (user_id IS NOT NULL)", name="ck_credit_alloc_target"),
    )

    company_id = Column(Integer, ForeignKey("companies.id", ondelete="CASCADE"), nullable=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    monthly_credits = Column(Integer, nullable=False, default=0)
    # A change to a running allocation starts on the next monthly cycle, never mid-month.
    pending_monthly_credits = Column(Integer, nullable=True)
    pending_from = Column(Date, nullable=True)

    company = relationship("Company", foreign_keys=[company_id])
    user = relationship("User", foreign_keys=[user_id])


class CreditLot(db.Model, PkMixin, TimestampMixin, OperatorScoped):
    """One grant of credits with its own expiry. Spending draws lots down."""
    __tablename__ = "credit_lots"
    __table_args__ = (
        CheckConstraint("(company_id IS NOT NULL) OR (user_id IS NOT NULL)", name="ck_credit_lot_target"),
        CheckConstraint("remaining >= 0", name="ck_credit_lot_remaining"),
    )

    company_id = Column(Integer, ForeignKey("companies.id", ondelete="CASCADE"), nullable=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    bucket = Column(Enum(CreditBucket), nullable=False, index=True)
    granted = Column(Integer, nullable=False)
    remaining = Column(Integer, nullable=False)
    expires_at = Column(DateTime, nullable=True, index=True)   # NULL = never
    source = Column(String(40), nullable=False)                # monthly | bonus | rollover | purchase | adjust
    period = Column(String(7), nullable=True, index=True)      # YYYY-MM, makes the monthly grant idempotent
    note = Column(String(200))

    company = relationship("Company", foreign_keys=[company_id])
    user = relationship("User", foreign_keys=[user_id])


class CreditLedger(db.Model, PkMixin, TimestampMixin, OperatorScoped):
    """Every change to a lot, signed: positive adds credits, negative removes them."""
    __tablename__ = "credit_ledger"

    lot_id = Column(Integer, ForeignKey("credit_lots.id", ondelete="CASCADE"), nullable=False, index=True)
    entry_type = Column(Enum(LedgerType), nullable=False, index=True)
    amount = Column(Integer, nullable=False)
    room_booking_id = Column(Integer, ForeignKey("room_bookings.id", ondelete="SET NULL"),
                             nullable=True, index=True)
    actor_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    note = Column(String(200))

    lot = relationship("CreditLot", foreign_keys=[lot_id])
    actor = relationship("User", foreign_keys=[actor_id])
