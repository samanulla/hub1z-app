"""Company-admin portal routes."""
from __future__ import annotations

from flask import Blueprint, render_template, redirect, url_for, flash, abort, request, g, current_app
from flask_login import current_user, login_user

from ...extensions import db
from ...models import (
    User, UserRole, PricingPlan, Subscription, SubscriptionStatus,
    SeatAllocation, AllocationStatus, Invoice, SeatBooking, RoomBooking,
)
from ...utils.decorators import company_admin_required
from .forms import InviteEmployeeForm, AcceptInviteForm
from ...services import mail_service, tier_limits

INVITE_TTL_SECONDS = 60 * 60 * 24 * 7  # 7 days

company_bp = Blueprint("company", __name__, template_folder="../../templates")


def _own_company():
    if not current_user.company_id:
        abort(403)
    return current_user.company


# --------------------------------------------------------------- dashboard --

@company_bp.route("/")
@company_admin_required
def dashboard():
    c = _own_company()
    stats = {
        "employees": User.query.filter_by(company_id=c.id, role=UserRole.EMPLOYEE).count(),
        "allocations": SeatAllocation.query.filter_by(company_id=c.id, status=AllocationStatus.ACTIVE).count(),
        "active_subs": Subscription.query.filter_by(company_id=c.id, status=SubscriptionStatus.ACTIVE).count(),
        "meeting_credits": sum(s.meeting_credits_balance for s in
                               Subscription.query.filter_by(company_id=c.id, status=SubscriptionStatus.ACTIVE).all()),
        "open_invoices": Invoice.query.filter(Invoice.company_id == c.id,
                                              Invoice.status.in_(["issued", "partial", "overdue"])).count(),
    }
    return render_template("company/dashboard.html", company=c, stats=stats)


# --------------------------------------------------------------- employees --

@company_bp.route("/employees")
@company_admin_required
def employees():
    c = _own_company()
    people = User.query.filter_by(company_id=c.id).order_by(User.full_name).all()
    return render_template("company/employees.html", company=c, people=people)


@company_bp.route("/employees/new", methods=["GET", "POST"])
@company_admin_required
def employee_new():
    c = _own_company()
    form = InviteEmployeeForm()
    if form.validate_on_submit():
        emp_count = User.query.filter_by(company_id=c.id, role=UserRole.EMPLOYEE).count()
        if emp_count >= c.max_employees:
            flash(f"Employee limit ({c.max_employees}) reached.", "warning")
            return redirect(url_for("company.employees"))
        ok, msg = tier_limits.check_limit(getattr(g, "tenant", None), "person")
        if not ok:
            flash(msg, "warning")
            return redirect(url_for("company.employees"))
        email = form.email.data.lower().strip()
        if User.query.filter_by(email=email).first():
            flash("That email is already registered under this workspace.", "warning")
            return redirect(url_for("company.employees"))
        u = User(
            tenant_id=getattr(g, "tenant_id", None),
            email=email,
            full_name=form.full_name.data.strip(),
            phone=form.phone.data,
            role=UserRole.EMPLOYEE,
            company_id=c.id,
            is_active=False,   # activated when invite is accepted
        )
        # Random placeholder — invitee will replace via accept-invite link.
        u.set_password(current_app.config["SECRET_KEY"] + email)
        db.session.add(u); db.session.commit()

        token = mail_service.make_token(u.id, "employee-invite")
        accept_url = url_for("company.accept_invite", token=token, _external=True)
        mail_service.send(
            subject=f"You're invited to {c.name} on {current_app.config['APP_NAME']}",
            recipient=u.email,
            template="employee_invite",
            user=u, company=c, accept_url=accept_url,
            ttl_days=INVITE_TTL_SECONDS // 86400,
        )
        flash(f"Invitation sent to {u.email}.", "success")
        return redirect(url_for("company.employees"))
    return render_template("company/employee_form.html", form=form, company=c)


@company_bp.route("/invite/<token>", methods=["GET", "POST"])
def accept_invite(token: str):
    uid = mail_service.read_token(token, "employee-invite", INVITE_TTL_SECONDS)
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

    form = AcceptInviteForm()
    if form.validate_on_submit():
        user.set_password(form.password.data)
        user.is_active = True
        user.email_verified = True
        db.session.commit()
        login_user(user)
        flash(f"Welcome to {user.company.name}!", "success")
        return redirect(url_for("member.dashboard"))
    return render_template("company/accept_invite.html", form=form, user=user)


@company_bp.route("/employees/<int:user_id>/deactivate", methods=["POST"])
@company_admin_required
def employee_deactivate(user_id: int):
    c = _own_company()
    u = User.query.filter_by(id=user_id, company_id=c.id).first_or_404()
    u.is_active = False
    db.session.commit()
    flash(f"{u.full_name} deactivated.", "info")
    return redirect(url_for("company.employees"))


# --------------------------------------------------------------- plans --

@company_bp.route("/plans")
@company_admin_required
def plans():
    """Read-only: what the tenant offers. Subscribing is tenant-controlled
    (/admin/companies/<id>/subscriptions/new) — it's tied to real seat
    inventory the tenant manages, not a company self-checkout."""
    c = _own_company()
    return render_template("company/plans.html", company=c,
                           plans=PricingPlan.query.filter_by(is_active=True).all())


@company_bp.route("/subscriptions")
@company_admin_required
def subscriptions():
    c = _own_company()
    subs = Subscription.query.filter_by(company_id=c.id).order_by(Subscription.created_at.desc()).all()
    return render_template("company/subscriptions.html", company=c, subs=subs)


# ------------------------------------------------------------ allocations --

@company_bp.route("/allocations")
@company_admin_required
def allocations():
    c = _own_company()
    allocs = (SeatAllocation.query.filter_by(company_id=c.id, status=AllocationStatus.ACTIVE)
              .order_by(SeatAllocation.start_date.desc()).all())
    return render_template("company/allocations.html", company=c, allocations=allocs)


# --------------------------------------------------------------- invoices --

@company_bp.route("/invoices")
@company_admin_required
def invoices():
    c = _own_company()
    invs = Invoice.query.filter_by(company_id=c.id).order_by(Invoice.issued_at.desc().nullslast()).all()
    return render_template("company/invoices.html", company=c, invoices=invs)


# --------------------------------------------------------------- bookings --

@company_bp.route("/bookings")
@company_admin_required
def bookings():
    c = _own_company()
    seat_bookings = (SeatBooking.query.filter_by(company_id=c.id)
                     .order_by(SeatBooking.start_at.desc()).limit(50).all())
    room_bookings = (RoomBooking.query.filter_by(company_id=c.id)
                     .order_by(RoomBooking.start_at.desc()).limit(50).all())
    return render_template("company/bookings.html", company=c,
                           seat_bookings=seat_bookings, room_bookings=room_bookings)
