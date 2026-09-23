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
from ...models import Tenant, PricingTier, Location, Seat, SeatType, ConferenceRoom
from ...services import audit_service
from ...utils.decorators import platform_permission_required


def _usage(tenant_id: int) -> dict:
    return {
        "locations": Location.query.filter_by(tenant_id=tenant_id).count(),
        "seats": (Seat.query.join(Location).filter(
            Location.tenant_id == tenant_id,
            Seat.seat_type.in_([SeatType.HOT_DESK, SeatType.DEDICATED_DESK])).count()),
        "private_offices": (Seat.query.join(Location).filter(
            Location.tenant_id == tenant_id, Seat.seat_type == SeatType.PRIVATE_OFFICE).count()),
        "rooms": ConferenceRoom.query.join(Location).filter(Location.tenant_id == tenant_id).count(),
    }


def register_billing_routes(bp):

    @bp.route("/billing")
    @platform_permission_required("billing")
    def billing():
        tenants = (Tenant.query.execution_options(skip_tenant_filter=True)
                   .order_by(Tenant.name).all())
        tiers_by_key = {t.key: t for t in PricingTier.query.all()}
        active_tiers = [t for t in tiers_by_key.values() if t.is_active]
        for t in tenants:
            t._tier = tiers_by_key.get(t.plan_tier)
            t._usage = _usage(t.id)
        return render_template("platform/billing.html", tenants=tenants, tiers=active_tiers)

    @bp.route("/billing/<int:tenant_id>/plan", methods=["POST"])
    @platform_permission_required("billing")
    def billing_set_plan(tenant_id: int):
        t = (Tenant.query.execution_options(skip_tenant_filter=True)
             .filter_by(id=tenant_id).first_or_404())
        tier_key = request.form.get("plan_tier")
        if not PricingTier.query.filter_by(key=tier_key, is_active=True).first():
            flash("Unknown or retired plan tier.", "warning")
            return redirect(url_for("platform.billing"))
        t.plan_tier = tier_key
        db.session.commit()
        audit_service.record("tenant.plan_tier_changed", "tenant", t.id,
                             {"slug": t.slug, "plan_tier": tier_key})
        flash(f"{t.name} moved to the {tier_key} plan.", "success")
        return redirect(url_for("platform.billing"))
