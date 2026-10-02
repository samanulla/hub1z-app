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

AVAILABLE, COMING_SOON, HIDDEN = "available", "coming_soon", "hidden"
AVAILABILITY_CHOICES = [(AVAILABLE, "Available"), (COMING_SOON, "Coming soon"), (HIDDEN, "Hidden")]

ALWAYS, FEATURE, ADDON, USAGE = "always", "feature", "addon", "usage"
KIND_LABELS = {ALWAYS: "Included in every plan", FEATURE: "Plan features", ADDON: "Paid add-ons",
               USAGE: "Pay-per-use"}
KIND_ORDER = [ALWAYS, FEATURE, ADDON, USAGE]


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


_ALWAYS = [
    ("bookings", "Bookings"), ("calendar", "Calendar"), ("meeting_credits", "Meeting room credits"),
    ("gst_invoices", "GST invoices"), ("pdf_documents", "PDF documents"),
    ("upi_payments", "UPI QR payments with manual confirmation"),
    ("location_qr_checkin", "Location QR check-in"), ("member_app", "Member mobile app"),
    ("parcels", "Parcels"), ("inapp_alerts", "In-app alerts"), ("leads", "Leads"),
    ("lead_email_alerts", "Email lead notifications"), ("basic_reports", "Basic reports"),
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
    CatalogEntry("white_label", "White Label", ADDON,
                 "Your own domain and no Hub1z branding on your portal."),
    CatalogEntry("extra_storage", "Extra Storage", ADDON,
                 "More document storage on top of the plan allowance.", unit_label="per 5 GB"),
    CatalogEntry("accounting_sync", "Accounting Sync", ADDON,
                 "Sync invoices and payments to your accounting software.", COMING_SOON, built=False),
    CatalogEntry("api_webhooks", "API & Webhooks", ADDON,
                 "API keys and webhooks to connect your own tools.", COMING_SOON, built=False),
    CatalogEntry("gst_einvoicing", "GST E-Invoicing", ADDON,
                 "Generate IRN and QR codes through the GST e-invoice portal.", COMING_SOON, built=False),
    CatalogEntry("featured_listing", "Featured Listing", ADDON,
                 "Be featured in the Hub1z space directory.", COMING_SOON, built=False),
    CatalogEntry("online_payments", "Online Payments (Razorpay)", ADDON,
                 "Collect cards, netbanking and UPI with automatic confirmation.", COMING_SOON, built=False),
    CatalogEntry("whatsapp_packs", "WhatsApp Messaging Packs", ADDON,
                 "Send reminders and alerts on WhatsApp.", COMING_SOON, built=False),
]

_USAGE = [
    CatalogEntry("pan_verification", "PAN verification", USAGE,
                 "Live PAN check against government records.", COMING_SOON, built=False, unit_label="per verification"),
    CatalogEntry("gstin_verification", "GSTIN verification", USAGE,
                 "Live GSTIN check against the GST portal.", COMING_SOON, built=False, unit_label="per verification"),
]

CATALOG: list[CatalogEntry] = (
    [CatalogEntry(code, name, ALWAYS) for code, name in _ALWAYS]
    + [CatalogEntry(code, name, FEATURE, desc, default_growth=True) for code, name, desc in _FEATURES]
    + _ADDONS + _USAGE
)

BY_CODE = {e.code: e for e in CATALOG}
LOCKABLE_CODES = [e.code for e in CATALOG if e.kind == FEATURE]

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
    return added
