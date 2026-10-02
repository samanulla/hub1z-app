"""Platform pricing: tiers, the feature catalog and plan settings.

Gated by the 'pricing' permission: the Owner always has it, and can grant it to a
Platform Manager. This defines what Hub1z sells; what an individual operator pays
is handled under /platform/billing.
"""
from __future__ import annotations

from flask import render_template, redirect, url_for, flash

from ...extensions import db
from ...models import PricingTier, TierStatus, PlatformModule, PlatformProfile
from ...services import audit_service
from ...services.catalog import BY_CODE, ensure_catalog, ALWAYS, FEATURE, KIND_LABELS, KIND_ORDER
from ...services.pricing_page import trial_days
from ...utils.decorators import platform_permission_required
from .forms import PricingTierForm, PlanSettingsForm, CatalogEntryForm

requires_pricing = platform_permission_required("pricing")


def _feature_modules():
    ensure_catalog()
    db.session.commit()
    return (PlatformModule.query.filter_by(kind=FEATURE, is_active=True)
            .order_by(PlatformModule.sort_order, PlatformModule.id).all())


def _is_built(code: str) -> bool:
    return BY_CODE[code].built if code in BY_CODE else True


def register_tiers_routes(bp):

    def tier_form(form, features, title):
        always_features = (PlatformModule.query.filter_by(kind=ALWAYS, is_active=True, availability="available")
                           .order_by(PlatformModule.sort_order, PlatformModule.id).all())
        return render_template("platform/tier_form.html", form=form, features=features,
                               always_features=always_features, title=title)

    def configure_feature_choices(form, features):
        form.feature_ids.choices = [(m.id, m.name) for m in features]

    def apply_features(tier, form, features):
        chosen = set(form.feature_ids.data or [])
        editable_ids = {module.id for module in features}
        retained = [module for module in tier.module_catalog if module.id not in editable_ids]
        tier.module_catalog = retained + [module for module in features if module.id in chosen]

    @bp.route("/tiers")
    @requires_pricing
    def tiers_list():
        _feature_modules()
        tiers = PricingTier.query.order_by(PricingTier.sort_order, PricingTier.id).all()
        profile = PlatformProfile.get()
        db.session.commit()
        settings_form = PlanSettingsForm(obj=profile)
        settings_form.trial_tier_key.choices = [(t.key, t.name) for t in tiers]
        settings_form.trial_days.data = trial_days()
        return render_template("platform/tiers_list.html", tiers=tiers, settings_form=settings_form)

    @bp.route("/tiers/settings", methods=["POST"])
    @requires_pricing
    def tier_settings():
        tiers = PricingTier.query.order_by(PricingTier.sort_order, PricingTier.id).all()
        profile = PlatformProfile.get()
        form = PlanSettingsForm()
        form.trial_tier_key.choices = [(t.key, t.name) for t in tiers]
        if form.validate_on_submit():
            profile.trial_days = form.trial_days.data
            profile.trial_tier_key = form.trial_tier_key.data
            profile.renewal_notice_days = form.renewal_notice_days.data
            profile.pricing_page_public = form.pricing_page_public.data
            db.session.commit()
            audit_service.record("plan_settings.updated", "platform_profile", profile.id, {
                "trial_days": profile.trial_days, "trial_tier_key": profile.trial_tier_key,
                "pricing_page_public": profile.pricing_page_public})
            flash("Plan settings saved.", "success")
        else:
            for field_errors in form.errors.values():
                flash(" ".join(field_errors), "warning")
        return redirect(url_for("platform.tiers_list"))

    @bp.route("/tiers/new", methods=["GET", "POST"])
    @requires_pricing
    def tier_new():
        features = _feature_modules()
        form = PricingTierForm()
        configure_feature_choices(form, features)
        if form.validate_on_submit():
            key = form.key.data.lower().strip()
            if PricingTier.query.filter_by(key=key).first():
                flash("A tier with that key already exists.", "warning")
                return tier_form(form, features, "New pricing tier")
            tier = PricingTier(key=key)
            form.populate_obj(tier)
            tier.key = key
            tier.annual_price = tier.calculate_annual_price()
            apply_features(tier, form, features)
            tier.is_active = tier.status == TierStatus.ACTIVE
            db.session.add(tier)
            db.session.commit()
            audit_service.record("pricing_tier.created", "pricing_tier", tier.id, {"key": tier.key})
            flash(f"Tier {tier.name} created.", "success")
            return redirect(url_for("platform.tiers_list"))
        return tier_form(form, features, "New pricing tier")

    @bp.route("/tiers/<int:tier_id>/edit", methods=["GET", "POST"])
    @requires_pricing
    def tier_edit(tier_id: int):
        features = _feature_modules()
        tier = PricingTier.query.get_or_404(tier_id)
        form = PricingTierForm(obj=tier)
        configure_feature_choices(form, features)
        if not form.is_submitted():
            form.feature_ids.data = [m.id for m in tier.module_catalog if m.kind == FEATURE]
        if form.validate_on_submit():
            original_key = tier.key
            form.populate_obj(tier)
            tier.pricing_version += 1
            tier.annual_price = tier.calculate_annual_price()
            apply_features(tier, form, features)
            tier.key = original_key  # key is immutable once operators may reference it
            tier.is_active = tier.status == TierStatus.ACTIVE
            db.session.commit()
            audit_service.record("pricing_tier.updated", "pricing_tier", tier.id, {"key": tier.key})
            flash(f"Tier {tier.name} updated.", "success")
            return redirect(url_for("platform.tiers_list"))
        return tier_form(form, features, f"Edit {tier.name}")

    @bp.route("/catalog")
    @requires_pricing
    def catalog_list():
        ensure_catalog()
        db.session.commit()
        modules = PlatformModule.query.order_by(PlatformModule.sort_order, PlatformModule.id).all()
        groups = [(KIND_LABELS[kind], [m for m in modules if m.kind == kind]) for kind in KIND_ORDER]
        return render_template("platform/catalog_list.html", groups=groups, is_built=_is_built)

    @bp.route("/catalog/<int:module_id>/edit", methods=["GET", "POST"])
    @requires_pricing
    def catalog_edit(module_id: int):
        module = PlatformModule.query.get_or_404(module_id)
        form = CatalogEntryForm(obj=module)
        form.code = module.code
        if form.validate_on_submit():
            form.populate_obj(module)
            module.unit_label = module.unit_label or None
            db.session.commit()
            audit_service.record("catalog_item.updated", "platform_module", module.id,
                                 {"code": module.code, "availability": module.availability})
            flash(f"{module.name} updated.", "success")
            return redirect(url_for("platform.catalog_list"))
        return render_template("platform/catalog_form.html", form=form, module=module,
                               built=_is_built(module.code))
