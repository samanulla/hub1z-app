"""Tenant admin/manager sets up a company's subscription — moved here from a
former company self-checkout (/company/plans used to let a Company Admin
subscribe to any plan/quantity instantly, disconnected from actual seat
inventory). Subscribing is now tenant-controlled, same as seat allocations.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from flask import render_template, redirect, url_for, flash

from ...extensions import db
from ...models import Company, PricingPlan, Subscription, SubscriptionStatus
from ...utils.decorators import manager_or_super_required
from ...services import audit_service
from .forms import AdminSubscribeForm


def register_subscription_routes(bp):

    @bp.route("/companies/<int:company_id>/subscriptions/new", methods=["GET", "POST"])
    @manager_or_super_required
    def company_subscription_new(company_id: int):
        company = Company.query.get_or_404(company_id)
        form = AdminSubscribeForm()
        form.plan_id.choices = [
            (p.id, f"{p.name} — {p.base_price}/{p.billing_cycle.value}")
            for p in PricingPlan.query.filter_by(is_active=True).order_by(PricingPlan.base_price).all()
        ]
        if form.validate_on_submit():
            plan = PricingPlan.query.get_or_404(form.plan_id.data)
            sub = Subscription(
                plan_id=plan.id,
                company_id=company.id,
                quantity=form.quantity.data,
                unit_price=Decimal(plan.base_price),
                start_date=form.start_date.data,
                status=SubscriptionStatus.ACTIVE,
                meeting_credits_balance=(plan.included_meeting_credits or 0) * form.quantity.data,
            )
            db.session.add(sub)
            db.session.commit()
            audit_service.record("subscription.created", "subscription", sub.id,
                                 {"company": company.name, "plan": plan.name, "quantity": sub.quantity})
            flash(f"{company.name} subscribed to {plan.name}.", "success")
            return redirect(url_for("admin.company_detail", company_id=company.id))
        if not form.is_submitted():
            form.start_date.data = date.today()
        return render_template("admin/companies/subscription_form.html", form=form, company=company)

    @bp.route("/companies/<int:company_id>/subscriptions/<int:sub_id>/cancel", methods=["POST"])
    @manager_or_super_required
    def company_subscription_cancel(company_id: int, sub_id: int):
        sub = Subscription.query.filter_by(id=sub_id, company_id=company_id).first_or_404()
        sub.status = SubscriptionStatus.CANCELLED
        sub.end_date = date.today()
        db.session.commit()
        audit_service.record("subscription.cancelled", "subscription", sub.id, {"company_id": company_id})
        flash("Subscription cancelled.", "info")
        return redirect(url_for("admin.company_detail", company_id=company_id))
