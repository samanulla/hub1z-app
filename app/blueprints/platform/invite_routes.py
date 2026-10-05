"""Platform invites a prospective coworking business to become an operator.

Distinct from direct provisioning (/platform/operators/new, staff sets
everything including the admin password and the operator goes live
    immediately): here the business sets its own password via a signed link.
Every new workspace starts a trial without platform approval.
"""
from __future__ import annotations

from flask import render_template, redirect, url_for, flash, current_app
from flask_login import logout_user

from ...extensions import db
from ...models import Operator, OperatorStatus, User, UserRole
from ...services import audit_service, mail_service
from ...services.operator_billing import start_trial
from ...services.operator_urls import workspace_url
from ...utils.decorators import platform_permission_required
from .forms import InviteOperatorForm
from ..admin.forms import AcceptOperatorInviteForm

INVITE_TTL_SECONDS = 60 * 60 * 24 * 7  # 7 days


def register_invite_routes(bp):

    @bp.route("/operators/invite", methods=["GET", "POST"])
    @platform_permission_required("operators")
    def operator_invite():
        form = InviteOperatorForm()
        if form.validate_on_submit():
            slug = form.slug.data.lower().strip()
            admin_email = form.admin_email.data.lower().strip()

            if Operator.query.execution_options(skip_operator_filter=True).filter_by(slug=slug).first():
                flash("An operator with that workspace slug already exists.", "warning")
                return render_template("platform/operator_invite_form.html", form=form)
            if User.query.execution_options(skip_operator_filter=True).filter_by(email=admin_email).first():
                flash("That admin email is already registered.", "warning")
                return render_template("platform/operator_invite_form.html", form=form)

            base = current_app.config.get("PLATFORM_BASE_DOMAIN", "hub1z.com")
            t = Operator(
                slug=slug, name=form.name.data.strip(),
                primary_domain=f"{slug}.{base}", status=OperatorStatus.TRIAL,
            )
            db.session.add(t)
            db.session.flush()

            admin = User(
                operator_id=t.id, email=admin_email,
                full_name=form.admin_name.data.strip(),
                role=UserRole.SUPER_ADMIN,
                is_active=False,  # activated when the invite is accepted
            )
            admin.set_password(current_app.config["SECRET_KEY"] + admin_email)
            db.session.add(admin)
            start_trial(t)
            db.session.commit()

            token = mail_service.make_token(admin.id, "platform-operator-invite")
            accept_url = url_for("platform.operator_accept_invite", token=token, _external=True)
            mail_service.send(
                subject=f"You're invited to bring {t.name} onto {current_app.config['APP_NAME']}",
                recipient=admin.email,
                template="platform_operator_invite",
                user=admin, operator=t, accept_url=accept_url,
                ttl_days=INVITE_TTL_SECONDS // 86400,
            )
            audit_service.record("operator.invited", "operator", t.id,
                                 {"slug": t.slug, "admin_email": admin.email})
            flash(f"Invitation sent to {admin.email}.", "success")
            return redirect(url_for("platform.operators_list"))
        return render_template("platform/operator_invite_form.html", form=form)

    @bp.route("/operators/accept/<token>", methods=["GET", "POST"])
    def operator_accept_invite(token: str):
        uid = mail_service.read_token(token, "platform-operator-invite", INVITE_TTL_SECONDS)
        if uid is None:
            flash("This invitation link is invalid or has expired.", "danger")
            return redirect(url_for("auth.login"))
        user = User.query.filter_by(id=int(uid)) \
                         .execution_options(skip_operator_filter=True).first()
        if user is None:
            flash("Account not found.", "danger")
            return redirect(url_for("auth.login"))
        if user.is_active:
            flash("This invitation has already been accepted. Please sign in.", "info")
            return redirect(url_for("auth.login"))

        form = AcceptOperatorInviteForm()
        if form.validate_on_submit():
            user.set_password(form.password.data)
            user.is_active = True
            user.email_verified = True
            if user.operator.trial_ends_at is None:
                start_trial(user.operator)
            db.session.commit()
            logout_user()
            return redirect(workspace_url(user.operator, "/auth/login"))
        return render_template("platform/operator_accept_invite.html", form=form, user=user)
