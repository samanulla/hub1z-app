"""Idempotent creation of unpublished entitlement manifest drafts."""
from decimal import Decimal

from ..extensions import db
from ..models import EntitlementOfferGrant, EntitlementOfferVersion
from .catalog import ENTITLEMENT_DEFINITIONS, ensure_catalog, ensure_entitlement_definitions

GIB = 1024 ** 3

BASE_CAPABILITIES = (
    "bookings", "calendar", "meeting_credits", "gst_invoices", "pdf_documents", "upi_payments",
    "location_qr_checkin", "manual_attendance", "member_app", "parcels", "inapp_alerts", "leads",
    "lead_email_alerts", "basic_reports", "people_admin", "announcements", "community_directory",
    "support_tickets", "payment_reminders", "audit_viewer",
)
GROWTH_CAPABILITIES = (
    "payroll", "expenses", "attendance_reports", "attendance_export", "rotating_qr_screen",
    "people_analytics", "booking_heatmap", "alert_digests", "lead_export", "audit_export",
)
SCALE_CAPABILITIES = ("white_label", "network_reports")
PROTECTED_CORE = (
    "authentication", "tenant_isolation", "two_factor", "password_reset", "audit_capture",
    "financial_settlement_and_history", "billing_recovery",
)


def _plan_spec(key, name, price, seats, locations, staff, storage_gib, open_leads,
               extra_seat, extra_location, max_locations, feature_sets, annual_price=None,
               contact_sales=False, price_from=False, early_access=False, public_features=True):
    features = list(dict.fromkeys(code for group in feature_sets for code in group))
    terms = {
        "manifest": "hub1z-pricing-entitlement-manifest-v1",
        "currency": "INR",
        "price_excludes_gst_percent": 18,
        "price_from": price_from,
        "contact_sales": contact_sales,
        "annual_price": annual_price,
        "annual_billing_months_charged": 10 if annual_price is not None else None,
        "per_included_seat_reference": {"starter_v2": 60, "growth_v2": 53, "scale_v1": 50,
                                         "enterprise_v1": 45}[key],
        "included_seats": seats,
        "included_locations": locations,
        "max_locations": max_locations,
        "extra_seat_monthly_rate": extra_seat,
        "extra_location_monthly_rate": extra_location,
        "staff_accounts": "unlimited" if staff is None else staff,
        "staff_counting_policy": "active accounts plus pending invitations; excludes deactivated accounts",
        "storage_gib": storage_gib,
        "storage_allowance": "custom" if storage_gib is None else storage_gib,
        "open_manual_leads": "unlimited" if open_leads is None else open_leads,
        "seat_grace_percent": 10,
        "seat_grace_threshold": "floor(1.10 x allowance)",
        "seat_grace_days": 7,
        "location_grace_percent": 0,
        "label": "early_access" if early_access else None,
        "public_feature_list": public_features,
        "protected_core_keys": list(PROTECTED_CORE),
        "unconfirmed_decisions": [
            "tier and action manifest", "seat grace duration and rounding", "staff account counting policy",
            "VO client scope and seat exclusion", "white-label scope", "same-operator network report semantics",
            "payment reminders included in all tiers", "lead export included in Growth and above",
            "White Label price and scope", "12-month grandfathering and legacy trial transition",
        ],
        "publication_checks": ["validate gross margin at Starter monthly price"],
        "future_inclusions_when_built": ["gst_einvoicing", "api_webhooks"] if key == "scale_v1" else [],
    }
    grants = [(code, {"boolean_value": True}) for code in features]
    grants.extend([
        ("contracted_seats", {"numeric_value": seats}),
        ("location_count", {"numeric_value": locations}),
    ])
    if staff is None:
        grants.append(("staff_accounts", {"unlimited": True}))
    else:
        grants.append(("staff_accounts", {"numeric_value": staff}))
    if storage_gib is not None:
        grants.append(("document_storage_bytes", {"numeric_value": storage_gib * GIB}))
    if open_leads is None:
        grants.append(("open_manual_leads", {"unlimited": True}))
    else:
        grants.append(("open_manual_leads", {"numeric_value": open_leads}))
    return {
        "offer_key": key,
        "version": 1,
        "kind": "base_plan",
        "status": "draft",
        "name": name,
        "currency": "INR",
        "billing_period": "monthly",
        "base_price": Decimal(str(price)),
        "publicly_listed": False,
        "terms_snapshot": terms,
        "grants": grants,
    }


def _addon_spec(key, name, price, terms, grants=(), billing_period="monthly"):
    return {
        "offer_key": key,
        "version": 1,
        "kind": "service" if billing_period == "one_time" else "addon",
        "status": "draft",
        "name": name,
        "currency": "INR",
        "billing_period": billing_period,
        "base_price": Decimal(str(price)),
        "publicly_listed": False,
        "terms_snapshot": {"manifest": "hub1z-pricing-entitlement-manifest-v1",
                   "availability": "paid_tiers_only", "trial_eligible": False, **terms},
        "grants": list(grants),
    }


def _draft_specs():
    core = (BASE_CAPABILITIES,)
    growth = (BASE_CAPABILITIES, GROWTH_CAPABILITIES)
    scale = (BASE_CAPABILITIES, GROWTH_CAPABILITIES, SCALE_CAPABILITIES)
    return [
        _plan_spec("starter_v2", "Starter", 2999, 50, 1, 3, 5, 250, 55, None, 1, core, 29990),
        _plan_spec("growth_v2", "Growth", 7999, 150, 3, None, 25, None, 49, 1999, 6, growth, 79990),
        _plan_spec("scale_v1", "Scale", 19999, 400, 8, None, 100, None, 45, 1499, 15,
                   scale, 199990, early_access=True),
        _plan_spec("enterprise_v1", "Enterprise", 44999, 1000, 15, None, None, None,
                   35, 999, "custom", scale, contact_sales=True, price_from=True, public_features=False),
        _addon_spec("extra_storage_v1", "Extra Storage", 149,
                    {"unit": "5 GiB", "blocks_new_uploads_only": True,
                     "downloads_and_deletes_remain_available": True, "auto_purge": False},
                    [("document_storage_bytes", {"numeric_value": 5 * GIB, "combine_rule": "add"})]),
        _addon_spec("white_label_v1", "White-label web portal / PWA", 2499,
                    {"scope": "web/PWA/custom domain", "dns_certificate_automation_complete": False,
                     "email_fully_white_labelled": False,
                     "expiry_policy": "keep domain resolving during notified transition; remove premium branding"},
                    [("white_label", {"boolean_value": True, "combine_rule": "enable"})]),
        _addon_spec("virtual_office_v1", "Virtual Office & NOC", 1499,
                    {"hold": True, "hold_reason": "Do not sell until active VO-client gauge and seat exclusion ship.",
                     "included_active_vo_clients": 25, "extra_client_monthly_rate": 39,
                     "proposed_client_scope": "distinct active legal party per operator",
                     "proposed_meter_key": "active_vo_clients", "meter_built": False}),
        _addon_spec("assisted_onboarding_v1", "Assisted onboarding", 4999,
                    {"service_order": True, "first_location_price": 4999,
                     "each_additional_location_price": 2499,
                     "included_for_annual_growth_and_above": True,
                     "fulfillment_workflow_built": False}, billing_period="one_time"),
    ]


def _grant_payload(grant):
    fields = ("boolean_value", "numeric_value", "unlimited", "combine_rule", "period_seconds")
    return {field: grant.get(field, False if field == "unlimited" else "add" if field == "combine_rule" else None)
            for field in fields}


def ensure_manifest_drafts():
    """Create the manifest's draft offers once; refuse to overwrite existing versions."""
    ensure_catalog()
    ensure_entitlement_definitions()
    results = []
    for spec in _draft_specs():
        for code, grant in spec["grants"]:
            if code not in ENTITLEMENT_DEFINITIONS:
                raise ValueError(f"Manifest grant references unregistered entitlement: {code}")
            if not ENTITLEMENT_DEFINITIONS[code].built:
                raise ValueError(f"Manifest draft cannot grant unbuilt entitlement: {code}")
        offer = EntitlementOfferVersion.query.filter_by(
            offer_key=spec["offer_key"], version=spec["version"]).first()
        if offer is None:
            offer = EntitlementOfferVersion(**{key: value for key, value in spec.items() if key != "grants"})
            db.session.add(offer)
            db.session.flush()
            for code, payload in spec["grants"]:
                db.session.add(EntitlementOfferGrant(
                    offer_version_id=offer.id, entitlement_key=code, scope_key="*", **payload))
        else:
            if (offer.status != "draft" or offer.publicly_listed or offer.name != spec["name"] or
                    offer.kind != spec["kind"] or offer.base_price != spec["base_price"] or
                    offer.terms_snapshot != spec["terms_snapshot"]):
                raise ValueError(f"Existing offer {spec['offer_key']} v{spec['version']} differs from manifest draft.")
            actual = {grant.entitlement_key: _grant_payload({
                "boolean_value": grant.boolean_value, "numeric_value": grant.numeric_value,
                "unlimited": grant.unlimited, "combine_rule": grant.combine_rule,
                "period_seconds": grant.period_seconds,
            }) for grant in EntitlementOfferGrant.query.filter_by(offer_version_id=offer.id).all()}
            expected = {code: _grant_payload(payload) for code, payload in spec["grants"]}
            if actual != expected:
                raise ValueError(f"Existing grants for {spec['offer_key']} v{spec['version']} differ from manifest draft.")
        results.append({"offer_key": offer.offer_key, "version": offer.version, "id": offer.id,
                        "name": offer.name, "status": offer.status, "publicly_listed": offer.publicly_listed})
    return results
