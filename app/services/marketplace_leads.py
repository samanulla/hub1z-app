"""Enquiries that start outside the booking flow: virtual office plans and new partner workspaces."""
from __future__ import annotations

from flask import current_app

from ..extensions import db
from ..models import (
    Lead, MarketplaceListing, MarketplacePartnerApplication, Operator, User, UserRole,
)
from . import mail_service
from .marketplace import MarketplaceError


def vo_enquiry(listing: MarketplaceListing, *, name: str, email: str, phone: str = "", company: str = "",
               message: str = "") -> Lead:
    """A virtual office enquiry lands in the operator's own Leads board; KYC and agreement follow there."""
    if listing.resource_type != "virtual_office":
        raise MarketplaceError("This listing doesn't take enquiries.")
    if not name.strip() or "@" not in email:
        raise MarketplaceError("Enter your name and a valid email address.")
    operator = Operator.query.execution_options(skip_operator_filter=True).filter_by(id=listing.operator_id).one()
    lead = Lead(operator_id=listing.operator_id, name=name.strip()[:160], email=email.strip()[:255],
                phone=(phone or "").strip()[:40] or None, company_name=(company or "").strip()[:200] or None,
                interest=f"Virtual office: {listing.title}"[:200], notes=(message or "").strip()[:2000] or None,
                source="Hub1z Marketplace", is_website_enquiry=True, stage="new")
    db.session.add(lead)
    db.session.commit()
    staff = User.query.execution_options(skip_operator_filter=True).filter(
        User.operator_id == listing.operator_id, User.is_active.is_(True),
        User.role.in_((UserRole.SUPER_ADMIN, UserRole.MANAGER))).all()
    for person in staff:
        try:
            mail_service.send(f"New virtual office enquiry for {operator.name}", person.email, "lead_enquiry",
                              lead=lead, operator=operator)
        except Exception:  # noqa: BLE001 - the enquiry is saved; a mail failure must not lose it
            current_app.logger.exception("Virtual office enquiry email failed")
    return lead


def partner_application(*, business_name: str, contact_name: str, email: str, phone: str, address_line1: str,
                        city: str, state: str, postal_code: str, gstin: str, pan: str, upi_id: str):
    """A workspace outside Hub1z applies to list. It becomes a platform lead plus a structured application."""
    for label, value in (("business name", business_name), ("contact name", contact_name),
                         ("address", address_line1), ("city", city)):
        if not (value or "").strip():
            raise MarketplaceError(f"Enter your {label}.")
    if "@" not in email:
        raise MarketplaceError("Enter a valid email address.")
    if MarketplacePartnerApplication.query.filter_by(email=email.strip().lower(), status="pending").first():
        raise MarketplaceError("We already have an application from this email. We'll be in touch soon.")
    lead = Lead(operator_id=None, name=contact_name.strip()[:160], company_name=business_name.strip()[:200],
                email=email.strip()[:255], phone=(phone or "").strip()[:40] or None,
                interest=f"Marketplace listing, {city.strip()}"[:200], source="Marketplace partner", stage="new")
    db.session.add(lead)
    db.session.flush()
    app = MarketplacePartnerApplication(
        business_name=business_name.strip()[:200], contact_name=contact_name.strip()[:150],
        email=email.strip().lower()[:255], phone=(phone or "").strip()[:30] or None,
        address_line1=address_line1.strip()[:255], city=city.strip()[:80], state=(state or "").strip()[:80] or None,
        postal_code=(postal_code or "").strip()[:20] or None, gstin=(gstin or "").strip().upper()[:20] or None,
        pan=(pan or "").strip().upper()[:20] or None, upi_id=(upi_id or "").strip()[:120] or None, lead_id=lead.id)
    db.session.add(app)
    db.session.commit()
    try:
        mail_service.send("New marketplace partner application", current_app.config["PLATFORM_SUPPORT_EMAIL"],
                          "marketplace_partner_application", application=app)
    except Exception:  # noqa: BLE001 - the application is saved either way
        current_app.logger.exception("Partner application email failed")
    return app
