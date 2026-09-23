"""User model and role enum."""
from __future__ import annotations

import enum
import json
from flask_login import UserMixin
from sqlalchemy import (
    Column, String, Boolean, Enum, ForeignKey, Integer, Text,
    UniqueConstraint, Index, text,
)
from sqlalchemy.orm import relationship
from werkzeug.security import generate_password_hash, check_password_hash

from ..extensions import db
from ._mixins import PkMixin, TimestampMixin
from .tenant import TenantScoped


class UserRole(str, enum.Enum):
    PLATFORM_OWNER = "platform_owner"  # SaaS operator — manages tenants; not scoped to one
    PLATFORM_MANAGER = "platform_manager"  # Platform staff/contractor with admin-granted feature access
    SUPER_ADMIN = "super_admin"        # Tenant owner — full access within one tenant
    MANAGER = "manager"                # Tenant operations manager (day-to-day, no destructive actions)
    LOCATION_MANAGER = "location_manager"  # Manages a specific location
    COMPANY_ADMIN = "company_admin"    # Admin of a subscribing company
    EMPLOYEE = "employee"              # Employee of a subscribing company
    INDIVIDUAL = "individual"          # Independent member (no company)


# Feature areas a Platform Super Admin can grant to / revoke from a Platform
# Manager. (key, label, description) — Platform Owners implicitly have all of
# them; a Manager only has what's in their `platform_permissions`.
PLATFORM_FEATURES: list[tuple[str, str, str]] = [
    ("tenants", "Tenants", "Provision, edit, suspend/activate coworking businesses"),
    ("billing", "Billing & accounting", "Tenant plan tiers and custom-domain access/surcharge"),
    ("reports", "Reports", "Cross-tenant analytics"),
]
PLATFORM_FEATURE_KEYS = {key for key, _, _ in PLATFORM_FEATURES}


class User(db.Model, PkMixin, TimestampMixin, UserMixin, TenantScoped):
    __tablename__ = "users"
    # Email is unique per-tenant; a second partial unique index enforces
    # a single platform-owner row per email (tenant_id IS NULL).
    __table_args__ = (
        UniqueConstraint("tenant_id", "email", name="uq_users_tenant_email"),
        Index(
            "uq_users_platform_email",
            "email",
            unique=True,
            postgresql_where=text("tenant_id IS NULL"),
            sqlite_where=text("tenant_id IS NULL"),
        ),
    )

    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"),
                       nullable=True, index=True)
    tenant = relationship("Tenant", foreign_keys=[tenant_id])

    email = Column(String(255), nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    full_name = Column(String(150), nullable=False)
    phone = Column(String(30))
    role = Column(Enum(UserRole), nullable=False, default=UserRole.INDIVIDUAL, index=True)
    is_active = Column(Boolean, default=True, nullable=False)
    email_verified = Column(Boolean, default=False, nullable=False)

    # 2FA (TOTP)
    two_factor_secret = Column(String(64), nullable=True)
    two_factor_enabled = Column(Boolean, default=False, nullable=False)

    # JSON-encoded list of PLATFORM_FEATURES keys — only meaningful for
    # role=PLATFORM_MANAGER. Set by a Platform Super Admin.
    platform_permissions = Column(Text, nullable=True)

    # Optional company link (for company_admin & employee)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="SET NULL"), nullable=True, index=True)
    company = relationship("Company", back_populates="users", foreign_keys=[company_id])

    # Optional location scoping (for location_manager)
    managed_location_id = Column(Integer, ForeignKey("locations.id", ondelete="SET NULL"), nullable=True)
    managed_location = relationship("Location", foreign_keys=[managed_location_id])

    # Reverse
    seat_bookings = relationship("SeatBooking", back_populates="user", cascade="all, delete-orphan")
    room_bookings = relationship("RoomBooking", back_populates="user", cascade="all, delete-orphan")
    allocations = relationship("SeatAllocation", back_populates="user")
    subscriptions = relationship(
        "Subscription", back_populates="user",
        foreign_keys="Subscription.user_id",
    )

    # ---- password helpers ----
    def set_password(self, raw: str) -> None:
        self.password_hash = generate_password_hash(raw)

    def check_password(self, raw: str) -> bool:
        return check_password_hash(self.password_hash, raw)

    # ---- role helpers ----
    @property
    def is_super_admin(self) -> bool:
        return self.role == UserRole.SUPER_ADMIN

    @property
    def is_platform_owner(self) -> bool:
        return self.role == UserRole.PLATFORM_OWNER

    @property
    def is_platform_manager(self) -> bool:
        return self.role == UserRole.PLATFORM_MANAGER

    @property
    def is_platform_staff(self) -> bool:
        """Works at the platform (hub1z.com) level — Owner or Manager."""
        return self.role in {UserRole.PLATFORM_OWNER, UserRole.PLATFORM_MANAGER}

    def get_platform_permissions(self) -> list[str]:
        """Feature keys this user can use under /platform/*. Owners get all of them."""
        if self.role == UserRole.PLATFORM_OWNER:
            return sorted(PLATFORM_FEATURE_KEYS)
        if self.role != UserRole.PLATFORM_MANAGER or not self.platform_permissions:
            return []
        try:
            perms = json.loads(self.platform_permissions)
        except (TypeError, ValueError):
            return []
        return [p for p in perms if p in PLATFORM_FEATURE_KEYS]

    def set_platform_permissions(self, keys: list[str]) -> None:
        self.platform_permissions = json.dumps(sorted(set(keys) & PLATFORM_FEATURE_KEYS))

    def has_platform_permission(self, feature: str) -> bool:
        if self.role == UserRole.PLATFORM_OWNER:
            return True
        return feature in self.get_platform_permissions()

    @property
    def is_manager(self) -> bool:
        return self.role == UserRole.MANAGER

    @property
    def is_location_manager(self) -> bool:
        return self.role == UserRole.LOCATION_MANAGER

    @property
    def is_admin(self) -> bool:
        return self.role in {UserRole.PLATFORM_OWNER, UserRole.SUPER_ADMIN,
                             UserRole.MANAGER, UserRole.LOCATION_MANAGER}

    @property
    def is_company_admin(self) -> bool:
        return self.role == UserRole.COMPANY_ADMIN

    @property
    def is_member(self) -> bool:
        return self.role in {UserRole.EMPLOYEE, UserRole.INDIVIDUAL}

    def __repr__(self) -> str:
        return f"<User {self.email} ({self.role.value})>"
