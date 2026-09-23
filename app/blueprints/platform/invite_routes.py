"""Platform invites a prospective coworking business to become a tenant.

Distinct from direct provisioning (/platform/tenants/new, staff sets
everything including the admin password and the tenant goes live
immediately): here the business sets its own password via a signed link,
and the tenant lands as TRIAL pending an explicit /platform/tenants/<id>/approve.
"""
from __future__ import annotations

from flask import render_template, redirect, url_for, flash, current_app
from flask_login import login_user

from ...extensions import db
from ...models import Tenant, TenantStatus, User, UserRole
from ...services import audit_service, mail_service
from ...utils.decorators import platform_permission_required
from .forms import InviteTenantForm
from ..admin.forms import AcceptTenantInviteForm

INVITE_TTL_SECONDS = 60 * 60 * 24 * 7  # 7 days


def register_invite_routes(bp):

    @bp.route("/tenants/invite", methods=["GET", "POST"])
    @platform_permission_required("tenants")
    def tenant_invite():
        form = InviteTenantForm()
        if form.validate_on_submit():
            slug = form.slug.data.lower().strip()
            admin_email = form.admin_email.data.lower().strip()

            if Tenant.query.execution_options(skip_tenant_filter=True).filter_by(slug=slug).first():
                flash("A tenant with that slug already exists.", "warning")
                return render_template("platform/tenant_invite_form.html", form=form)
            if User.query.execution_options(skip_tenant_filter=True).filter_by(email=admin_email).first():
                flash("That admin email is already registered.", "warning")
                return render_template("platform/tenant_invite_form.html", form=form)

            base = current_app.config.get("PLATFORM_BASE_DOMAIN", "hub1z.com")
            t = Tenant(
                slug=slug, name=form.name.data.strip(),
                primary_domain=f"{slug}.{base}", status=TenantStatus.TRIAL,
            )
            db.session.add(t)
            db.session.flush()

            admin = User(
                tenant_id=t.id, email=admin_email,
                full_name=form.admin_name.data.strip(),
                role=UserRole.SUPER_ADMIN,
                is_active=False,  # activated when the invite is accepted
            )
            admin.set_password(current_app.config["SECRET_KEY"] + admin_email)
            db.session.add(admin)
            db.session.commit()

            token = mail_service.make_token(admin.id, "platform-tenant-invite")
            accept_url = url_for("platform.tenant_accept_invite", token=token, _external=True)
            mail_service.send(
                subject=f"You're invited to bring {t.name} onto {current_app.config['APP_NAME']}",
                recipient=admin.email,
                template="platform_tenant_invite",
                user=admin, tenant=t, accept_url=accept_url,
                ttl_days=INVITE_TTL_SECONDS // 86400,
            )
            audit_service.record("tenant.invited", "tenant", t.id,
                                 {"slug": t.slug, "admin_email": admin.email})
            flash(f"Invitation sent to {admin.email}.", "success")
            return redirect(url_for("platform.tenants_list"))
        return render_template("platform/tenant_invite_form.html", form=form)

    @bp.route("/tenants/accept/<token>", methods=["GET", "POST"])
    def tenant_accept_invite(token: str):
        uid = mail_service.read_token(token, "platform-tenant-invite", INVITE_TTL_SECONDS)
        if uid is None:
            flash("This invitation link is invalid or has expired.", "danger")
            return redirect(url_for("auth.login"))
        user = User.query.filter_by(id=int(uid)) \
                         .execution_options(skip_tenant_filter=True).first()
        if user is None:
            flash("Account not found.", "danger")
            return redirect(url_for("auth.login"))
        if user.is_active:
            flash("This invitation has already been accepted. Please sign in.", "info")
            return redirect(url_for("auth.login"))

        form = AcceptTenantInviteForm()
        if form.validate_on_submit():
            user.set_password(form.password.data)
            user.is_active = True
            user.email_verified = True
            db.session.commit()
            login_user(user)
            flash("Your account is set up. Your workspace is pending platform approval "
                 "before it goes fully live.", "success")
            return redirect(url_for("admin.dashboard"))
        return render_template("platform/tenant_accept_invite.html", form=form, user=user)
