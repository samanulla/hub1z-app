"""Authentication routes."""
from __future__ import annotations

from datetime import datetime, timedelta
from urllib.parse import urlparse

from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app, g
from flask_login import login_user, logout_user, login_required, current_user

from ...extensions import db, limiter
from ...models import User, UserRole, Company, CompanyStatus, Tenant, TenantStatus
from ...services import mail_service, tier_limits
from .forms import (
    LoginForm, RegisterIndividualForm, RegisterCompanyForm, RegisterTenantForm,
    ForgotPasswordForm, ResetPasswordForm, ChangePasswordForm, TenantPickerForm,
    TotpVerifyForm, TotpEnableForm,
)


def _safe_next(target: str | None) -> str | None:
    """Only return the next URL if it's a same-host relative path and not the logout endpoint."""
    if not target:
        return None
    parsed = urlparse(target)
    if parsed.netloc or parsed.scheme:
        return None
    path = parsed.path or ""
    if not path.startswith("/"):
        return None
    if path.startswith("/auth/logout"):
        return None
    return target


auth_bp = Blueprint("auth", __name__, template_folder="../../templates")


def _notify_new_company_signup(company, admin_user):
    """Email the tenant's super admins that a new company self-registered."""
    from ...models import Tenant
    tid = getattr(g, "tenant_id", None)
    if tid is None:
        return
    admins = User.query.filter_by(role=UserRole.SUPER_ADMIN, tenant_id=tid) \
                       .execution_options(skip_tenant_filter=True).all()
    for a in admins:
        try:
            mail_service.send(
                subject=f"[{current_app.config['APP_NAME']}] New company signup: {company.name}",
                recipient=a.email,
                template="company_signup_notify",
                admin=a, company=company, applicant=admin_user,
            )
        except Exception as e:
            current_app.logger.warning("company-signup notify failed: %s", e)


@auth_bp.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute; 30 per hour", methods=["POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("auth.post_login_redirect"))

    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data.lower().strip()).first()
        if user and user.check_password(form.password.data) and user.is_active:
            if user.tenant_id and user.tenant and user.tenant.is_trial_expired:
                flash(f"This workspace's trial ended on "
                     f"{user.tenant.trial_ends_at.strftime('%d-%b-%Y')}. "
                     f"Contact {current_app.config['APP_NAME']} to continue.", "warning")
                return render_template("auth/login.html", form=form)
            next_url = _safe_next(request.args.get("next"))
            if user.two_factor_enabled:
                from flask import session as flask_session
                flask_session["pending_2fa_user_id"] = user.id
                flask_session["pending_2fa_remember"] = form.remember.data
                flask_session["pending_2fa_next"] = next_url
                return redirect(url_for("auth.two_factor_login"))
            login_user(user, remember=form.remember.data)
            return redirect(next_url or url_for("auth.post_login_redirect"))
        flash("Invalid email or password.", "danger")
    return render_template("auth/login.html", form=form)


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("You have been signed out.", "info")
    return redirect(url_for("auth.login"))


@auth_bp.route("/register", methods=["GET", "POST"])
def register_individual():
    if current_user.is_authenticated:
        return redirect(url_for("auth.post_login_redirect"))

    from flask import g
    tenant = getattr(g, "tenant", None)

    form = RegisterIndividualForm()
    if form.validate_on_submit():
        email = form.email.data.lower().strip()
        ok, tier_msg = tier_limits.check_limit(tenant, "person")
        if User.query.filter_by(email=email).first():
            flash("An account with that email already exists.", "warning")
        elif not ok:
            flash(tier_msg, "warning")
        else:
            user = User(
                tenant_id=tenant.id if tenant else None,
                email=email,
                full_name=form.full_name.data.strip(),
                phone=form.phone.data,
                role=UserRole.INDIVIDUAL,
            )
            user.set_password(form.password.data)
            db.session.add(user)
            db.session.commit()
            login_user(user)
            flash(f"Welcome to {tenant.name if tenant else current_app.config['APP_NAME']}!", "success")
            return redirect(url_for("member.dashboard"))
    return render_template("auth/register_individual.html", form=form)


@auth_bp.route("/register/company", methods=["GET", "POST"])
def register_company():
    if current_user.is_authenticated:
        return redirect(url_for("auth.post_login_redirect"))

    from flask import g
    tenant = getattr(g, "tenant", None)

    form = RegisterCompanyForm()
    if form.validate_on_submit():
        admin_email = form.admin_email.data.lower().strip()
        if User.query.filter_by(email=admin_email).first():
            flash("An account with that admin email already exists.", "warning")
            return render_template("auth/register_company.html", form=form)
        if Company.query.filter_by(name=form.company_name.data.strip()).first():
            flash("A company with that name already exists.", "warning")
            return render_template("auth/register_company.html", form=form)
        ok, tier_msg = tier_limits.check_limit(tenant, "person")
        if not ok:
            flash(tier_msg, "warning")
            return render_template("auth/register_company.html", form=form)

        company = Company(
            tenant_id=tenant.id if tenant else None,
            name=form.company_name.data.strip(),
            billing_email=form.billing_email.data.lower().strip(),
            status=CompanyStatus.PROSPECT,
        )
        db.session.add(company)
        db.session.flush()

        admin = User(
            tenant_id=tenant.id if tenant else None,
            email=admin_email,
            full_name=form.admin_full_name.data.strip(),
            role=UserRole.COMPANY_ADMIN,
            company_id=company.id,
        )
        admin.set_password(form.password.data)
        db.session.add(admin)
        db.session.commit()

        # Notify tenant super admins so they can approve.
        _notify_new_company_signup(company, admin)

        login_user(admin)
        flash("Your company account is created. The workspace admin will contact you to finalise onboarding.", "success")
        return redirect(url_for("company.dashboard"))
    return render_template("auth/register_company.html", form=form)


@auth_bp.route("/register/tenant", methods=["GET", "POST"])
def register_tenant():
    """Self-serve: a coworking business signs itself up directly, no
    platform staff involved. Lands as a time-boxed TRIAL so they can try the
    platform; a Platform Super Admin/Manager still has to Approve it
    (/platform/tenants/<id>/approve) to lift the trial deadline."""
    if current_user.is_authenticated:
        return redirect(url_for("auth.post_login_redirect"))

    form = RegisterTenantForm()
    if form.validate_on_submit():
        slug = form.slug.data.lower().strip()
        admin_email = form.admin_email.data.lower().strip()

        if Tenant.query.execution_options(skip_tenant_filter=True).filter_by(slug=slug).first():
            flash("That URL slug is already taken.", "warning")
            return render_template("auth/register_tenant.html", form=form)
        if User.query.execution_options(skip_tenant_filter=True).filter_by(email=admin_email).first():
            flash("An account with that email already exists.", "warning")
            return render_template("auth/register_tenant.html", form=form)

        base = current_app.config.get("PLATFORM_BASE_DOMAIN", "hub1z.com")
        trial_days = current_app.config.get("TENANT_TRIAL_DAYS", 14)
        t = Tenant(
            slug=slug, name=form.business_name.data.strip(),
            primary_domain=f"{slug}.{base}", status=TenantStatus.TRIAL,
            trial_ends_at=datetime.utcnow() + timedelta(days=trial_days),
        )
        db.session.add(t)
        db.session.flush()

        admin = User(
            tenant_id=t.id, email=admin_email,
            full_name=form.admin_full_name.data.strip(),
            role=UserRole.SUPER_ADMIN, is_active=True, email_verified=False,
        )
        admin.set_password(form.password.data)
        db.session.add(admin)
        db.session.commit()

        login_user(admin)
        flash(f"Welcome! Your {trial_days}-day free trial has started — "
             f"explore everything, and we'll be in touch to get you fully set up.", "success")
        return redirect(url_for("admin.dashboard"))
    return render_template("auth/register_tenant.html", form=form)


@auth_bp.route("/post-login")
@login_required
def post_login_redirect():
    """Route logged-in users to their home based on role."""
    role = current_user.role
    if role in (UserRole.PLATFORM_OWNER, UserRole.PLATFORM_MANAGER):
        return redirect(url_for("platform.dashboard"))
    if role in (UserRole.SUPER_ADMIN, UserRole.MANAGER, UserRole.LOCATION_MANAGER):
        return redirect(url_for("admin.dashboard"))
    if role == UserRole.COMPANY_ADMIN:
        return redirect(url_for("company.dashboard"))
    return redirect(url_for("member.dashboard"))


PASSWORD_RESET_TTL_SECONDS = 60 * 60 * 2  # 2 hours


@auth_bp.route("/forgot-password", methods=["GET", "POST"])
@limiter.limit("5 per minute; 20 per hour", methods=["POST"])
def forgot_password():
    form = ForgotPasswordForm()
    if form.validate_on_submit():
        email = form.email.data.lower().strip()
        user = User.query.filter_by(email=email).first()
        if user and user.is_active:
            token = mail_service.make_token(user.id, "password-reset")
            reset_url = url_for("auth.reset_password", token=token, _external=True)
            mail_service.send(
                subject=f"Reset your {current_app.config['APP_NAME']} password",
                recipient=user.email,
                template="password_reset",
                user=user,
                reset_url=reset_url,
                ttl_hours=PASSWORD_RESET_TTL_SECONDS // 3600,
            )
        flash("If that email is registered here, a reset link has been sent. "
              "Check your inbox (and spam folder).", "info")
        return redirect(url_for("auth.login"))
    return render_template("auth/forgot_password.html", form=form)


@auth_bp.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token: str):
    user_id = mail_service.read_token(token, "password-reset", PASSWORD_RESET_TTL_SECONDS)
    if user_id is None:
        flash("This password-reset link is invalid or has expired. Request a new one.", "danger")
        return redirect(url_for("auth.forgot_password"))
    user = User.query.filter_by(id=int(user_id)) \
                     .execution_options(skip_tenant_filter=True).first()
    if user is None or not user.is_active:
        flash("Account not found.", "danger")
        return redirect(url_for("auth.login"))

    form = ResetPasswordForm()
    if form.validate_on_submit():
        user.set_password(form.password.data)
        db.session.commit()
        flash("Password updated. Please sign in with your new password.", "success")
        return redirect(url_for("auth.login"))
    return render_template("auth/reset_password.html", form=form)


@auth_bp.route("/change-password", methods=["GET", "POST"])
@login_required
def change_password():
    form = ChangePasswordForm()
    if form.validate_on_submit():
        if not current_user.check_password(form.current_password.data):
            flash("Current password is incorrect.", "danger")
        else:
            current_user.set_password(form.password.data)
            db.session.commit()
            flash("Password changed.", "success")
            return redirect(url_for("auth.post_login_redirect"))
    return render_template("auth/change_password.html", form=form)


@auth_bp.route("/pick-workspace", methods=["GET", "POST"])
def pick_workspace():
    """At the apex domain, let a user type their workspace slug and get redirected."""
    form = TenantPickerForm()
    if form.validate_on_submit():
        slug = form.workspace.data.lower().strip()
        tenant = Tenant.query.filter_by(slug=slug) \
                             .execution_options(skip_tenant_filter=True).first()
        if tenant is None:
            flash(f"No workspace found for '{slug}'. Check the spelling.", "warning")
        else:
            base = current_app.config.get("PLATFORM_BASE_DOMAIN", "hub1z.com")
            host = tenant.primary_domain or f"{tenant.slug}.{base}"
            scheme = "https" if not current_app.debug else request.scheme
            return redirect(f"{scheme}://{host}/auth/login")
    return render_template("auth/pick_workspace.html", form=form)


# ------- two-factor auth (TOTP) -------

def _totp_issuer_name() -> str:
    tenant = getattr(g, "tenant", None)
    return (tenant.name if tenant else current_app.config.get("APP_NAME", "hub1z"))


@auth_bp.route("/2fa/login", methods=["GET", "POST"])
def two_factor_login():
    from flask import session as flask_session
    import pyotp
    uid = flask_session.get("pending_2fa_user_id")
    if uid is None:
        return redirect(url_for("auth.login"))
    form = TotpVerifyForm()
    if form.validate_on_submit():
        user = User.query.filter_by(id=int(uid)) \
                         .execution_options(skip_tenant_filter=True).first()
        if user is None or not user.two_factor_secret:
            flash("Please sign in again.", "warning")
            return redirect(url_for("auth.login"))
        totp = pyotp.TOTP(user.two_factor_secret)
        if totp.verify(form.code.data.strip(), valid_window=1):
            remember = flask_session.pop("pending_2fa_remember", False)
            next_url = flask_session.pop("pending_2fa_next", None)
            flask_session.pop("pending_2fa_user_id", None)
            login_user(user, remember=remember)
            return redirect(next_url or url_for("auth.post_login_redirect"))
        flash("Invalid code. Try again.", "danger")
    return render_template("auth/two_factor_login.html", form=form)


@auth_bp.route("/2fa/setup", methods=["GET", "POST"])
@login_required
def two_factor_setup():
    import pyotp
    if current_user.two_factor_enabled:
        flash("Two-factor is already enabled. Disable it first to reset.", "info")
        return redirect(url_for("auth.two_factor_status"))
    if not current_user.two_factor_secret:
        current_user.two_factor_secret = pyotp.random_base32()
        db.session.commit()
    otpauth_url = pyotp.TOTP(current_user.two_factor_secret).provisioning_uri(
        name=current_user.email, issuer_name=_totp_issuer_name()
    )
    form = TotpEnableForm()
    if form.validate_on_submit():
        totp = pyotp.TOTP(current_user.two_factor_secret)
        if totp.verify(form.code.data.strip(), valid_window=1):
            current_user.two_factor_enabled = True
            db.session.commit()
            flash("Two-factor authentication is now on.", "success")
            return redirect(url_for("auth.two_factor_status"))
        flash("Invalid code — try again.", "danger")
    return render_template("auth/two_factor_setup.html",
                           form=form, otpauth_url=otpauth_url)


@auth_bp.route("/2fa/qr.png")
@login_required
def two_factor_qr():
    import pyotp, qrcode
    from io import BytesIO
    from flask import send_file
    if not current_user.two_factor_secret:
        return ("", 404)
    url = pyotp.TOTP(current_user.two_factor_secret).provisioning_uri(
        name=current_user.email, issuer_name=_totp_issuer_name()
    )
    img = qrcode.make(url)
    buf = BytesIO(); img.save(buf, format="PNG"); buf.seek(0)
    return send_file(buf, mimetype="image/png")


@auth_bp.route("/2fa", methods=["GET"])
@login_required
def two_factor_status():
    return render_template("auth/two_factor_status.html")


@auth_bp.route("/2fa/disable", methods=["POST"])
@login_required
def two_factor_disable():
    current_user.two_factor_enabled = False
    current_user.two_factor_secret = None
    db.session.commit()
    flash("Two-factor authentication disabled.", "info")
    return redirect(url_for("auth.two_factor_status"))
