"""Hub1z's sellable feature catalog.

Codes are fixed here because the app enforces them. Platform admin edits the
name, description, price, availability and which tier includes each one
(PlatformModule rows); it cannot invent a code the app does not know about.

kind:
  always  - part of every plan, listed on the pricing page, never locked
  feature - lockable; included by ticking it on a tier (or by the tier's "all features")
  addon   - paid add-on on top of any plan
  usage   - pay-per-use charge that lands on the next Hub1z invoice

"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

AVAILABLE, BETA, COMING_SOON, HIDDEN = "available", "beta", "coming_soon", "hidden"
FUTURE = COMING_SOON
AVAILABILITY_CHOICES = [(AVAILABLE, "Available"), (BETA, "Beta"),
                        (COMING_SOON, "Coming soon"), (HIDDEN, "Hidden")]


class EntitlementValueType(str, Enum):
    BOOLEAN = "boolean"
    ALLOWANCE = "allowance"
    USAGE = "usage"

ALWAYS, FEATURE, ADDON, USAGE = "always", "feature", "addon", "usage"
KIND_LABELS = {ALWAYS: "Included in every plan", FEATURE: "Plan features", ADDON: "Paid add-ons",
               USAGE: "Pay-per-use"}
KIND_ORDER = [ALWAYS, FEATURE, ADDON, USAGE]

@dataclass(frozen=True)
class EntitlementDefinitionSpec:
    key: str
    name: str
    value_type: EntitlementValueType
    unit: str = ""
    measurement: str = "capability"
    built: bool = True
    protected_actions: tuple[str, ...] = ()


@dataclass(frozen=True)
class CatalogEntry:
    code: str
    name: str
    kind: str
    description: str = ""
    availability: str = AVAILABLE
    built: bool = True            # False = the app cannot deliver it yet, so it can never be set to Available
    unit_label: str = ""
    default_growth: bool = False  # ticked on the seeded Growth tier
    value_type: EntitlementValueType = EntitlementValueType.BOOLEAN


_ALWAYS = [
    ("bookings", "Bookings"), ("calendar", "Calendar"), ("meeting_credits", "Meeting room credits"),
    ("gst_invoices", "GST invoices"), ("pdf_documents", "PDF documents"),
    ("upi_payments", "UPI QR payments with manual confirmation"),
    ("location_qr_checkin", "Location QR check-in"), ("manual_attendance", "Manual attendance entry"),
    ("member_app", "Member PWA"),
    ("parcels", "Parcels"), ("inapp_alerts", "In-app alerts"), ("leads", "Leads"),
    ("lead_email_alerts", "Email lead notifications"), ("basic_reports", "Basic reports"),
    ("people_admin", "People and member administration"), ("announcements", "Announcements"),
    ("community_directory", "Community directory"), ("support_tickets", "Support tickets"),
    ("audit_capture", "Audit capture"), ("audit_viewer", "Audit viewer"),
]

_FEATURES = [
    ("rotating_qr_screen", "Rotating reception QR screen", "A reception display with a QR code that changes every few minutes."),
    ("attendance_reports", "Attendance reports", "Attendance history beyond the last 7 days."),
    ("attendance_export", "Attendance CSV export", "Download attendance as a CSV file."),
    ("lead_export", "Lead export", "Download leads as a CSV file."),
    ("advanced_reports", "Advanced reporting", "People and heatmap reports, plus new advanced reports as they ship."),
    ("alert_digests", "Alert email digests", "Emailed digests of parcels, agreements and overdue invoices."),
    ("payment_reminders", "Payment reminders", "Automatic reminder emails to customers with unpaid invoices."),
    ("payroll", "Payroll", "Salary structures, payroll runs and payslips."),
    ("expenses", "Expenses", "Expense tracking and approvals."),
    ("audit_export", "Audit log exports", "Download the audit log as a CSV file."),
]

_ADDONS = [
    CatalogEntry("virtual_office", "Virtual Office & NOC", ADDON,
                 "Virtual office plans and NOC / address letters for customers."),
    CatalogEntry("white_label", "White-label web portal / PWA", ADDON,
                 "Custom domain and Hub1z branding removal on the web/PWA portal."),
    CatalogEntry("extra_storage", "Extra Storage", ADDON,
                 "More document storage on top of the plan allowance.", unit_label="per 5 GB",
                 value_type=EntitlementValueType.ALLOWANCE),
    CatalogEntry("accounting_sync", "Accounting Sync", ADDON,
                 "Sync invoices and payments to your accounting software.", COMING_SOON, built=False),
    CatalogEntry("api_webhooks", "API & Webhooks", ADDON,
                 "API keys and webhooks to connect your own tools.", COMING_SOON, built=False),
    CatalogEntry("gst_einvoicing", "GST E-Invoicing", ADDON,
                 "Generate IRN and QR codes through the GST e-invoice portal.", COMING_SOON, built=False),
    CatalogEntry("marketplace_listing", "Marketplace Listing", ADDON,
                 "List shared rooms and day access on the Hub1z marketplace.", COMING_SOON, built=False),
    CatalogEntry("marketplace_featured", "Marketplace Featured Placement", ADDON,
                 "Featured placement in Hub1z marketplace search.", COMING_SOON, built=False),
    CatalogEntry("featured_listing", "Featured Listing", ADDON,
                 "Be featured in the Hub1z space directory.", COMING_SOON, built=False),
    CatalogEntry("online_payments", "Online Payments (Razorpay)", ADDON,
                 "Collect cards, netbanking and UPI with automatic confirmation.", COMING_SOON, built=False),
    CatalogEntry("whatsapp_packs", "WhatsApp Messaging Packs", ADDON,
                 "Send reminders and alerts on WhatsApp.", COMING_SOON, built=False),
    CatalogEntry("multi_gstin", "Multiple GSTINs", ADDON,
                 "Manage multiple seller registrations.", COMING_SOON, built=False),
    CatalogEntry("native_apps", "Native mobile apps", ADDON,
                 "Branded iOS and Android applications.", COMING_SOON, built=False),
    CatalogEntry("franchise_tenancy", "Franchise tenancy", ADDON,
                 "Manage separately isolated franchise operators.", COMING_SOON, built=False),
    CatalogEntry("sso", "Single sign-on", ADDON,
                 "Authenticate operator teams through an identity provider.", COMING_SOON, built=False),
    CatalogEntry("customer_sandbox", "Customer sandbox", ADDON,
                 "Operate an isolated customer test environment.", COMING_SOON, built=False),
    CatalogEntry("sla_fulfillment", "SLA fulfillment", ADDON,
                 "Contracted service-level and support commitments.", COMING_SOON, built=False),
]

_USAGE = [
    CatalogEntry("pan_verification", "PAN verification", USAGE,
                 "Live PAN check against government records.", COMING_SOON, built=False,
                 unit_label="per verification", value_type=EntitlementValueType.USAGE),
    CatalogEntry("gstin_verification", "GSTIN verification", USAGE,
                 "Live GSTIN check against the GST portal.", COMING_SOON, built=False,
                 unit_label="per verification", value_type=EntitlementValueType.USAGE),
]

CATALOG: list[CatalogEntry] = (
    [CatalogEntry(code, name, ALWAYS) for code, name in _ALWAYS]
    + [CatalogEntry(code, name, FEATURE, desc, default_growth=True) for code, name, desc in _FEATURES]
    + _ADDONS + _USAGE
)

BY_CODE = {e.code: e for e in CATALOG}
LOCKABLE_CODES = [e.code for e in CATALOG if e.kind == FEATURE]

ENTITLEMENT_DEFINITIONS = {
    entry.code: EntitlementDefinitionSpec(
        key=entry.code, name=entry.name, value_type=entry.value_type,
        unit=entry.unit_label, built=entry.built,
        measurement="period" if entry.value_type == EntitlementValueType.USAGE else "capability")
    for entry in CATALOG
}
ENTITLEMENT_DEFINITIONS.update({
    "tenant_isolation": EntitlementDefinitionSpec("tenant_isolation", "Tenant isolation",
        EntitlementValueType.BOOLEAN, protected_actions=("read", "write", "execute")),
    "authentication": EntitlementDefinitionSpec("authentication", "Authentication",
        EntitlementValueType.BOOLEAN, protected_actions=("read", "write", "execute")),
    "financial_settlement": EntitlementDefinitionSpec("financial_settlement", "Financial settlement",
        EntitlementValueType.BOOLEAN, protected_actions=("read", "settle", "correct")),
    "existing_bookings": EntitlementDefinitionSpec("existing_bookings", "Existing bookings",
        EntitlementValueType.BOOLEAN, protected_actions=("read", "cancel", "checkin", "settle")),
    "document_downloads": EntitlementDefinitionSpec("document_downloads", "Owned document downloads",
        EntitlementValueType.BOOLEAN, protected_actions=("read", "download", "delete")),
    "audit_capture": EntitlementDefinitionSpec("audit_capture", "Audit capture",
        EntitlementValueType.BOOLEAN, protected_actions=("capture", "read")),
    "two_factor": EntitlementDefinitionSpec("two_factor", "Two-factor authentication",
        EntitlementValueType.BOOLEAN, protected_actions=("verify", "disable")),
    "password_reset": EntitlementDefinitionSpec("password_reset", "Password reset",
        EntitlementValueType.BOOLEAN, protected_actions=("recover",)),
    "billing_recovery": EntitlementDefinitionSpec("billing_recovery", "Billing recovery",
        EntitlementValueType.BOOLEAN, protected_actions=("read", "pay", "recover")),
    "financial_settlement_and_history": EntitlementDefinitionSpec(
        "financial_settlement_and_history", "Financial settlement and history",
        EntitlementValueType.BOOLEAN, protected_actions=("read", "settle", "correct")),
    "location_count": EntitlementDefinitionSpec("location_count", "Locations",
        EntitlementValueType.ALLOWANCE, "location", "gauge"),
    "contracted_seats": EntitlementDefinitionSpec("contracted_seats", "Contracted seats",
        EntitlementValueType.ALLOWANCE, "seat", "gauge"),
    "staff_accounts": EntitlementDefinitionSpec("staff_accounts", "Staff accounts",
        EntitlementValueType.ALLOWANCE, "account", "gauge"),
    "open_manual_leads": EntitlementDefinitionSpec("open_manual_leads", "Open manual leads",
        EntitlementValueType.ALLOWANCE, "lead", "gauge"),
    "document_storage_bytes": EntitlementDefinitionSpec("document_storage_bytes", "Document storage",
        EntitlementValueType.ALLOWANCE, "byte", "gauge"),
    "active_vo_clients": EntitlementDefinitionSpec("active_vo_clients", "Active Virtual Office clients",
        EntitlementValueType.ALLOWANCE, "client", "gauge", built=False),
})

# Seeded as drafts with no price: Platform admin sets prices and publishes them.
DEFAULT_TIERS = [
    dict(key="starter", name="Starter", description="Get running quickly with everything a single space needs.",
         sort_order=10, max_locations=1, max_staff_users=3, max_open_leads=100, storage_mb=500),
    dict(key="growth", name="Growth", description="Multiple locations, attendance, payroll and advanced reporting.",
         sort_order=20, is_highlighted=True, storage_mb=2048),
    dict(key="enterprise", name="Enterprise", description="Large chains and custom contracts.",
         sort_order=30, contact_sales=True, all_features=True),
]


def can_be_available(code: str) -> bool:
    entry = BY_CODE.get(code)
    return entry is None or entry.built


def ensure_entitlement_definitions() -> int:
    """Sync app-owned entitlement types without importing commercial terms."""
    from ..extensions import db
    from ..models import EntitlementDefinition

    existing = {row.key: row for row in EntitlementDefinition.query.all()}
    added = 0
    for spec in ENTITLEMENT_DEFINITIONS.values():
        row = existing.get(spec.key)
        if row is None:
            db.session.add(EntitlementDefinition(
                key=spec.key, name=spec.name, value_type=spec.value_type.value,
                unit=spec.unit or None, measurement=spec.measurement, built=spec.built,
                protected_actions=list(spec.protected_actions)))
            added += 1
        else:
            row.name = spec.name
            row.value_type = spec.value_type.value
            row.unit = spec.unit or None
            row.measurement = spec.measurement
            row.built = spec.built
            row.protected_actions = list(spec.protected_actions)
    if added or existing:
        db.session.flush()
    return added


def ensure_catalog() -> int:
    """Insert catalog rows that are missing (e.g. added in a newer release). Never overwrites admin edits."""
    from ..extensions import db
    from ..models import PlatformModule

    existing = {code for (code,) in db.session.query(PlatformModule.code)}
    added = 0
    for order, entry in enumerate(CATALOG, start=1):
        if entry.code in existing:
            continue
        db.session.add(PlatformModule(
            code=entry.code, name=entry.name, kind=entry.kind, description=entry.description,
            availability=entry.availability, unit_label=entry.unit_label or None,
            sort_order=order * 10, monthly_price=0, is_active=True))
        added += 1
    if added:
        db.session.flush()
    ensure_entitlement_definitions()
    return added
