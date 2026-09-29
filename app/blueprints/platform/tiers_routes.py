"""Platform pricing tiers: Owner-only. "Introducing a new pricing model" and
"Tiers for operators" from the product brief — deliberately not delegable to a
Platform Manager, unlike day-to-day operator billing (/platform/billing)."""
from __future__ import annotations

from flask import render_template, redirect, url_for, flash

from ...extensions import db
from ...models import PricingTier, TierStatus, PlatformModule
from ...services import audit_service
from ...utils.decorators import platform_owner_required
from .forms import PricingTierForm


def register_tiers_routes(bp):

    def configure_module_choices(form):
        modules = PlatformModule.query.filter_by(is_active=True).all()
        form.feature_ids.choices = [(m.id, m.name) for m in modules if m.kind == "feature"]
        form.module_ids.choices = [(m.id, f"{m.name} ({m.monthly_price}/mo)") for m in modules if m.kind == "module"]

    def apply_starter_defaults(tier):
        if tier.key == "starter":
            tier.max_locations = 1
            tier.location_overage_policy = "require_plan_upgrade"
            tier.additional_location_rate = 0
            tier.included_active_contracted_seats = 50
            tier.seat_overage_policy = "allow_and_charge"
            tier.additional_seat_rate = 75
            tier.trial_period_days = 14
            tier.annual_discount = 10

    @bp.route("/tiers")
    @platform_owner_required
    def tiers_list():
        tiers = PricingTier.query.order_by(PricingTier.id).all()
        return render_template("platform/tiers_list.html", tiers=tiers)

    @bp.route("/tiers/new", methods=["GET", "POST"])
    @platform_owner_required
    def tier_new():
        form = PricingTierForm()
        configure_module_choices(form)
        if form.validate_on_submit():
            key = form.key.data.lower().strip()
            if PricingTier.query.filter_by(key=key).first():
                flash("A tier with that key already exists.", "warning")
                return render_template("platform/tier_form.html", form=form, title="New pricing tier")
            tier = PricingTier(key=key)
            form.populate_obj(tier)
            tier.key = key
            apply_starter_defaults(tier)
            tier.annual_price = tier.calculate_annual_price()
            tier.module_catalog = PlatformModule.query.filter(PlatformModule.id.in_(form.feature_ids.data + form.module_ids.data)).all()
            tier.is_active = tier.status == TierStatus.ACTIVE
            db.session.add(tier)
            db.session.commit()
            audit_service.record("pricing_tier.created", "pricing_tier", tier.id, {"key": tier.key})
            flash(f"Tier {tier.name} created.", "success")
            return redirect(url_for("platform.tiers_list"))
        return render_template("platform/tier_form.html", form=form, title="New pricing tier")

    @bp.route("/tiers/<int:tier_id>/edit", methods=["GET", "POST"])
    @platform_owner_required
    def tier_edit(tier_id: int):
        tier = PricingTier.query.get_or_404(tier_id)
        form = PricingTierForm(obj=tier)
        configure_module_choices(form)
        if not form.is_submitted():
            form.feature_ids.data = [m.id for m in tier.module_catalog if m.kind == "feature"]
            form.module_ids.data = [m.id for m in tier.module_catalog if m.kind == "module"]
        if form.validate_on_submit():
            original_key = tier.key
            form.populate_obj(tier)
            apply_starter_defaults(tier)
            tier.pricing_version += 1
            tier.annual_price = tier.calculate_annual_price()
            tier.module_catalog = PlatformModule.query.filter(PlatformModule.id.in_(form.feature_ids.data + form.module_ids.data)).all()
            tier.key = original_key  # key is immutable once operators may reference it
            tier.is_active = tier.status == TierStatus.ACTIVE
            db.session.commit()
            audit_service.record("pricing_tier.updated", "pricing_tier", tier.id, {"key": tier.key})
            flash(f"Tier {tier.name} updated.", "success")
            return redirect(url_for("platform.tiers_list"))
        return render_template("platform/tier_form.html", form=form, title=f"Edit {tier.name}")
