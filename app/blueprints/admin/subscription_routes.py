"""Operator admin/manager sets up a company's subscription — moved here from a
former company self-checkout (/company/plans used to let a Company Admin
subscribe to any plan/quantity instantly, disconnected from actual seat
inventory). Subscribing is now operator-controlled, same as seat allocations.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
import json

from flask import render_template, redirect, url_for, flash, request, g
from flask_login import current_user

from ...extensions import db
from ...models import (
    Company, PricingPlan, Subscription, SubscriptionStatus, User, UserRole,
    SubscriptionChangeRequest, SubscriptionRequestStatus,
)
from ...utils.decorators import admin_required, manager_or_super_required
from ...services import audit_service, credit_service, billing_service
from ...services.gst import money
from ...models import BillingSettings
from .forms import AdminSubscribeForm

_TERM_FIELDS = (
    "term_months", "lock_in_months", "notice_months", "due_day", "deposit_refund_days", "escalation_percent",
    "escalation_after_months", "late_fee_mode", "late_fee_value", "late_fee_grace_days", "early_exit_rule",
)


def register_subscription_routes(bp):

    def _subscribe(company=None, user=None):
        subject_name = company.name if company else user.full_name
        back_url = (url_for("admin.company_detail", company_id=company.id) if company
                    else url_for("admin.individuals_list"))
        form = AdminSubscribeForm()
        form.plan_id.choices = [
            (p.id, f"{p.name} — {p.base_price}/{p.billing_cycle.value}")
            for p in PricingPlan.query.filter_by(is_active=True).order_by(PricingPlan.base_price).all()
        ]
        if form.validate_on_submit():
            plan = PricingPlan.query.get_or_404(form.plan_id.data)
            sub = Subscription(
                plan_id=plan.id,
                company_id=company.id if company else None,
                user_id=user.id if user else None,
                quantity=form.quantity.data,
                unit_price=Decimal(plan.base_price),
                start_date=form.start_date.data,
                status=SubscriptionStatus.ACTIVE,
                price_includes_tax=bool(form.price_includes_tax.data),
                pricing_snapshot=json.dumps({
                    "plan_id": plan.id, "plan_version": plan.version, "base_price": str(plan.base_price),
                    "billing_unit": plan.billing_unit.value, "billing_cycle": plan.billing_cycle.value,
                    "included_seat_quantity": plan.included_seat_quantity,
                    "additional_seat_rate": str(plan.additional_seat_rate),
                    "effective_from": plan.effective_from.isoformat() if plan.effective_from else None,
                    "effective_until": plan.effective_until.isoformat() if plan.effective_until else None,
                }),
            )
            db.session.add(sub)
            defaults = BillingSettings.for_operator(g.operator_id)
            for name in _TERM_FIELDS:
                value = getattr(form, name).data if name in request.form else None
                setattr(sub, name, getattr(defaults, name) if value is None else value)
            if form.deposit_amount.data is not None:
                sub.deposit_amount = money(form.deposit_amount.data)
            else:
                months = form.deposit_months.data if form.deposit_months.data is not None else defaults.deposit_months
                sub.deposit_amount = money(Decimal(sub.unit_price) * sub.quantity * months)
            db.session.flush()
            billing_service.create_deposit_invoice(sub)
            credits = credit_service.auto_allocate_for_subscription(sub, actor=current_user)
            db.session.commit()
            audit_service.record("subscription.created", "subscription", sub.id,
                                 {"subject": subject_name, "plan": plan.name, "quantity": sub.quantity})
            flash(f"{subject_name} subscribed to {plan.name}.", "success")
            if credits:
                flash(f"Monthly credits suggested from the seat bands: {credits['credits']}. "
                      "Adjust them on the Credits page.", "info")
                if credits["warning"]:
                    flash(credits["warning"], "warning")
            return redirect(back_url)
        if not form.is_submitted():
            form.start_date.data = date.today()
            defaults = BillingSettings.for_operator(g.operator_id)
            for name in _TERM_FIELDS:
                getattr(form, name).data = getattr(defaults, name)
            form.deposit_months.data = defaults.deposit_months
        return render_template("admin/companies/subscription_form.html", form=form, subject_name=subject_name,
                               back_url=back_url)

    @bp.route("/companies/<int:company_id>/subscriptions/new", methods=["GET", "POST"])
    @manager_or_super_required
    def company_subscription_new(company_id: int):
        return _subscribe(company=Company.query.get_or_404(company_id))

    @bp.route("/individuals")
    @admin_required
    def individuals_list():
        people = (User.query.filter_by(role=UserRole.INDIVIDUAL).order_by(User.full_name).all())
        subs = Subscription.query.filter(Subscription.user_id.in_([p.id for p in people] or [0])).all()
        by_user: dict[int, list] = {}
        for s in subs:
            by_user.setdefault(s.user_id, []).append(s)
        return render_template("admin/individuals.html", people=people, subs=by_user)

    @bp.route("/individuals/<int:user_id>/subscriptions/new", methods=["GET", "POST"])
    @manager_or_super_required
    def individual_subscription_new(user_id: int):
        user = User.query.filter_by(id=user_id, role=UserRole.INDIVIDUAL, is_active=True).first_or_404()
        return _subscribe(user=user)

    @bp.route("/individuals/<int:user_id>/subscriptions/<int:sub_id>/cancel", methods=["POST"])
    @manager_or_super_required
    def individual_subscription_cancel(user_id: int, sub_id: int):
        sub = Subscription.query.filter_by(id=sub_id, user_id=user_id).first_or_404()
        sub.status = SubscriptionStatus.CANCELLED
        sub.end_date = date.today()
        db.session.commit()
        audit_service.record("subscription.cancelled", "subscription", sub.id, {"user_id": user_id})
        flash("Subscription cancelled.", "info")
        return redirect(url_for("admin.individuals_list"))

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
                billing_service.apply_default_terms(subscription)
                billing_service.create_deposit_invoice(subscription)
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
