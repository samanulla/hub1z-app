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
    Company, Location, PricingPlan, Subscription, SubscriptionStatus, User, UserRole,
    SubscriptionChangeRequest, SubscriptionRequestStatus,
)
from ...utils.decorators import admin_required, manager_or_super_required
from ...services import audit_service, credit_service, billing_service, subscription_spaces
from ...services.gst import money
from ...models import BillingSettings
from .forms import AdminSubscribeForm

_TERM_FIELDS = (
    "term_months", "lock_in_months", "notice_months", "due_day", "deposit_refund_days", "escalation_percent",
    "escalation_after_months", "late_fee_mode", "late_fee_value", "late_fee_grace_days", "early_exit_rule",
)


def _read_spaces(form, plan):
    """Validate the extra people and the chosen/new space against the plan.
    Returns (seats, location for a new space, new space code, extra people, error)."""
    extra = form.extra_people.data or 0
    ids = form.space_ids.data or []
    code = (form.new_space_code.data or "").strip()
    if extra and not plan.additional_seats_allowed:
        return [], None, "", 0, "This plan does not allow extra people."
    if extra and plan.maximum_additional_seats and extra > plan.maximum_additional_seats:
        return [], None, "", 0, f"This plan allows at most {plan.maximum_additional_seats} extra people."
    if (ids or code) and not subscription_spaces.seat_types_for(plan):
        return [], None, "", 0, "This plan is not tied to a specific desk or office, so no space can be assigned."
    available = {s.id: s for s in subscription_spaces.free_seats(plan)}
    seats = []
    for seat_id in ids:
        if seat_id not in available:
            return [], None, "", 0, "A chosen space is taken or does not fit this plan."
        seats.append(available[seat_id])
    location = None
    if code:
        location = db.session.get(Location, form.new_space_location_id.data or 0)
        if location is None:
            return [], None, "", 0, "Choose a location for the new space."
    if len(seats) + (1 if code else 0) > (form.quantity.data or 1):
        return [], None, "", 0, "You chose more spaces than the quantity being subscribed."
    return seats, location, code, extra, None


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
        form.space_ids.choices = [
            (s.id, f"{s.code} - {s.location.name} ({s.seat_type.value.replace('_', ' ')})")
            for s in subscription_spaces.free_seats()]
        form.new_space_location_id.choices = [(0, "Choose location")] + [
            (loc.id, loc.name) for loc in Location.query.order_by(Location.name).all()]

        def _page():
            meta = {}
            for p in PricingPlan.query.filter_by(is_active=True).all():
                types = subscription_spaces.seat_types_for(p)
                meta[p.id] = {"seat_type": types[0].value if types else None,
                              "office": p.plan_type in subscription_spaces.OFFICE_TYPES,
                              "people": subscription_spaces.people_per_unit(p),
                              "extras": bool(p.additional_seats_allowed), "max_extra": p.maximum_additional_seats,
                              "rate": str(p.additional_seat_rate or 0), "unit": p.billing_unit.value}
            seat_types = {str(s.id): s.seat_type.value for s in subscription_spaces.free_seats()}
            return render_template("admin/companies/subscription_form.html", form=form,
                                   subject_name=subject_name, back_url=back_url, plan_meta=meta,
                                   seat_types=seat_types)

        if form.validate_on_submit():
            plan = PricingPlan.query.get_or_404(form.plan_id.data)
            seats, new_location, new_code, extra, error = _read_spaces(form, plan)
            if error:
                flash(error, "warning")
                return _page()
            sub = Subscription(
                plan_id=plan.id,
                people_per_unit=subscription_spaces.people_per_unit(plan),
                extra_people=extra,
                extra_person_price=Decimal(plan.additional_seat_rate or 0),
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
            try:
                if new_code:
                    seats.append(subscription_spaces.create_space(new_location, new_code, plan))
            except subscription_spaces.SpaceError as exc:
                db.session.rollback()
                flash(str(exc), "warning")
                return _page()
            subscription_spaces.attach_spaces(sub, seats)
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
            form.extra_people.data = 0
        return _page()

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
        subscription_spaces.end_places(sub, sub.end_date)
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
        subscription_spaces.end_places(sub, sub.end_date)
        db.session.commit()
        audit_service.record("subscription.cancelled", "subscription", sub.id, {"company_id": company_id})
        flash("Subscription cancelled.", "info")
        return redirect(url_for("admin.company_detail", company_id=company_id))

    @bp.route("/subscriptions/<int:sub_id>/extra-people", methods=["POST"])
    @manager_or_super_required
    def subscription_extra_people(sub_id: int):
        sub = Subscription.query.filter_by(id=sub_id, status=SubscriptionStatus.ACTIVE).first_or_404()
        back = (url_for("admin.company_detail", company_id=sub.company_id) if sub.company_id
                else url_for("admin.individuals_list"))
        mode = "prorate" if request.form.get("mode") == "prorate" else "next"
        try:
            count = int(request.form.get("extra_people", ""))
            _invoice, message = subscription_spaces.change_extra_people(sub, count, mode)
        except (ValueError, subscription_spaces.SpaceError) as exc:
            db.session.rollback()
            flash(str(exc) if isinstance(exc, subscription_spaces.SpaceError) else "Enter a whole number.",
                  "warning")
            return redirect(back)
        db.session.commit()
        audit_service.record("subscription.extra_people", "subscription", sub.id,
                             {"extra_people": sub.extra_people, "mode": mode})
        flash(message, "success")
        return redirect(back)

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
