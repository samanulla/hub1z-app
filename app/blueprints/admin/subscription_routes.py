"""Operator admin/manager sets up a company's subscription — moved here from a
former company self-checkout (/company/plans used to let a Company Admin
subscribe to any plan/quantity instantly, disconnected from actual seat
inventory). Subscribing is now operator-controlled, same as seat allocations.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
import json

from flask import render_template, redirect, url_for, flash, request
from flask_login import current_user

from ...extensions import db
from ...models import (
    Company, PricingPlan, Subscription, SubscriptionStatus,
    SubscriptionChangeRequest, SubscriptionRequestStatus,
)
from ...utils.decorators import manager_or_super_required
from ...services import audit_service, credit_service
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
                pricing_snapshot=json.dumps({
                    "plan_id": plan.id, "plan_version": plan.version, "base_price": str(plan.base_price),
                    "billing_unit": plan.billing_unit.value, "billing_cycle": plan.billing_cycle.value,
                    "included_seat_quantity": plan.included_seat_quantity,
                    "meeting_room_credits": plan.included_meeting_credits,
                    "additional_seat_rate": str(plan.additional_seat_rate),
                    "effective_from": plan.effective_from.isoformat() if plan.effective_from else None,
                    "effective_until": plan.effective_until.isoformat() if plan.effective_until else None,
                }),
            )
            db.session.add(sub)
            db.session.flush()
            credits = credit_service.auto_allocate_for_subscription(sub, actor=current_user)
            db.session.commit()
            audit_service.record("subscription.created", "subscription", sub.id,
                                 {"company": company.name, "plan": plan.name, "quantity": sub.quantity})
            flash(f"{company.name} subscribed to {plan.name}.", "success")
            if credits:
                flash(f"Monthly credits suggested from the seat bands: {credits['credits']}. "
                      "Adjust them on the Credits page.", "info")
                if credits["warning"]:
                    flash(credits["warning"], "warning")
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

    @bp.route("/companies/<int:company_id>/subscription-requests/<int:request_id>/<decision>", methods=["POST"])
    @manager_or_super_required
    def company_subscription_request_review(company_id: int, request_id: int, decision: str):
        change = SubscriptionChangeRequest.query.filter_by(
            id=request_id, company_id=company_id,
            status=SubscriptionRequestStatus.PENDING,
        ).first_or_404()
        operator_message = (request.form.get("operator_message") or "").strip() or None
        if decision == "approve":
            plan = change.requested_plan
            subscription = change.subscription
            if subscription is None:
                subscription = Subscription(
                    operator_id=change.operator_id,
                    company_id=change.company_id,
                    plan_id=plan.id,
                    quantity=change.requested_quantity,
                    unit_price=Decimal(plan.base_price),
                    start_date=date.today(),
                    status=SubscriptionStatus.ACTIVE,
                )
                db.session.add(subscription)
                db.session.flush()
                change.subscription_id = subscription.id
                credit_service.auto_allocate_for_subscription(subscription, actor=current_user)
            else:
                subscription.plan_id = plan.id
                subscription.quantity = change.requested_quantity
                subscription.unit_price = Decimal(plan.base_price)
                subscription.status = SubscriptionStatus.ACTIVE
            change.status = SubscriptionRequestStatus.APPROVED
            action = "approved"
        elif decision == "deny":
            if not operator_message:
                flash("Add a message explaining why the request cannot be approved.", "warning")
                return redirect(url_for("admin.company_detail", company_id=company_id))
            change.status = SubscriptionRequestStatus.DENIED
            action = "denied"
        else:
            flash("Invalid subscription request decision.", "warning")
            return redirect(url_for("admin.company_detail", company_id=company_id))

        change.operator_message = operator_message
        change.reviewed_by_id = current_user.id
        change.reviewed_at = datetime.utcnow()
        db.session.commit()
        audit_service.record(f"subscription_request.{action}", "subscription_change_request", change.id,
                             {"company_id": company_id, "plan_id": change.requested_plan_id,
                              "quantity": change.requested_quantity})
        flash(f"Subscription request {action}.", "success" if decision == "approve" else "info")
        return redirect(url_for("admin.company_detail", company_id=company_id))
