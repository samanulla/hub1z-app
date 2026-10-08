"""External workspaces on the marketplace: provisioning an approved application and recognising partner operators.

A partner is a normal operator on a hidden, free tier, so upgrading to the full product later is only a tier change.
"""
from __future__ import annotations

import re

from flask import current_app

from ..extensions import db
from ..models import (
    Floor, Location, MarketplacePartnerApplication, Operator, OperatorMarketplaceTerms, OperatorStatus, PricingTier,
    TierStatus, User, UserRole,
)
from .marketplace import MarketplaceError

PARTNER_TIER = "marketplace_partner"
INVITE_TTL_SECONDS = 60 * 60 * 24 * 7


def is_marketplace_partner(operator) -> bool:
    return bool(operator is not None and operator.plan_tier == PARTNER_TIER)


def ensure_partner_tier() -> PricingTier:
    tier = PricingTier.query.filter_by(key=PARTNER_TIER).first()
    if tier is None:
        tier = PricingTier(key=PARTNER_TIER, name="Marketplace Partner", sort_order=900, monthly_price=0,
                           status=TierStatus.ACTIVE, is_public=False, max_locations=3, max_staff_users=3,
                           max_open_leads=50, storage_mb=500,
                           description="Free listing on the Hub1z marketplace. Not shown on the pricing page.")
        db.session.add(tier)
        db.session.flush()
    return tier


def _slug_for(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:24] or "space"
    slug, n = base, 1
    while Operator.query.execution_options(skip_operator_filter=True).filter_by(slug=slug).first():
        n += 1
        slug = f"{base}-{n}"
    return slug


def provision(application: MarketplacePartnerApplication, commission_pct) -> tuple[Operator, User]:
    """Create the operator, its owner (inactive until the invite is accepted), a first location and approval."""
    if application.status != "pending":
        raise MarketplaceError("This application has already been handled.")
    email = application.email.lower()
    if User.query.execution_options(skip_operator_filter=True).filter_by(email=email).first():
        raise MarketplaceError("That email already has a Hub1z account. Ask them to apply with another address.")
    ensure_partner_tier()
    base = current_app.config.get("PLATFORM_BASE_DOMAIN", "hub1z.com")
    slug = _slug_for(application.business_name)
    operator = Operator(slug=slug, name=application.business_name, primary_domain=f"{slug}.{base}",
                        status=OperatorStatus.ACTIVE, plan_tier=PARTNER_TIER,
                        company_legal_name=application.business_name, gstin=application.gstin, pan=application.pan,
                        gst_state=(application.gstin or "")[:2] or None, support_email=application.email,
                        payment_upi_id=application.upi_id)
    db.session.add(operator)
    db.session.flush()
    owner = User(operator_id=operator.id, email=email, full_name=application.contact_name,
                 phone=application.phone, role=UserRole.SUPER_ADMIN, is_active=False)
    owner.set_password(current_app.config["SECRET_KEY"] + email)
    db.session.add(owner)
    location = Location(operator_id=operator.id, name=application.business_name[:150], code="MAIN",
                        address_line1=application.address_line1, city=application.city, state=application.state,
                        postal_code=application.postal_code, country="India", timezone="Asia/Kolkata")
    db.session.add(location)
    db.session.flush()
    db.session.add(Floor(operator_id=operator.id, location_id=location.id, level=1, name="Ground"))
    operator.primary_location_id = location.id
    db.session.add(OperatorMarketplaceTerms(operator_id=operator.id, enabled=False, kyc_approved=True,
                                            commission_pct=commission_pct,
                                            payment_methods=["manual_upi", "pay_at_venue"]))
    application.status = "approved"
    application.operator_id = operator.id
    if application.lead_id:
        from datetime import datetime
        from ..models import Lead
        lead = Lead.query.execution_options(skip_operator_filter=True).filter_by(id=application.lead_id).first()
        if lead is not None:
            lead.stage = "won"
            lead.closed_at = datetime.utcnow()
    db.session.flush()
    return operator, owner
