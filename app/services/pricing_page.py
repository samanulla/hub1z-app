"""Plan data for the public pricing page and the Platform landing page, built from the tiers Platform admin configures."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from flask import current_app
from sqlalchemy import or_

from ..models import OveragePolicy, PlatformModule, PlatformProfile, PricingTier, TierStatus
from .catalog import ADDON, ALWAYS, AVAILABLE, BETA, COMING_SOON, FEATURE, USAGE
from .formatting import format_inr


def trial_days() -> int:
    profile = PlatformProfile.peek()
    if profile is not None and profile.trial_days:
        return profile.trial_days
    return current_app.config.get("OPERATOR_TRIAL_DAYS", 14)


def pricing_is_public() -> bool:
    profile = PlatformProfile.peek()
    return bool(profile is not None and profile.pricing_page_public)


def format_storage(mb: int) -> str:
    return f"{mb / 1024:g} GB" if mb >= 1024 else f"{mb} MB"


def _count(n: int, singular: str, plural: str | None = None) -> str:
    return f"{n} {singular if n == 1 else (plural or singular + 's')}"


def tier_limit_lines(tier: PricingTier) -> list[str]:
    if tier.all_features and tier.contact_sales:
        return ["Locations, seats and users to suit you", "Custom limits and contract terms"]
    lines = []
    if tier.max_locations is not None:
        lines.append("1 location" if tier.max_locations == 1 else f"Up to {tier.max_locations} locations")
        if (tier.location_overage_policy == OveragePolicy.ALLOW_AND_CHARGE
                and Decimal(tier.additional_location_rate or 0) > 0):
            lines.append(f"Extra locations {format_inr(tier.additional_location_rate)}/month each")
    else:
        lines.append("Unlimited locations")
    if tier.included_active_contracted_seats is not None:
        seats = f"{_count(tier.included_active_contracted_seats, 'active seat')} included"
        if (tier.seat_overage_policy == OveragePolicy.ALLOW_AND_CHARGE
                and Decimal(tier.additional_seat_rate or 0) > 0):
            seats += f", then {format_inr(tier.additional_seat_rate)}/month per seat"
        lines.append(seats)
    lines.append("Unlimited staff logins" if tier.max_staff_users is None
                 else _count(tier.max_staff_users, "staff login"))
    lines.append("Unlimited leads" if tier.max_open_leads is None
                 else f"Up to {tier.max_open_leads} open leads")
    lines.append("Unlimited document storage" if tier.storage_mb is None
                 else f"{format_storage(tier.storage_mb)} document storage")
    return lines


def tier_feature_names(tier: PricingTier) -> list[str]:
    """Lockable features this tier includes, in catalog order."""
    if tier.all_features:
        query = PlatformModule.query.filter_by(kind=FEATURE, is_active=True, availability=AVAILABLE)
        return [m.name for m in query.order_by(PlatformModule.sort_order, PlatformModule.id)]
    modules = [m for m in tier.module_catalog
               if m.kind == FEATURE and m.is_active and m.availability == AVAILABLE]
    return [m.name for m in sorted(modules, key=lambda m: (m.sort_order, m.id))]


def public_tiers() -> list[PricingTier]:
    if not pricing_is_public():
        return []
    today = date.today()
    return (PricingTier.query.filter_by(status=TierStatus.ACTIVE, is_active=True, is_public=True)
            .filter(PricingTier.key != "scale",
                    or_(PricingTier.effective_from.is_(None), PricingTier.effective_from <= today),
                    or_(PricingTier.effective_to.is_(None), PricingTier.effective_to >= today))
            .order_by(PricingTier.sort_order, PricingTier.id).all())


def public_plans(billing: str = "monthly") -> list[dict]:
    plans = []
    for tier in public_tiers():
        monthly = tier.monthly_price
        annual = tier.calculate_annual_price()
        custom = tier.contact_sales or monthly is None
        shown = None
        if not custom:
            shown = annual / 12 if billing == "annual" and annual is not None else monthly
        plans.append({
            "tier": tier,
            "description": tier.description,
            "custom": custom,
            "price": shown,
            "annual": None if custom else annual,
            "discount": tier.annual_discount if Decimal(tier.annual_discount or 0) > 0 else None,
            "popular": tier.is_highlighted,
            "limits": tier_limit_lines(tier),
            "features": tier_feature_names(tier),
            "all_features": tier.all_features,
        })
    return plans


def addon_price_text(module: PlatformModule) -> str:
    if module.availability == BETA:
        return "Beta"
    if module.availability != AVAILABLE:
        return "Coming soon"
    if module.kind == USAGE:
        return (f"{format_inr(module.unit_price)} {module.unit_label or 'per use'}"
                if module.unit_price else "Pay per use")
    if Decimal(module.monthly_price or 0) > 0:
        return f"{format_inr(module.monthly_price)}/month" + (f" {module.unit_label}" if module.unit_label else "")
    return "Contact us"


def public_catalog() -> dict | None:
    """What every plan includes, plus the add-ons and pay-per-use items worth listing."""
    if not pricing_is_public():
        return None
    modules = (PlatformModule.query.filter(PlatformModule.is_active.is_(True),
                                           PlatformModule.availability != "hidden")
               .order_by(PlatformModule.sort_order, PlatformModule.id).all())
    return {
        "always": [m.name for m in modules if m.kind == ALWAYS],
        "beta_features": [m.name for m in modules if m.kind == FEATURE and m.availability == BETA],
        "upcoming_features": [m.name for m in modules if m.kind == FEATURE and m.availability == COMING_SOON],
        "addons": [{"name": m.name, "description": m.description, "price": addon_price_text(m),
                    "soon": m.availability == COMING_SOON} for m in modules if m.kind == ADDON],
        "usage": [{"name": m.name, "description": m.description, "price": addon_price_text(m),
                   "soon": m.availability == COMING_SOON} for m in modules if m.kind == USAGE],
    }
