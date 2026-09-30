"""Community & premium features (WeWork-parity MVP).

Guest passes, visitors, community directory opt-in, announcements, printing,
support tickets, lockers, referrals — thin models + relationships to plug
into simple CRUD routes.
"""
from __future__ import annotations

import enum
import secrets
from datetime import date, datetime

from sqlalchemy import (
    Column, String, Text, Integer, DateTime, Date, Enum, Boolean,
    Numeric, ForeignKey,
)
from sqlalchemy.orm import relationship

from ..extensions import db
from ._mixins import PkMixin, TimestampMixin
from .operator import OperatorScoped


# ---------------- Guest pass ----------------

class GuestPassStatus(str, enum.Enum):
    ISSUED = "issued"
    USED = "used"
    CANCELLED = "cancelled"


class GuestPass(db.Model, PkMixin, TimestampMixin, OperatorScoped):
    __tablename__ = "guest_passes"
    issuer_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"),
                       nullable=True)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="SET NULL"),
                        nullable=True, index=True)
    location_id = Column(Integer, ForeignKey("locations.id", ondelete="CASCADE"),
                         nullable=False, index=True)
    guest_name = Column(String(150), nullable=False)
    guest_email = Column(String(255), nullable=True)
    visit_date = Column(Date, nullable=False, default=date.today, index=True)
    code = Column(String(32), nullable=False, unique=True, index=True)
    status = Column(Enum(GuestPassStatus), nullable=False,
                    default=GuestPassStatus.ISSUED, index=True)
    used_at = Column(DateTime, nullable=True)

    issuer = relationship("User", foreign_keys=[issuer_id])
    company = relationship("Company", foreign_keys=[company_id])
    location = relationship("Location", foreign_keys=[location_id])

    @staticmethod
    def new_code() -> str:
        return secrets.token_urlsafe(9)


# ---------------- Visitor pre-registration ----------------

class VisitorStatus(str, enum.Enum):
    PENDING = "pending"
    CHECKED_IN = "checked_in"
    CHECKED_OUT = "checked_out"
    CANCELLED = "cancelled"


class Visitor(db.Model, PkMixin, TimestampMixin, OperatorScoped):
    __tablename__ = "visitors"
    host_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"),
                          nullable=True, index=True)
    location_id = Column(Integer, ForeignKey("locations.id", ondelete="CASCADE"),
                         nullable=False, index=True)
    name = Column(String(150), nullable=False)
    email = Column(String(255), nullable=True)
    phone = Column(String(30), nullable=True)
    company = Column(String(150), nullable=True)
    expected_at = Column(DateTime, nullable=False, index=True)
    purpose = Column(String(255), nullable=True)
    status = Column(Enum(VisitorStatus), nullable=False,
                    default=VisitorStatus.PENDING, index=True)
    checked_in_at = Column(DateTime, nullable=True)
    checked_out_at = Column(DateTime, nullable=True)

    host = relationship("User", foreign_keys=[host_user_id])
    location = relationship("Location", foreign_keys=[location_id])


# ---------------- Community directory (opt-in) ----------------

class CommunityProfile(db.Model, PkMixin, TimestampMixin, OperatorScoped):
    __tablename__ = "community_profiles"
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"),
                     nullable=False, unique=True, index=True)
    headline = Column(String(200), nullable=True)
    bio = Column(Text, nullable=True)
    skills = Column(String(500), nullable=True)  # comma-separated
    linkedin_url = Column(String(300), nullable=True)
    is_public = Column(Boolean, nullable=False, default=False, index=True)

    user = relationship("User", foreign_keys=[user_id])


# ---------------- Announcements / notice board ----------------

class Announcement(db.Model, PkMixin, TimestampMixin, OperatorScoped):
    __tablename__ = "announcements"
    location_id = Column(Integer, ForeignKey("locations.id", ondelete="CASCADE"),
                         nullable=True, index=True)  # NULL = all locations
    author_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"),
                       nullable=True)
    title = Column(String(200), nullable=False)
    body = Column(Text, nullable=False)
    is_pinned = Column(Boolean, nullable=False, default=False)
    published_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)

    location = relationship("Location", foreign_keys=[location_id])
    author = relationship("User", foreign_keys=[author_id])


# ---------------- Printing credits ----------------

class PrintingLedger(db.Model, PkMixin, TimestampMixin, OperatorScoped):
    """Positive = credited, negative = used."""
    __tablename__ = "printing_ledger"
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"),
                     nullable=False, index=True)
    delta = Column(Integer, nullable=False)   # +credits, -pages
    note = Column(String(200), nullable=True)

    user = relationship("User", foreign_keys=[user_id])


# ---------------- Support tickets ----------------

class TicketStatus(str, enum.Enum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    CLOSED = "closed"


class TicketPriority(str, enum.Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class SupportTicket(db.Model, PkMixin, TimestampMixin, OperatorScoped):
    __tablename__ = "support_tickets"
    submitter_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"),
                          nullable=True, index=True)
    location_id = Column(Integer, ForeignKey("locations.id", ondelete="CASCADE"),
                         nullable=True, index=True)
    subject = Column(String(200), nullable=False)
    body = Column(Text, nullable=False)
    status = Column(Enum(TicketStatus), nullable=False,
                    default=TicketStatus.OPEN, index=True)
    priority = Column(Enum(TicketPriority), nullable=False,
                      default=TicketPriority.NORMAL)
    resolved_at = Column(DateTime, nullable=True)

    submitter = relationship("User", foreign_keys=[submitter_id])
    location = relationship("Location", foreign_keys=[location_id])


# ---------------- Lockers ----------------

class LockerStatus(str, enum.Enum):
    AVAILABLE = "available"
    ASSIGNED = "assigned"
    MAINTENANCE = "maintenance"


class Locker(db.Model, PkMixin, TimestampMixin, OperatorScoped):
    __tablename__ = "lockers"
    location_id = Column(Integer, ForeignKey("locations.id", ondelete="CASCADE"),
                         nullable=False, index=True)
    code = Column(String(40), nullable=False)
    monthly_rate = Column(Numeric(10, 2), nullable=False, default=0)
    status = Column(Enum(LockerStatus), nullable=False,
                    default=LockerStatus.AVAILABLE, index=True)
    assigned_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"),
                              nullable=True, index=True)
    assigned_at = Column(Date, nullable=True)

    location = relationship("Location", foreign_keys=[location_id])
    assigned_user = relationship("User", foreign_keys=[assigned_user_id])


# ---------------- Referrals ----------------

class ReferralStatus(str, enum.Enum):
    PENDING = "pending"
    SIGNED_UP = "signed_up"
    CREDITED = "credited"
    EXPIRED = "expired"


class Referral(db.Model, PkMixin, TimestampMixin, OperatorScoped):
    __tablename__ = "referrals"
    referrer_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"),
                         nullable=False, index=True)
    referred_email = Column(String(255), nullable=False, index=True)
    code = Column(String(32), nullable=False, unique=True, index=True)
    reward_credits = Column(Integer, nullable=False, default=0)
    status = Column(Enum(ReferralStatus), nullable=False,
                    default=ReferralStatus.PENDING, index=True)

    referrer = relationship("User", foreign_keys=[referrer_id])

    @staticmethod
    def new_code() -> str:
        return secrets.token_urlsafe(6)
