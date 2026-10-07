"""Read-only, allowlisted views of operator data for the public marketplace.

The marketplace host has no tenant, so the automatic operator filter is off there. Everything shown to a
stranger therefore goes through these functions, which return plain dataclasses built from an explicit set of
fields, never ORM objects, so a template cannot reach a field that was not chosen here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from flask import current_app, request

from ..extensions import db
from ..models import (
    Location, MarketplaceBooking, MarketplaceListing, Operator, OperatorMarketplaceTerms,
)
from ..models.marketplace import CANCELLATION_PRESETS
from ..models.operator import OperatorStatus
from . import marketplace as mk

READ = {"marketplace_read": True, "skip_operator_filter": True}
DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


@dataclass(frozen=True)
class PublicListing:
    id: int
    title: str
    kind: str
    description: str
    price: Decimal
    gst_pct: Decimal
    unit: str
    approval_mode: str
    seller_name: str
    seller_gstin: str
    seller_contact: str
    location_name: str
    city: str
    state: str
    open_text: str
    min_lead_hours: int
    max_length_hours: int
    max_guests: int | None
    id_required: bool
    house_rules: str
    cancellation_text: str
    payment_methods: list[str] = field(default_factory=list)
    access_start: str = "09:00"
    access_end: str = "18:00"


def _windows_text(listing: MarketplaceListing) -> str:
    windows = listing.availability_windows or []
    if not windows:
        return "Every day, all day"
    parts = []
    for w in windows:
        days = sorted(w.get("days", range(7)))
        label = "Every day" if len(days) == 7 else ", ".join(DAY_NAMES[d] for d in days)
        parts.append(f"{label}, {w.get('from', '00:00')} to {w.get('to', '23:59')}")
    return "; ".join(parts)


def _cancellation_text(key: str) -> str:
    preset = CANCELLATION_PRESETS.get(key, CANCELLATION_PRESETS["flexible"])
    return (f"{preset['label']}: free cancellation up to {preset['free_hours']} hours before the start, "
            f"{preset['late_refund_pct']}% refund after that. If the space cancels, you are refunded in full.")


def _project(listing, location, operator, terms) -> PublicListing:
    rules = listing.guest_rules or {}
    visible = (listing.visibility or {}).get("description", True)
    window = (listing.availability_windows or [{}])[0]
    return PublicListing(
        id=listing.id, title=listing.title, kind=listing.resource_type,
        description=(listing.description or "") if visible else "",
        price=listing.price, gst_pct=listing.gst_rate_pct,
        unit="per hour" if listing.resource_type == "room" else "per day",
        approval_mode=listing.approval_mode,
        seller_name=operator.company_legal_name or operator.name, seller_gstin=operator.gstin or "",
        seller_contact=operator.support_email or "",
        location_name=location.name, city=location.city or "", state=location.state or "",
        open_text=_windows_text(listing), min_lead_hours=listing.min_lead_hours,
        max_length_hours=listing.max_length_hours, max_guests=rules.get("max_guests"),
        id_required=bool(rules.get("id_required")), house_rules=rules.get("house_rules", ""),
        cancellation_text=_cancellation_text(listing.cancellation_preset),
        payment_methods=list(listing.payment_methods or terms.payment_methods or []),
        access_start=window.get("from", "09:00"), access_end=window.get("to", "18:00"))


def _base_query():
    return (db.session.query(MarketplaceListing, Location, Operator, OperatorMarketplaceTerms)
            .join(Location, Location.id == MarketplaceListing.location_id)
            .join(Operator, Operator.id == MarketplaceListing.operator_id)
            .join(OperatorMarketplaceTerms, OperatorMarketplaceTerms.operator_id == MarketplaceListing.operator_id)
            .filter(MarketplaceListing.status == "live", OperatorMarketplaceTerms.enabled.is_(True),
                    OperatorMarketplaceTerms.kyc_approved.is_(True),
                    Operator.status.in_((OperatorStatus.ACTIVE, OperatorStatus.TRIAL)))
            .execution_options(**READ))


def search(city: str = "", kind: str = "") -> list[PublicListing]:
    q = _base_query()
    if city:
        q = q.filter(Location.city.ilike(city.strip()))
    if kind in ("room", "day_access"):
        q = q.filter(MarketplaceListing.resource_type == kind)
    rows = q.order_by(Location.city, MarketplaceListing.price).limit(60).all()
    return [_project(*row) for row in rows]


def cities() -> list[str]:
    rows = (_base_query().with_entities(Location.city).distinct().order_by(Location.city).all())
    return [c for (c,) in rows if c]


def listing_detail(listing_id: int) -> PublicListing | None:
    row = _base_query().filter(MarketplaceListing.id == listing_id).first()
    return _project(*row) if row else None


def listing_for_booking(listing_id: int) -> MarketplaceListing | None:
    """The ORM row for the booking engine, only if it is publicly bookable."""
    row = _base_query().filter(MarketplaceListing.id == listing_id).first()
    return row[0] if row else None


# ----------------------------------------------------------------- guest --

@dataclass(frozen=True)
class GuestBooking:
    code: str
    title: str
    kind: str
    status: str
    payment_status: str
    payment_method: str
    id_status: str
    id_reject_reason: str
    id_required: bool
    start_at: datetime
    end_at: datetime
    units: int
    guests: int
    subtotal: Decimal
    gst_amount: Decimal
    total: Decimal
    seller_name: str
    seller_contact: str
    location_name: str
    city: str
    reveal: bool
    address: str
    access_instructions: str
    house_rules: str
    cancellation_text: str
    pay_vpa: str | None
    pay_upi_id: str
    pay_bank: str
    pay_payee: str
    pay_instructions: str
    payment_reference: str
    timezone: str
    refund_if_cancelled_pct: int


def _guest(booking, listing, location, operator) -> GuestBooking:
    from . import upi
    reveal = mk.access_revealed(booking)
    pay = upi.operator_details(operator) if booking.status == "held" and booking.payment_status in (
        "unpaid", "pending_verification") and booking.payment_method in ("manual_upi", "bank_transfer") else {}
    address = ""
    if reveal:
        address = ", ".join(p for p in (location.address_line1, location.address_line2, location.city,
                                        location.state, location.postal_code) if p)
    return GuestBooking(
        code=booking.code, title=listing.title, kind=listing.resource_type, status=booking.status,
        payment_status=booking.payment_status, payment_method=booking.payment_method or "",
        id_status=booking.id_status, id_reject_reason=booking.id_reject_reason or "",
        id_required=booking.id_status != "not_required", start_at=booking.start_at, end_at=booking.end_at,
        units=booking.units, guests=booking.guests, subtotal=booking.subtotal, gst_amount=booking.gst_amount,
        total=booking.total, seller_name=operator.company_legal_name or operator.name,
        seller_contact=operator.support_email or "", location_name=location.name, city=location.city or "",
        reveal=reveal, address=address, access_instructions=(listing.access_instructions or "") if reveal else "",
        house_rules=(listing.guest_rules or {}).get("house_rules", ""),
        cancellation_text=_cancellation_text(booking.cancellation_preset),
        pay_vpa=pay.get("vpa"), pay_upi_id=pay.get("upi_id") or "", pay_bank=pay.get("bank") or "",
        pay_payee=pay.get("payee") or "", pay_instructions=pay.get("instructions") or "",
        payment_reference=booking.payment_reference or "", timezone=location.timezone or "UTC",
        refund_if_cancelled_pct=mk.refund_pct(booking, by_operator=False))


def _guest_query(customer_id: int):
    return (db.session.query(MarketplaceBooking, MarketplaceListing, Location, Operator)
            .join(MarketplaceListing, MarketplaceListing.id == MarketplaceBooking.listing_id)
            .join(Location, Location.id == MarketplaceListing.location_id)
            .join(Operator, Operator.id == MarketplaceBooking.operator_id)
            .filter(MarketplaceBooking.customer_id == customer_id)
            .execution_options(**READ))


def guest_bookings(customer_id: int) -> list[GuestBooking]:
    rows = _guest_query(customer_id).order_by(MarketplaceBooking.start_at.desc()).limit(100).all()
    return [_guest(*row) for row in rows]


def guest_booking(customer_id: int, code: str) -> GuestBooking | None:
    row = _guest_query(customer_id).filter(MarketplaceBooking.code == code.upper()).first()
    return _guest(*row) if row else None


def booking_row(customer_id: int, code: str) -> MarketplaceBooking | None:
    """The ORM booking for a state change, only ever the signed-in customer's own."""
    row = _guest_query(customer_id).filter(MarketplaceBooking.code == code.upper()).first()
    return row[0] if row else None


def marketplace_url(path: str = "") -> str:
    """Absolute link to the public marketplace from any host."""
    from .operator_resolver import marketplace_host
    host = marketplace_host(current_app)
    scheme, port = "https", ""
    if current_app.debug or current_app.testing:
        scheme = request.scheme if request else "http"
        port = request.host.partition(":")[2] if request else ""
    return f"{scheme}://{host}{':' + port if port else ''}/marketplace{path}"
