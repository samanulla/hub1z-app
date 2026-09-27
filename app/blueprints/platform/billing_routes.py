"""Platform billing: each tenant's commercial plan tier and custom-domain
access. Gated by the 'billing' feature — day-to-day, delegable to a Platform
Manager. Defining/editing the tiers themselves is Owner-only (/platform/tiers).

This is the platform's OWN commercial relationship with its tenants (what a
tenant pays hub1z.com), separate from a tenant's own /admin/billing
(what that tenant charges its member companies).
"""
from __future__ import annotations

from flask import render_template, redirect, url_for, flash, request

from ...extensions import db
from ...models import Tenant, PricingTier, OperatorSubscription, TierStatus
from ...services import audit_service
from ...services.platform_pricing import subscription_pricing
from ...utils.decorators import platform_permission_required
from .forms import OperatorSubscriptionForm


def register_billing_routes(bp):

    @bp.route("/billing")
    @platform_permission_required("billing")
    def billing():
        tenants = (Tenant.query.execution_options(skip_tenant_filter=True)
                   .order_by(Tenant.name).all())
        tiers_by_key = {t.key: t for t in PricingTier.query.all()}
        active_tiers = [t for t in tiers_by_key.values() if t.status == TierStatus.ACTIVE]
        growth = tiers_by_key.get("growth")
        for t in tenants:
            t._tier = tiers_by_key.get(t.plan_tier)
            t._subscription = OperatorSubscription.query.filter_by(tenant_id=t.id).first()
            t._pricing = (subscription_pricing(t, t._tier, t._subscription)
                          if t._tier else None)
            t._upgrade_recommendation = (
                growth if t._tier and t._tier.key == "starter" and growth and
                growth.monthly_price is not None and t._pricing and
                t._pricing["total"] >= growth.monthly_price else None
            )
        return render_template("platform/billing.html", tenants=tenants, tiers=active_tiers)

    @bp.route("/billing/<int:tenant_id>/plan", methods=["POST"])
    @platform_permission_required("billing")
    def billing_set_plan(tenant_id: int):
        t = (Tenant.query.execution_options(skip_tenant_filter=True)
             .filter_by(id=tenant_id).first_or_404())
        tier_key = request.form.get("plan_tier")
        if not PricingTier.query.filter_by(key=tier_key, status=TierStatus.ACTIVE).first():
            flash("Unknown or retired plan tier.", "warning")
            return redirect(url_for("platform.billing"))
        t.plan_tier = tier_key
        db.session.commit()
        audit_service.record("tenant.plan_tier_changed", "tenant", t.id,
                             {"slug": t.slug, "plan_tier": tier_key})
        flash(f"{t.name} moved to the {tier_key} plan.", "success")
        return redirect(url_for("platform.billing"))

    @bp.route("/billing/<int:tenant_id>/subscription", methods=["GET", "POST"])
    @platform_permission_required("billing")
    def billing_subscription_edit(tenant_id: int):
        tenant = (Tenant.query.execution_options(skip_tenant_filter=True)
                  .filter_by(id=tenant_id).first_or_404())
        subscription = OperatorSubscription.query.filter_by(tenant_id=tenant.id).first()
        if subscription is None:
            subscription = OperatorSubscription(tenant_id=tenant.id)
        form = OperatorSubscriptionForm(obj=subscription)
        tiers = PricingTier.query.order_by(PricingTier.id).all()
        form.tier_id.choices = [(0, "— use operator's current tier —")] + [
            (tier.id, tier.name) for tier in tiers
        ]
        if not form.is_submitted() and subscription.tier_id is None:
            current = PricingTier.query.filter_by(key=tenant.plan_tier).first()
            form.tier_id.data = current.id if current else 0
        if form.validate_on_submit():
            form.populate_obj(subscription)
            subscription.tier_id = form.tier_id.data or None
            selected_tier = PricingTier.query.get(subscription.tier_id) if subscription.tier_id else None
            if selected_tier:
                tenant.plan_tier = selected_tier.key
            if subscription.id is None:
                db.session.add(subscription)
            db.session.commit()
            audit_service.record("operator_subscription.updated", "operator_subscription", subscription.id,
                                 {"tenant_id": tenant.id, "tier": tenant.plan_tier})
            flash("Operator subscription and negotiated terms saved.", "success")
            return redirect(url_for("platform.billing"))
        return render_template("platform/operator_subscription_form.html", form=form,
                               tenant=tenant, subscription=subscription)
