"""Platform billing: each operator's commercial plan tier and custom-domain
access. Gated by the 'billing' feature — day-to-day, delegable to a Platform
Manager. Defining/editing the tiers themselves is Owner-only (/platform/tiers).

This is the platform's OWN commercial relationship with its operators (what a
operator pays hub1z.com), separate from an operator's own /admin/billing
(what that operator charges its member companies).
"""
from __future__ import annotations

import json

from flask import render_template, redirect, url_for, flash, request

from ...extensions import db
from ...models import Operator, PricingTier, OperatorSubscription, TierStatus
from ...services import audit_service
from ...services.platform_pricing import subscription_pricing
from ...utils.decorators import platform_permission_required
from .forms import OperatorSubscriptionForm


def register_billing_routes(bp):

    @bp.route("/billing")
    @platform_permission_required("billing")
    def billing():
        operators = (Operator.query.execution_options(skip_operator_filter=True)
                   .order_by(Operator.name).all())
        tiers_by_key = {t.key: t for t in PricingTier.query.all()}
        active_tiers = [t for t in tiers_by_key.values() if t.status == TierStatus.ACTIVE]
        growth = tiers_by_key.get("growth")
        for t in operators:
            t._tier = tiers_by_key.get(t.plan_tier)
            t._subscription = OperatorSubscription.query.filter_by(operator_id=t.id).first()
            t._pricing = (subscription_pricing(t, t._tier, t._subscription)
                          if t._tier else None)
            t._upgrade_recommendation = (
                growth if t._tier and t._tier.key == "starter" and growth and
                growth.monthly_price is not None and t._pricing and
                t._pricing["total"] >= growth.monthly_price else None
            )
            db.session.commit()
        return render_template("platform/billing.html", operators=operators, tiers=active_tiers)

    @bp.route("/billing/<int:operator_id>/plan", methods=["POST"])
    @platform_permission_required("billing")
    def billing_set_plan(operator_id: int):
        t = (Operator.query.execution_options(skip_operator_filter=True)
             .filter_by(id=operator_id).first_or_404())
        tier_key = request.form.get("plan_tier")
        if not PricingTier.query.filter_by(key=tier_key, status=TierStatus.ACTIVE).first():
            flash("Unknown or retired plan tier.", "warning")
            return redirect(url_for("platform.billing"))
        t.plan_tier = tier_key
        db.session.commit()
        audit_service.record("operator.plan_tier_changed", "operator", t.id,
                             {"slug": t.slug, "plan_tier": tier_key})
        flash(f"{t.name} moved to the {tier_key} plan.", "success")
        return redirect(url_for("platform.billing"))

    @bp.route("/billing/<int:operator_id>/subscription", methods=["GET", "POST"])
    @platform_permission_required("billing")
    def billing_subscription_edit(operator_id: int):
        operator = (Operator.query.execution_options(skip_operator_filter=True)
                  .filter_by(id=operator_id).first_or_404())
        subscription = OperatorSubscription.query.filter_by(operator_id=operator.id).first()
        if subscription is None:
            subscription = OperatorSubscription(operator_id=operator.id)
        form = OperatorSubscriptionForm(obj=subscription)
        tiers = PricingTier.query.order_by(PricingTier.id).all()
        form.tier_id.choices = [(0, "— use operator's current tier —")] + [
            (tier.id, tier.name) for tier in tiers
        ]
        if not form.is_submitted() and subscription.tier_id is None:
            current = PricingTier.query.filter_by(key=operator.plan_tier).first()
            form.tier_id.data = current.id if current else 0
        if form.validate_on_submit():
            form.populate_obj(subscription)
            subscription.tier_id = form.tier_id.data or None
            selected_tier = PricingTier.query.get(subscription.tier_id) if subscription.tier_id else None
            if selected_tier:
                operator.plan_tier = selected_tier.key
            if subscription.id is None:
                db.session.add(subscription)
            tier = selected_tier or PricingTier.query.filter_by(key=operator.plan_tier).first()
            if tier:
                subscription.pricing_snapshot = json.dumps({
                    "tier_key": tier.key,
                    "monthly_price": str(tier.monthly_price) if tier.monthly_price is not None else None,
                    "annual_price": str(tier.annual_price) if tier.annual_price is not None else None,
                    "annual_discount": str(tier.annual_discount),
                    "pricing_version": tier.pricing_version,
                    "included_locations": tier.max_locations,
                    "included_active_contracted_seats": tier.included_active_contracted_seats,
                    "additional_seat_rate": str(tier.additional_seat_rate),
                    "additional_location_rate": str(tier.additional_location_rate),
                    "seat_overage_policy": tier.seat_overage_policy.value,
                    "location_overage_policy": tier.location_overage_policy.value,
                    "seat_usage_method": tier.seat_usage_method.value,
                    "effective_from": tier.effective_from.isoformat() if tier.effective_from else None,
                    "effective_to": tier.effective_to.isoformat() if tier.effective_to else None,
                    "features": [module.code for module in tier.module_catalog if module.kind == "feature"],
                    "modules": [module.code for module in tier.module_catalog if module.kind == "module"],
                })
            db.session.commit()
            audit_service.record("operator_subscription.updated", "operator_subscription", subscription.id,
                                 {"operator_id": operator.id, "tier": operator.plan_tier})
            flash("Operator subscription and negotiated terms saved.", "success")
            return redirect(url_for("platform.billing"))
        return render_template("platform/operator_subscription_form.html", form=form,
                               operator=operator, subscription=subscription)
