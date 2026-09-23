"""Tenant-initiated invites: a tenant admin/manager invites an Individual or
a Company to join their workspace. The invitee finishes signup (sets their
own password) via a signed, time-limited link — same mechanism as the
existing employee invite flow in app/blueprints/company/routes.py.

This is separate from self-serve signup (/auth/register, /auth/register/company),
which is initiated by the prospect instead of the tenant.
"""
from __future__ import annotations

from flask import render_template, redirect, url_for, flash, g, current_app
from flask_login import login_user

from ...extensions import db
from ...models import User, UserRole, Company, CompanyStatus, Location
from ...utils.decorators import manager_or_super_required, super_admin_required
from ...services import mail_service, tier_limits
from .forms import (
    InviteIndividualForm, InviteCompanyForm, InviteTeamMemberForm, AcceptTenantInviteForm,
)

INVITE_TTL_SECONDS = 60 * 60 * 24 * 7  # 7 days


def register_invite_routes(bp):

    @bp.route("/invites")
    @manager_or_super_required
    def invites_list():
        pending_individuals = (User.query
                               .filter_by(role=UserRole.INDIVIDUAL, is_active=False)
                               .order_by(User.created_at.desc()).all())
        pending_companies = (User.query
                             .filter_by(role=UserRole.COMPANY_ADMIN, is_active=False)
                             .order_by(User.created_at.desc()).all())
        pending_team = (User.query
                        .filter(User.role.in_([UserRole.MANAGER, UserRole.LOCATION_MANAGER]),
                               User.is_active.is_(False))
                        .order_by(User.created_at.desc()).all())
        return render_template("admin/invites/list.html",
                               pending_individuals=pending_individuals,
                               pending_companies=pending_companies,
                               pending_team=pending_team)

    # ------------------------------------------------------------ individual --

    @bp.route("/invites/individual/new", methods=["GET", "POST"])
    @manager_or_super_required
    def invite_individual_new():
        form = InviteIndividualForm()
        if form.validate_on_submit():
            email = form.email.data.lower().strip()
            if User.query.filter_by(email=email).first():
                flash("That email is already registered under this workspace.", "warning")
                return redirect(url_for("admin.invites_list"))
            ok, msg = tier_limits.check_limit(getattr(g, "tenant", None), "person")
            if not ok:
                flash(msg, "warning")
                return redirect(url_for("admin.invites_list"))

            u = User(
                tenant_id=getattr(g, "tenant_id", None),
                email=email,
                full_name=form.full_name.data.strip(),
                role=UserRole.INDIVIDUAL,
                is_active=False,  # activated when invite is accepted
            )
            u.set_password(current_app.config["SECRET_KEY"] + email)
            db.session.add(u)
            db.session.commit()

            token = mail_service.make_token(u.id, "tenant-member-invite")
            accept_url = url_for("admin.accept_member_invite", token=token, _external=True)
            tenant_name = getattr(g.tenant, "name", None) if getattr(g, "tenant", None) else current_app.config.get("APP_NAME")
            mail_service.send(
                subject=f"You're invited to {tenant_name}",
                recipient=u.email,
                template="tenant_member_invite",
                user=u, tenant_name=tenant_name, accept_url=accept_url,
                ttl_days=INVITE_TTL_SECONDS // 86400,
            )
            flash(f"Invitation sent to {u.email}.", "success")
            return redirect(url_for("admin.invites_list"))
        return render_template("admin/invites/individual_form.html", form=form)

    @bp.route("/invites/accept/<token>", methods=["GET", "POST"])
    def accept_member_invite(token: str):
        uid = mail_service.read_token(token, "tenant-member-invite", INVITE_TTL_SECONDS)
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
            flash("Welcome!", "success")
            return redirect(url_for("member.dashboard"))
        return render_template("admin/invites/accept.html", form=form, user=user)

    # --------------------------------------------------------------- company --

    @bp.route("/invites/company/new", methods=["GET", "POST"])
    @manager_or_super_required
    def invite_company_new():
        form = InviteCompanyForm()
        if form.validate_on_submit():
            admin_email = form.admin_email.data.lower().strip()
            if User.query.filter_by(email=admin_email).first():
                flash("That admin email is already registered under this workspace.", "warning")
                return redirect(url_for("admin.invites_list"))
            if Company.query.filter_by(name=form.company_name.data.strip()).first():
                flash("A company with that name already exists.", "warning")
                return redirect(url_for("admin.invites_list"))
            ok, msg = tier_limits.check_limit(getattr(g, "tenant", None), "person")
            if not ok:
                flash(msg, "warning")
                return redirect(url_for("admin.invites_list"))

            tenant_id = getattr(g, "tenant_id", None)
            company = Company(
                tenant_id=tenant_id,
                name=form.company_name.data.strip(),
                billing_email=form.billing_email.data.lower().strip(),
                status=CompanyStatus.PROSPECT,
            )
            db.session.add(company)
            db.session.flush()

            admin = User(
                tenant_id=tenant_id,
                email=admin_email,
                full_name=form.admin_full_name.data.strip(),
                role=UserRole.COMPANY_ADMIN,
                company_id=company.id,
                is_active=False,  # activated when invite is accepted
            )
            admin.set_password(current_app.config["SECRET_KEY"] + admin_email)
            db.session.add(admin)
            db.session.commit()

            token = mail_service.make_token(admin.id, "tenant-company-invite")
            accept_url = url_for("admin.accept_company_invite", token=token, _external=True)
            tenant_name = getattr(g.tenant, "name", None) if getattr(g, "tenant", None) else current_app.config.get("APP_NAME")
            mail_service.send(
                subject=f"You're invited to set up {company.name} on {tenant_name}",
                recipient=admin.email,
                template="tenant_company_invite",
                user=admin, company=company, tenant_name=tenant_name, accept_url=accept_url,
                ttl_days=INVITE_TTL_SECONDS // 86400,
            )
            flash(f"Invitation sent to {admin.email}.", "success")
            return redirect(url_for("admin.invites_list"))
        return render_template("admin/invites/company_form.html", form=form)

    @bp.route("/invites/accept-company/<token>", methods=["GET", "POST"])
    def accept_company_invite(token: str):
        uid = mail_service.read_token(token, "tenant-company-invite", INVITE_TTL_SECONDS)
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
            if user.company:
                user.company.status = CompanyStatus.ACTIVE
            db.session.commit()
            login_user(user)
            flash(f"Welcome, {user.company.name if user.company else ''}!", "success")
            return redirect(url_for("company.dashboard"))
        return render_template("admin/invites/accept.html", form=form, user=user)

    # ----------------------------------------------------------------- revoke --

    @bp.route("/invites/individual/<int:user_id>/revoke", methods=["POST"])
    @manager_or_super_required
    def invite_individual_revoke(user_id: int):
        u = User.query.filter_by(id=user_id, role=UserRole.INDIVIDUAL, is_active=False).first_or_404()
        db.session.delete(u)
        db.session.commit()
        flash("Invitation revoked.", "info")
        return redirect(url_for("admin.invites_list"))

    @bp.route("/invites/company/<int:company_id>/revoke", methods=["POST"])
    @manager_or_super_required
    def invite_company_revoke(company_id: int):
        company = Company.query.filter_by(id=company_id, status=CompanyStatus.PROSPECT).first_or_404()
        admins = User.query.filter_by(company_id=company.id, role=UserRole.COMPANY_ADMIN).all()
        if any(a.is_active for a in admins):
            flash("This company has already been set up; it can't be revoked.", "warning")
            return redirect(url_for("admin.invites_list"))
        for a in admins:
            db.session.delete(a)
        db.session.delete(company)
        db.session.commit()
        flash("Invitation revoked.", "info")
        return redirect(url_for("admin.invites_list"))

    # ------------------------------------------------------------------ team --
    # A tenant can span multiple locations, so a Location Manager must be
    # scoped to exactly one of them. Always Super-Admin-only to send — never
    # delegable to an existing Manager, same guard as Platform Manager creation.

    @bp.route("/invites/team/new", methods=["GET", "POST"])
    @super_admin_required
    def invite_team_new():
        form = InviteTeamMemberForm()
        form.location_id.choices = [(0, "— not applicable —")] + [
            (loc.id, loc.name) for loc in Location.query.order_by(Location.name).all()
        ]
        if form.validate_on_submit():
            email = form.email.data.lower().strip()
            if User.query.filter_by(email=email).first():
                flash("That email is already registered under this workspace.", "warning")
                return redirect(url_for("admin.invites_list"))
            if form.role.data == "location_manager" and not form.location_id.data:
                flash("Pick a location for a Location Manager.", "warning")
                return render_template("admin/invites/team_form.html", form=form)

            role = UserRole.LOCATION_MANAGER if form.role.data == "location_manager" else UserRole.MANAGER
            u = User(
                tenant_id=getattr(g, "tenant_id", None),
                email=email,
                full_name=form.full_name.data.strip(),
                role=role,
                managed_location_id=form.location_id.data if role == UserRole.LOCATION_MANAGER else None,
                is_active=False,  # activated when invite is accepted
            )
            u.set_password(current_app.config["SECRET_KEY"] + email)
            db.session.add(u)
            db.session.commit()

            token = mail_service.make_token(u.id, "tenant-team-invite")
            accept_url = url_for("admin.accept_team_invite", token=token, _external=True)
            tenant_name = getattr(g.tenant, "name", None) if getattr(g, "tenant", None) else current_app.config.get("APP_NAME")
            mail_service.send(
                subject=f"You're invited to join the {tenant_name} team",
                recipient=u.email,
                template="tenant_team_invite",
                user=u, tenant_name=tenant_name, accept_url=accept_url,
                role_label=("Location Manager" if role == UserRole.LOCATION_MANAGER else "Manager"),
                location=(u.managed_location if u.managed_location_id else None),
                ttl_days=INVITE_TTL_SECONDS // 86400,
            )
            flash(f"Invitation sent to {u.email}.", "success")
            return redirect(url_for("admin.invites_list"))
        return render_template("admin/invites/team_form.html", form=form)

    @bp.route("/invites/accept-team/<token>", methods=["GET", "POST"])
    def accept_team_invite(token: str):
        uid = mail_service.read_token(token, "tenant-team-invite", INVITE_TTL_SECONDS)
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
            flash("Welcome to the team!", "success")
            return redirect(url_for("admin.dashboard"))
        return render_template("admin/invites/accept.html", form=form, user=user)

    @bp.route("/invites/team/<int:user_id>/revoke", methods=["POST"])
    @super_admin_required
    def invite_team_revoke(user_id: int):
        u = User.query.filter_by(
            id=user_id, is_active=False,
        ).filter(User.role.in_([UserRole.MANAGER, UserRole.LOCATION_MANAGER])).first_or_404()
        db.session.delete(u)
        db.session.commit()
        flash("Invitation revoked.", "info")
        return redirect(url_for("admin.invites_list"))
