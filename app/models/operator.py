"""Operator — a coworking-space business that owns a slice of the platform."""
from __future__ import annotations

import enum
from datetime import datetime
from decimal import Decimal
from sqlalchemy import Column, String, Integer, ForeignKey, Boolean, Numeric, Enum, DateTime
from sqlalchemy.orm import relationship, declared_attr

from ..extensions import db
from ._mixins import PkMixin, TimestampMixin


class OperatorScoped:
    """Marks operator-owned data: gives the model a required ``operator_id`` and
    opts it into the automatic per-operator query filter and insert stamping.
    Set ``__operator_nullable__ = True`` only for rows that may also exist at
    platform level (no operator); those stay invisible to every operator."""
    __operator_nullable__ = False

    @declared_attr
    def operator_id(cls):
        return Column(Integer, ForeignKey("operators.id", ondelete="CASCADE"),
                      nullable=cls.__operator_nullable__, index=True)


class OperatorStatus(str, enum.Enum):
    TRIAL = "trial"          # invited/self-registered, pending platform approval
    ACTIVE = "active"
    HOLD = "hold"            # soft, reversible pause — Manager-grantable
    SUSPENDED = "suspended"  # hard stop — Platform Super Admin only
    CHURNED = "churned"


class Operator(db.Model, PkMixin, TimestampMixin):
    __tablename__ = "operators"

    slug = Column(String(40), unique=True, nullable=False, index=True)
    name = Column(String(200), nullable=False)
    tagline = Column(String(200))

    # Branding
    logo_url = Column(String(500))                  # public URL or signed URL
    brand_color = Column(String(20), default="#0f766e", nullable=False)
    support_email = Column(String(255))

    # Lifecycle
    plan_tier = Column(String(20), default="starter", nullable=False)
    status = Column(Enum(OperatorStatus), default=OperatorStatus.ACTIVE, nullable=False, index=True)
    # Set only for self-serve trial sign-ups (see auth.register_operator). Null
    # for staff-provisioned/invited operators — no forced deadline on those.
    trial_ends_at = Column(DateTime, nullable=True)

    # Domain mapping — one primary subdomain (adyarspace.hub1z.com) plus one optional
    # custom domain (portal.adyarspace.com). Both used by the resolver to pick an operator.
    primary_domain = Column(String(255), unique=True, index=True)
    custom_domain = Column(String(255), unique=True, index=True)

    # Localisation (previously on SystemSettings, now per-operator)
    currency_code = Column(String(3), default="INR", nullable=False)
    currency_symbol = Column(String(4), default="₹", nullable=False)
    country_code = Column(String(2), default="IN", nullable=False)
    locale = Column(String(10), default="en_IN", nullable=False)
    number_grouping = Column(String(20), default="indian", nullable=False)
    show_currency_code_after_symbol = Column(Boolean, default=False, nullable=False)
    timezone = Column(String(64), default="Asia/Kolkata", nullable=False)
    date_format = Column(String(30), default="%d-%b-%Y", nullable=False)
    datetime_format = Column(String(30), default="%d-%b-%Y %H:%M", nullable=False)
    time_format = Column(String(20), default="%H:%M", nullable=False)

    # Tax / business identity
    default_tax_rate = Column(Numeric(5, 2), default=Decimal("18.00"), nullable=False)
    tax_label = Column(String(30), default="GST", nullable=False)
    company_legal_name = Column(String(200))
    gstin = Column(String(20))
    pan = Column(String(20))
    invoice_prefix = Column(String(10), default="INV", nullable=False)

    # Manual payment instructions shown on the public operator microsite.
    payment_instructions = Column(String(500))
    payment_upi_id = Column(String(120))
    payment_gpay = Column(String(120))
    payment_bank_details = Column(String(500))
    payment_bank_account_name = Column(String(200))
    payment_bank_account_number = Column(String(60))
    payment_bank_account_type = Column(String(20))
    payment_bank_ifsc_or_routing = Column(String(30))

    # Circular with locations.operator_id, so the constraint is added after both tables exist.
    primary_location_id = Column(Integer, ForeignKey("locations.id", ondelete="SET NULL",
                                                     name="fk_operators_primary_location", use_alter=True),
                                 nullable=True, index=True)
    primary_location = relationship("Location", foreign_keys=[primary_location_id])

    @classmethod
    def default(cls) -> "Operator | None":
        return cls.query.order_by(cls.id).first()

    @classmethod
    def resolve(cls, host: str | None) -> "Operator | None":
        if not host:
            return None
        host = host.split(":")[0].lower()
        from sqlalchemy import or_
        return cls.query.filter(
            or_(cls.primary_domain == host, cls.custom_domain == host)
        ).first()

    @property
    def is_trial_expired(self) -> bool:
        return (self.status == OperatorStatus.TRIAL
                and self.trial_ends_at is not None
                and self.trial_ends_at < datetime.utcnow())

    def __repr__(self) -> str:
        return f"<Operator {self.slug}>"
