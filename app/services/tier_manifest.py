"""Create the pricing manifest's tiers as unpublished drafts that admins edit like any other tier."""
from decimal import Decimal

from ..extensions import db
from ..models import OveragePolicy, PlatformModule, PricingTier, TierStatus
from .catalog import ensure_catalog

GROWTH_FEATURES = (
    "payment_reminders", "payroll", "expenses", "attendance_reports", "attendance_export",
    "rotating_qr_screen", "advanced_reports", "alert_digests", "lead_export", "audit_export",
)
# Annual = 10 x monthly; two decimals is the closest the discount field can store.
ANNUAL_DISCOUNT = Decimal("16.67")

MANIFEST_TIERS = [
    dict(key="starter_v2", name="Starter", sort_order=110, monthly_price=2999,
         description="One location with everything a single space needs.",
         max_locations=1, included_active_contracted_seats=50, max_staff_users=3, max_open_leads=250,
         storage_mb=5 * 1024, additional_seat_rate=55, additional_location_rate=0,
         location_overage_policy=OveragePolicy.REQUIRE_PLAN_UPGRADE, features=("payment_reminders",)),
    dict(key="growth_v2", name="Growth", sort_order=120, monthly_price=7999,
         description="Multi-location operations with payroll, expenses and advanced reports.",
         max_locations=3, included_active_contracted_seats=150, storage_mb=25 * 1024,
         additional_seat_rate=49, additional_location_rate=1999,
         location_overage_policy=OveragePolicy.ALLOW_AND_CHARGE, features=GROWTH_FEATURES),
    dict(key="scale_v1", name="Scale", sort_order=130, monthly_price=19999,
         description="Early access: larger networks with a white-label web portal / PWA.",
         max_locations=8, included_active_contracted_seats=400, storage_mb=100 * 1024,
         additional_seat_rate=45, additional_location_rate=1499,
         location_overage_policy=OveragePolicy.ALLOW_AND_CHARGE, features=GROWTH_FEATURES + ("white_label",)),
    dict(key="enterprise_v1", name="Enterprise", sort_order=140, monthly_price=44999, contact_sales=True,
         description="Custom contracts for large networks.",
         max_locations=15, included_active_contracted_seats=1000,
         additional_seat_rate=35, additional_location_rate=999,
         location_overage_policy=OveragePolicy.ALLOW_AND_CHARGE, features=GROWTH_FEATURES + ("white_label",)),
]


def ensure_manifest_tiers() -> list[str]:
    """Add any missing manifest tier as a hidden draft. Existing tiers are never changed."""
    ensure_catalog()
    modules = {m.code: m for m in PlatformModule.query.all()}
    created = []
    for spec in MANIFEST_TIERS:
        values = dict(spec)
        codes = values.pop("features")
        if PricingTier.query.filter_by(key=values["key"]).first():
            continue
        tier = PricingTier(status=TierStatus.DRAFT, is_public=False, is_active=False,
                           annual_discount=ANNUAL_DISCOUNT, seat_overage_policy=OveragePolicy.ALLOW_AND_CHARGE,
                           **values)
        tier.annual_price = tier.calculate_annual_price()
        tier.module_catalog = [modules[code] for code in codes]
        db.session.add(tier)
        created.append(tier.key)
    db.session.flush()
    return created
