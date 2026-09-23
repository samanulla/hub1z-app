"""Platform pricing tiers: Owner-only. "Introducing a new pricing model" and
"Tiers for tenants" from the product brief — deliberately not delegable to a
Platform Manager, unlike day-to-day tenant billing (/platform/billing)."""
from __future__ import annotations

from flask import render_template, redirect, url_for, flash

from ...extensions import db
from ...models import PricingTier
from ...services import audit_service
from ...utils.decorators import platform_owner_required
from .forms import PricingTierForm


def register_tiers_routes(bp):

    @bp.route("/tiers")
    @platform_owner_required
    def tiers_list():
        tiers = PricingTier.query.order_by(PricingTier.id).all()
        return render_template("platform/tiers_list.html", tiers=tiers)

    @bp.route("/tiers/new", methods=["GET", "POST"])
    @platform_owner_required
    def tier_new():
        form = PricingTierForm()
        if form.validate_on_submit():
            key = form.key.data.lower().strip()
            if PricingTier.query.filter_by(key=key).first():
                flash("A tier with that key already exists.", "warning")
                return render_template("platform/tier_form.html", form=form, title="New pricing tier")
            tier = PricingTier(key=key)
            form.populate_obj(tier)
            tier.key = key
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
        if form.validate_on_submit():
            original_key = tier.key
            form.populate_obj(tier)
            tier.key = original_key  # key is immutable once tenants may reference it
            db.session.commit()
            audit_service.record("pricing_tier.updated", "pricing_tier", tier.id, {"key": tier.key})
            flash(f"Tier {tier.name} updated.", "success")
            return redirect(url_for("platform.tiers_list"))
        return render_template("platform/tier_form.html", form=form, title=f"Edit {tier.name}")
