"""Platform Owner routes: manage tenants (create, edit, list, dashboard)."""
from __future__ import annotations

from decimal import Decimal

from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app

from ...extensions import db
from ...models import (
    Tenant, TenantStatus, User, UserRole, Company, Location,
    PricingPlan, PlanType, BillingCycle, EmailTemplate, EmailKind,
    AuditLog, Invoice, PricingTier,
)
from ...services import audit_service
from ...utils.decorators import (
    platform_staff_required, platform_permission_required, platform_owner_required,
)
from .forms import TenantForm, NewTenantForm


platform_bp = Blueprint("platform", __name__, template_folder="../../templates")


def _seed_tenant_defaults(tenant: Tenant) -> None:
    """Seed a fresh tenant with sensible starter data — pricing plans + email templates."""
    plans_seed = [
        ("Hot Desk Monthly", PlanType.HOT_DESK, BillingCycle.MONTHLY, Decimal("12000"), 8, 1),
        ("Dedicated Desk", PlanType.DEDICATED_DESK, BillingCycle.MONTHLY, Decimal("22000"), 20, 1),
        ("Private Office (4-person)", PlanType.PRIVATE_OFFICE, BillingCycle.MONTHLY, Decimal("85000"), 40, 1),
        ("All Access", PlanType.ALL_ACCESS, BillingCycle.MONTHLY, Decimal("18000"), 12, 0),
        ("Day Pass", PlanType.DAY_PASS, BillingCycle.DAILY, Decimal("900"), 0, 1),
    ]
    for name, ptype, cycle, price, credits, max_loc in plans_seed:
        db.session.add(PricingPlan(
            tenant_id=tenant.id, name=name, plan_type=ptype, billing_cycle=cycle,
            base_price=price, included_meeting_credits=credits, max_locations=max_loc,
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
            tenant_id=tenant.id, code=code, name=subject, kind=kind,
            subject=subject, body_html=body, is_active=True,
        ))


@platform_bp.route("/")
@platform_staff_required
def dashboard():
    stats = {
        "tenants": Tenant.query.execution_options(skip_tenant_filter=True).count(),
        "active_tenants": Tenant.query.execution_options(skip_tenant_filter=True)
                                       .filter_by(status=TenantStatus.ACTIVE).count(),
        "total_users": User.query.execution_options(skip_tenant_filter=True).count(),
        "total_companies": Company.query.execution_options(skip_tenant_filter=True).count(),
        "total_locations": Location.query.execution_options(skip_tenant_filter=True).count(),
        "total_invoices": Invoice.query.execution_options(skip_tenant_filter=True).count(),
    }
    return render_template("platform/dashboard.html", stats=stats)


@platform_bp.route("/tenants")
@platform_permission_required("tenants")
def tenants_list():
    tenants = (Tenant.query
               .execution_options(skip_tenant_filter=True)
               .order_by(Tenant.name).all())
    # Enrich with counts (bypass filter)
    for t in tenants:
        t._user_count = (User.query.execution_options(skip_tenant_filter=True)
                                    .filter_by(tenant_id=t.id).count())
        t._location_count = (Location.query.execution_options(skip_tenant_filter=True)
                                            .filter_by(tenant_id=t.id).count())
    return render_template("platform/tenants_list.html", tenants=tenants)


@platform_bp.route("/tenants/new", methods=["GET", "POST"])
@platform_permission_required("tenants")
def tenant_new():
    form = NewTenantForm()
    form.plan_tier.choices = [(t.key, t.name) for t in
                              PricingTier.query.filter_by(is_active=True).order_by(PricingTier.id).all()]
    if form.validate_on_submit():
        slug = form.slug.data.lower().strip()
        # Auto-fill primary_domain if the operator left it blank
        if not (form.primary_domain.data or "").strip():
            base = current_app.config.get("PLATFORM_BASE_DOMAIN", "hub1z.com")
            form.primary_domain.data = f"{slug}.{base}"

        existing = (Tenant.query
                    .execution_options(skip_tenant_filter=True)
                    .filter_by(slug=slug).first())
        if existing:
            flash("A tenant with that slug already exists.", "warning")
            return render_template("platform/tenant_form.html", form=form, title="New tenant")

        t = Tenant()
        for f in TenantForm.__dict__:
            if hasattr(t, f) and hasattr(form, f) and f not in ("submit", "seed_defaults"):
                val = getattr(form, f).data
                setattr(t, f, val)
        db.session.add(t)
        db.session.flush()

        # First super admin for this tenant
        u = User(
            tenant_id=t.id,
            email=form.admin_email.data.lower().strip(),
            full_name=form.admin_name.data.strip(),
            role=UserRole.SUPER_ADMIN,
            is_active=True, email_verified=True,
        )
        u.set_password(form.admin_password.data)
        db.session.add(u)

        if form.seed_defaults.data:
            _seed_tenant_defaults(t)

        db.session.commit()
        audit_service.record("tenant.created", "tenant", t.id,
                             {"slug": t.slug, "name": t.name})
        flash(f"Tenant {t.name} provisioned. Admin: {u.email}", "success")
        return redirect(url_for("platform.tenants_list"))
    return render_template("platform/tenant_form.html", form=form, title="Provision new tenant")


@platform_bp.route("/tenants/<int:tenant_id>/edit", methods=["GET", "POST"])
@platform_permission_required("tenants")
def tenant_edit(tenant_id: int):
    t = (Tenant.query.execution_options(skip_tenant_filter=True)
                     .filter_by(id=tenant_id).first_or_404())
    form = TenantForm(obj=t)
    tiers = PricingTier.query.filter_by(is_active=True).order_by(PricingTier.id).all()
    choices = [(pt.key, pt.name) for pt in tiers]
    if t.plan_tier and t.plan_tier not in {k for k, _ in choices}:
        choices.append((t.plan_tier, f"{t.plan_tier} (retired)"))
    form.plan_tier.choices = choices
    if form.validate_on_submit():
        form.populate_obj(t)
        db.session.commit()
        audit_service.record("tenant.updated", "tenant", t.id, {"slug": t.slug})
        flash("Tenant updated.", "success")
        return redirect(url_for("platform.tenants_list"))
    return render_template("platform/tenant_form.html", form=form,
                           title=f"Edit {t.name}", tenant=t)


@platform_bp.route("/tenants/<int:tenant_id>/approve", methods=["POST"])
@platform_permission_required("tenants")
def tenant_approve(tenant_id: int):
    """TRIAL -> ACTIVE. For tenants that came in via /platform/tenants/invite
    (directly-provisioned tenants from /platform/tenants/new start ACTIVE already)."""
    t = (Tenant.query.execution_options(skip_tenant_filter=True)
                     .filter_by(id=tenant_id).first_or_404())
    if t.status != TenantStatus.TRIAL:
        flash(f"{t.name} isn't pending approval.", "warning")
        return redirect(url_for("platform.tenants_list"))
    t.status = TenantStatus.ACTIVE
    db.session.commit()
    audit_service.record("tenant.approved", "tenant", t.id, {"slug": t.slug})
    flash(f"{t.name} approved and now active.", "success")
    return redirect(url_for("platform.tenants_list"))


@platform_bp.route("/tenants/<int:tenant_id>/hold", methods=["POST"])
@platform_permission_required("tenants")
def tenant_hold(tenant_id: int):
    """Soft, reversible pause — available to any staffer with the 'tenants' grant."""
    t = (Tenant.query.execution_options(skip_tenant_filter=True)
                     .filter_by(id=tenant_id).first_or_404())
    if t.status == TenantStatus.SUSPENDED:
        flash(f"{t.name} is suspended; only a Platform Super Admin can change that.", "warning")
        return redirect(url_for("platform.tenants_list"))
    t.status = TenantStatus.HOLD
    db.session.commit()
    audit_service.record("tenant.held", "tenant", t.id, {"slug": t.slug})
    flash(f"{t.name} placed on hold.", "info")
    return redirect(url_for("platform.tenants_list"))


@platform_bp.route("/tenants/<int:tenant_id>/release-hold", methods=["POST"])
@platform_permission_required("tenants")
def tenant_release_hold(tenant_id: int):
    t = (Tenant.query.execution_options(skip_tenant_filter=True)
                     .filter_by(id=tenant_id).first_or_404())
    if t.status != TenantStatus.HOLD:
        flash(f"{t.name} isn't on hold.", "warning")
        return redirect(url_for("platform.tenants_list"))
    t.status = TenantStatus.ACTIVE
    db.session.commit()
    audit_service.record("tenant.hold_released", "tenant", t.id, {"slug": t.slug})
    flash(f"{t.name} is active again.", "success")
    return redirect(url_for("platform.tenants_list"))


@platform_bp.route("/tenants/<int:tenant_id>/suspend", methods=["POST"])
@platform_owner_required
def tenant_suspend(tenant_id: int):
    """Hard stop (deactivation) — Platform Super Admin only, not delegable."""
    t = (Tenant.query.execution_options(skip_tenant_filter=True)
                     .filter_by(id=tenant_id).first_or_404())
    t.status = TenantStatus.SUSPENDED
    db.session.commit()
    audit_service.record("tenant.suspended", "tenant", t.id, {"slug": t.slug})
    flash(f"{t.name} suspended.", "info")
    return redirect(url_for("platform.tenants_list"))


@platform_bp.route("/tenants/<int:tenant_id>/activate", methods=["POST"])
@platform_owner_required
def tenant_activate(tenant_id: int):
    """Reactivating out of a hard Suspend — Platform Super Admin only, to match
    Suspend being Owner-exclusive. (Reactivating from Hold is tenant_release_hold.)"""
    t = (Tenant.query.execution_options(skip_tenant_filter=True)
                     .filter_by(id=tenant_id).first_or_404())
    t.status = TenantStatus.ACTIVE
    db.session.commit()
    audit_service.record("tenant.activated", "tenant", t.id, {"slug": t.slug})
    flash(f"{t.name} activated.", "success")
    return redirect(url_for("platform.tenants_list"))
