"""Platform Owner routes: manage operators (create, edit, list, dashboard)."""
from __future__ import annotations

from decimal import Decimal

from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app, abort
from flask_login import current_user

from ...extensions import db
from ...models import (
    Operator, OperatorStatus, User, UserRole, Company, Location,
    PricingPlan, PlanType, BillingCycle, EmailTemplate, EmailKind,
    AuditLog, Invoice, PricingTier, PlatformPaymentReport,
)
from ...services import audit_service
from ...services import credit_service
from ...services import mail_service
from ...services.locale_data import CURRENCY_SYMBOLS
from ...utils.decorators import platform_staff_required, platform_permission_required
from .forms import OperatorForm, NewOperatorForm


platform_bp = Blueprint("platform", __name__, template_folder="../../templates")


def _normalize_primary_domain(raw: str | None, slug: str, base: str) -> str:
    """A bare slug/subdomain (no base domain) silently breaks operator
    resolution by Host header, so always ensure the full domain is stored."""
    domain = (raw or "").strip().lower()
    if not domain:
        return f"{slug}.{base}"
    if domain != base and not domain.endswith(f".{base}"):
        return f"{domain}.{base}"
    return domain


def _seed_operator_defaults(operator: Operator) -> None:
    """Seed a fresh operator with sensible starter data — pricing plans + email templates."""
    plans_seed = [
        ("Hot Desk Monthly", PlanType.HOT_DESK, BillingCycle.MONTHLY, Decimal("12000"), 1),
        ("Dedicated Desk", PlanType.DEDICATED_DESK, BillingCycle.MONTHLY, Decimal("22000"), 1),
        ("Private Office (4-person)", PlanType.PRIVATE_OFFICE, BillingCycle.MONTHLY, Decimal("85000"), 1),
        ("All Access", PlanType.ALL_ACCESS, BillingCycle.MONTHLY, Decimal("18000"), 0),
        ("Day Pass", PlanType.DAY_PASS, BillingCycle.DAILY, Decimal("900"), 1),
    ]
    for name, ptype, cycle, price, max_loc in plans_seed:
        db.session.add(PricingPlan(
            operator_id=operator.id, name=name, plan_type=ptype, billing_cycle=cycle,
            base_price=price, max_locations=max_loc,
        ))

    tmpl_seed = [
        ("welcome_member", "Welcome to {{ app.name }}", EmailKind.WELCOME_MEMBER,
         "<p>Hi {{ user.full_name }},</p><p>Welcome to {{ app.name }}!</p>"),
        ("booking_confirmation", "Booking confirmed", EmailKind.BOOKING_CONFIRMATION,
         "<p>Hi {{ user.full_name }}, your booking of {{ booking.room_name }} on {{ booking.start_at }} is confirmed.</p>"),
        ("invoice_issued", "Invoice {{ invoice.number }}", EmailKind.INVOICE_ISSUED,
         "<p>Your invoice {{ invoice.number }} for {{ invoice.total_amount }} is due on {{ invoice.due_date }}.</p>"),
    ]
    for code, subject, kind, body in tmpl_seed:
        db.session.add(EmailTemplate(
            operator_id=operator.id, code=code, name=subject, kind=kind,
            subject=subject, body_html=body, is_active=True,
        ))
    credit_service.seed_default_categories(operator.id)


@platform_bp.route("/")
@platform_staff_required
def dashboard():
    from ...services import platform_dashboard
    waiting, waiting_total = [], 0
    if current_user.has_platform_permission("billing"):
        pending = PlatformPaymentReport.query.filter_by(status="pending")
        waiting_total = pending.count()
        waiting = pending.order_by(PlatformPaymentReport.created_at).limit(5).all()
    return render_template("platform/dashboard.html", dash=platform_dashboard.build(),
                           waiting=waiting, waiting_total=waiting_total)


@platform_bp.route("/operators")
@platform_staff_required
def operators_list():
    if not any(current_user.has_platform_permission(permission)
               for permission in ("operators", "operator_suspension")):
        abort(403)
    operators = (Operator.query
               .execution_options(skip_operator_filter=True)
               .order_by(Operator.name).all())
    # Enrich with counts (bypass filter)
    for t in operators:
        t._user_count = (User.query.execution_options(skip_operator_filter=True)
                                    .filter_by(operator_id=t.id).count())
        t._location_count = (Location.query.execution_options(skip_operator_filter=True)
                                            .filter_by(operator_id=t.id).count())
    return render_template("platform/operators_list.html", operators=operators)


@platform_bp.route("/operators/new", methods=["GET", "POST"])
@platform_permission_required("operators")
def operator_new():
    form = NewOperatorForm()
    if (form.is_submitted() and form.status.data == OperatorStatus.SUSPENDED.value
            and not current_user.has_platform_permission("operator_suspension")):
        abort(403)
    form.plan_tier.choices = [(t.key, t.name) for t in
                              PricingTier.query.filter_by(is_active=True).order_by(PricingTier.id).all()]
    if form.validate_on_submit():
        slug = form.slug.data.lower().strip()
        base = current_app.config.get("PLATFORM_BASE_DOMAIN", "hub1z.com")
        form.primary_domain.data = _normalize_primary_domain(form.primary_domain.data, slug, base)

        existing = (Operator.query
                    .execution_options(skip_operator_filter=True)
                    .filter_by(slug=slug).first())
        if existing:
            flash("An operator with that workspace slug already exists.", "warning")
            return render_template("platform/operator_form.html", form=form, title="New operator")

        t = Operator()
        for f in OperatorForm.__dict__:
            if f.startswith("_") or f in ("submit", "seed_defaults"):
                continue
            if hasattr(t, f) and hasattr(form, f):
                val = getattr(form, f).data
                setattr(t, f, val)
        t.currency_symbol = CURRENCY_SYMBOLS.get(t.currency_code, t.currency_symbol)
        db.session.add(t)
        db.session.flush()

        # First super admin for this operator
        u = User(
            operator_id=t.id,
            email=form.admin_email.data.lower().strip(),
            full_name=form.admin_name.data.strip(),
            role=UserRole.SUPER_ADMIN,
            is_active=True, email_verified=True,
        )
        u.set_password(form.admin_password.data)
        db.session.add(u)

        if form.seed_defaults.data:
            _seed_operator_defaults(t)

        db.session.commit()
        audit_service.record("operator.created", "operator", t.id,
                             {"slug": t.slug, "name": t.name})
        flash(f"Operator workspace {t.name} provisioned. Owner: {u.email}", "success")
        return redirect(url_for("platform.operators_list"))
    return render_template("platform/operator_form.html", form=form, title="Provision new operator")


@platform_bp.route("/operators/<int:operator_id>/edit", methods=["GET", "POST"])
@platform_permission_required("operators")
def operator_edit(operator_id: int):
    t = (Operator.query.execution_options(skip_operator_filter=True)
                     .filter_by(id=operator_id).first_or_404())
    form = OperatorForm(obj=t)
    if (form.is_submitted() and form.status.data != t.status.value
            and OperatorStatus.SUSPENDED.value in (form.status.data, t.status.value)
            and not current_user.has_platform_permission("operator_suspension")):
        abort(403)
    tiers = PricingTier.query.filter_by(is_active=True).order_by(PricingTier.id).all()
    choices = [(pt.key, pt.name) for pt in tiers]
    if t.plan_tier and t.plan_tier not in {k for k, _ in choices}:
        choices.append((t.plan_tier, f"{t.plan_tier} (retired)"))
    form.plan_tier.choices = choices
    if form.validate_on_submit():
        base = current_app.config.get("PLATFORM_BASE_DOMAIN", "hub1z.com")
        form.primary_domain.data = _normalize_primary_domain(form.primary_domain.data, t.slug, base)
        form.populate_obj(t)
        t.currency_symbol = CURRENCY_SYMBOLS.get(t.currency_code, t.currency_symbol)
        db.session.commit()
        audit_service.record("operator.updated", "operator", t.id, {"slug": t.slug})
        flash("Operator workspace updated.", "success")
        return redirect(url_for("platform.operators_list"))
    return render_template("platform/operator_form.html", form=form,
                           title=f"Edit {t.name}", operator=t)


@platform_bp.route("/operators/<int:operator_id>/send-password-reset", methods=["POST"])
@platform_permission_required("operators")
def operator_send_password_reset(operator_id: int):
    """Email a password-reset link to the operator's Super Admin(s) — for
    when an operator is locked out and can't use self-service Forgot
    Password (e.g. they no longer have access to that inbox)."""
    t = (Operator.query.execution_options(skip_operator_filter=True)
                     .filter_by(id=operator_id).first_or_404())
    admins = (User.query.execution_options(skip_operator_filter=True)
              .filter_by(operator_id=t.id, role=UserRole.SUPER_ADMIN, is_active=True).all())
    if not admins:
        flash(f"{t.name} has no active Super Admin to send a reset link to.", "warning")
        return redirect(url_for("platform.operator_edit", operator_id=t.id))
    for admin in admins:
        token = mail_service.make_token(admin.id, "password-reset")
        reset_url = url_for("auth.reset_password", token=token, _external=True)
        mail_service.send(
            subject=f"Reset your {current_app.config['APP_NAME']} password",
            recipient=admin.email,
            template="password_reset",
            user=admin, reset_url=reset_url, ttl_hours=2,
        )
    audit_service.record("operator.password_reset_sent", "operator", t.id, {"slug": t.slug})
    flash(f"Password reset link sent to: {', '.join(a.email for a in admins)}.", "success")
    return redirect(url_for("platform.operator_edit", operator_id=t.id))


@platform_bp.route("/operators/<int:operator_id>/approve", methods=["POST"])
@platform_permission_required("operators")
def operator_approve(operator_id: int):
    """TRIAL -> ACTIVE. For operators that came in via /platform/operators/invite
    (directly-provisioned operators from /platform/operators/new start ACTIVE already)."""
    t = (Operator.query.execution_options(skip_operator_filter=True)
                     .filter_by(id=operator_id).first_or_404())
    if t.status != OperatorStatus.TRIAL:
        flash(f"{t.name} isn't pending approval.", "warning")
        return redirect(url_for("platform.operators_list"))
    t.status = OperatorStatus.ACTIVE
    db.session.commit()
    audit_service.record("operator.approved", "operator", t.id, {"slug": t.slug})
    flash(f"{t.name} approved and now active.", "success")
    return redirect(url_for("platform.operators_list"))


@platform_bp.route("/operators/<int:operator_id>/hold", methods=["POST"])
@platform_permission_required("operators")
def operator_hold(operator_id: int):
    """Soft, reversible pause — available to any staffer with the 'operators' grant."""
    t = (Operator.query.execution_options(skip_operator_filter=True)
                     .filter_by(id=operator_id).first_or_404())
    if t.status == OperatorStatus.SUSPENDED:
        flash(f"{t.name} is suspended; only a Platform Super Admin can change that.", "warning")
        return redirect(url_for("platform.operators_list"))
    t.status = OperatorStatus.HOLD
    db.session.commit()
    audit_service.record("operator.held", "operator", t.id, {"slug": t.slug})
    flash(f"{t.name} placed on hold.", "info")
    return redirect(url_for("platform.operators_list"))


@platform_bp.route("/operators/<int:operator_id>/release-hold", methods=["POST"])
@platform_permission_required("operators")
def operator_release_hold(operator_id: int):
    t = (Operator.query.execution_options(skip_operator_filter=True)
                     .filter_by(id=operator_id).first_or_404())
    if t.status != OperatorStatus.HOLD:
        flash(f"{t.name} isn't on hold.", "warning")
        return redirect(url_for("platform.operators_list"))
    t.status = OperatorStatus.ACTIVE
    db.session.commit()
    audit_service.record("operator.hold_released", "operator", t.id, {"slug": t.slug})
    flash(f"{t.name} is active again.", "success")
    return redirect(url_for("platform.operators_list"))


@platform_bp.route("/operators/<int:operator_id>/suspend", methods=["POST"])
@platform_permission_required("operator_suspension")
def operator_suspend(operator_id: int):
    """Hard stop (deactivation): the Owner, or a Manager granted Suspend & reactivate."""
    t = (Operator.query.execution_options(skip_operator_filter=True)
                     .filter_by(id=operator_id).first_or_404())
    t.status = OperatorStatus.SUSPENDED
    db.session.commit()
    audit_service.record("operator.suspended", "operator", t.id, {"slug": t.slug})
    flash(f"{t.name} suspended.", "info")
    return redirect(url_for("platform.operators_list"))


@platform_bp.route("/operators/<int:operator_id>/activate", methods=["POST"])
@platform_permission_required("operator_suspension")
def operator_activate(operator_id: int):
    """Reactivating out of a hard Suspend, gated like Suspend itself.
    (Reactivating from Hold is operator_release_hold.)"""
    t = (Operator.query.execution_options(skip_operator_filter=True)
                     .filter_by(id=operator_id).first_or_404())
    t.status = OperatorStatus.ACTIVE
    db.session.commit()
    audit_service.record("operator.activated", "operator", t.id, {"slug": t.slug})
    flash(f"{t.name} activated.", "success")
    return redirect(url_for("platform.operators_list"))
