"""Company-admin portal routes."""
from __future__ import annotations

from datetime import date

from flask import Blueprint, render_template, redirect, url_for, flash, abort, request, g, current_app
from flask_login import current_user, login_user

from ...extensions import db
from ...models import (
    User, UserRole, PricingPlan, Subscription, SubscriptionStatus,
    SubscriptionChangeRequest, SubscriptionRequestStatus,
    Seat, SeatType, SeatAllocation, AllocationStatus, Invoice, InvoiceStatus, PaymentSubmission,
    PaymentSubmissionStatus, SeatBooking, RoomBooking,
)
from ...utils.decorators import company_admin_required
from .forms import (
    InviteEmployeeForm, AcceptInviteForm, CompanyProfileForm,
    SubscriptionRequestForm, EmployeeAllocationForm, CompanySeatAllocationForm, PaymentSubmissionForm,
)
from ...services import mail_service, tier_limits

INVITE_TTL_SECONDS = 60 * 60 * 24 * 7  # 7 days

company_bp = Blueprint("company", __name__, template_folder="../../templates")


def _own_company():
    if not current_user.company_id:
        abort(403)
    return current_user.company


def _company_subscription_capacity(company):
    return sum(subscription.quantity for subscription in Subscription.query.filter_by(
        company_id=company.id, status=SubscriptionStatus.ACTIVE,
    ).all())


def _employee_seat_choices(company, employee_id=None):
    query = SeatAllocation.query.filter_by(company_id=company.id, status=AllocationStatus.ACTIVE)
    if employee_id is None:
        query = query.filter(SeatAllocation.user_id.is_(None))
    else:
        query = query.filter((SeatAllocation.user_id.is_(None)) | (SeatAllocation.user_id == employee_id))
    return [(0, "— no assigned seat —")] + [
        (allocation.id, f"{allocation.seat.location.name} / {allocation.seat.code}")
        for allocation in query.order_by(SeatAllocation.created_at.desc()).all()
    ]


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
    pending_requests = SubscriptionChangeRequest.query.filter_by(
        company_id=c.id, status=SubscriptionRequestStatus.PENDING,
    ).count()
    return render_template("company/dashboard.html", company=c, stats=stats,
                           pending_requests=pending_requests)


@company_bp.route("/profile", methods=["GET", "POST"])
@company_admin_required
def profile():
    c = _own_company()
    form = CompanyProfileForm(obj=c)
    if form.validate_on_submit():
        form.populate_obj(c)
        db.session.commit()
        flash("Company profile updated.", "success")
        return redirect(url_for("company.profile"))
    return render_template("company/profile.html", company=c, form=form)


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
    form.seat_allocation_id.choices = _employee_seat_choices(c)
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
        db.session.add(u)
        db.session.flush()
        if form.seat_allocation_id.data:
            allocation = SeatAllocation.query.filter_by(
                id=form.seat_allocation_id.data, company_id=c.id,
                status=AllocationStatus.ACTIVE, user_id=None,
            ).first()
            if allocation is not None:
                allocation.user_id = u.id
        db.session.commit()

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
    return render_template("company/employee_form.html", form=form, company=c, editing=False)


@company_bp.route("/employees/<int:user_id>/edit", methods=["GET", "POST"])
@company_admin_required
def employee_edit(user_id: int):
    c = _own_company()
    employee = User.query.filter_by(id=user_id, company_id=c.id, role=UserRole.EMPLOYEE).first_or_404()
    form = InviteEmployeeForm(obj=employee)
    form.seat_allocation_id.choices = _employee_seat_choices(c, employee.id)
    current_allocation = SeatAllocation.query.filter_by(
        company_id=c.id, user_id=employee.id, status=AllocationStatus.ACTIVE,
    ).first()
    if not form.is_submitted():
        form.seat_allocation_id.data = current_allocation.id if current_allocation else 0
    if form.validate_on_submit():
        email = form.email.data.lower().strip()
        duplicate = User.query.filter(User.tenant_id == c.tenant_id, User.email == email,
                                      User.id != employee.id).first()
        if duplicate:
            flash("That email is already registered under this workspace.", "warning")
        else:
            employee.full_name = form.full_name.data.strip()
            employee.email = email
            employee.phone = form.phone.data
            if current_allocation and current_allocation.id != form.seat_allocation_id.data:
                current_allocation.user_id = None
            if form.seat_allocation_id.data:
                allocation = SeatAllocation.query.filter_by(
                    id=form.seat_allocation_id.data, company_id=c.id,
                    status=AllocationStatus.ACTIVE,
                ).filter((SeatAllocation.user_id.is_(None)) | (SeatAllocation.user_id == employee.id)).first()
                if allocation is not None:
                    allocation.user_id = employee.id
            db.session.commit()
            flash("Employee updated.", "success")
            return redirect(url_for("company.employees"))
    return render_template("company/employee_form.html", form=form, company=c, editing=True)


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

@company_bp.route("/plans", methods=["GET", "POST"])
@company_admin_required
def plans():
    c = _own_company()
    plans = PricingPlan.query.filter_by(is_active=True).order_by(PricingPlan.base_price).all()
    active_subs = Subscription.query.filter_by(
        company_id=c.id, status=SubscriptionStatus.ACTIVE,
    ).all()
    form = SubscriptionRequestForm()
    form.plan_id.choices = [(plan.id, plan.name) for plan in plans]
    if form.validate_on_submit():
        if SubscriptionChangeRequest.query.filter_by(
            company_id=c.id, status=SubscriptionRequestStatus.PENDING,
        ).first():
            flash("You already have a subscription request awaiting review.", "warning")
        else:
            change = SubscriptionChangeRequest(
                tenant_id=getattr(g, "tenant_id", None),
                company_id=c.id,
                subscription_id=active_subs[0].id if active_subs else None,
                requested_plan_id=form.plan_id.data,
                requested_quantity=form.quantity.data,
                company_message=(form.company_message.data or "").strip() or None,
                requested_by_id=current_user.id,
            )
            db.session.add(change)
            db.session.commit()
            flash("Your subscription request was sent to the workspace operator.", "success")
            return redirect(url_for("company.plans"))
    return render_template("company/plans.html", company=c, plans=plans, form=form,
                           active_plan_ids={subscription.plan_id for subscription in active_subs})


@company_bp.route("/subscriptions")
@company_admin_required
def subscriptions():
    c = _own_company()
    subs = Subscription.query.filter_by(company_id=c.id).order_by(Subscription.created_at.desc()).all()
    requests = (SubscriptionChangeRequest.query.filter_by(company_id=c.id)
                .order_by(SubscriptionChangeRequest.created_at.desc()).all())
    return render_template("company/subscriptions.html", company=c, subs=subs, requests=requests)


# ------------------------------------------------------------ allocations --

@company_bp.route("/allocations")
@company_admin_required
def allocations():
    c = _own_company()
    allocs = (SeatAllocation.query.filter_by(company_id=c.id, status=AllocationStatus.ACTIVE)
              .order_by(SeatAllocation.start_date.desc()).all())
    employees = (User.query.filter_by(company_id=c.id, role=UserRole.EMPLOYEE, is_active=True)
                 .order_by(User.full_name).all())
    form = EmployeeAllocationForm()
    form.employee_id.choices = [(employee.id, employee.full_name) for employee in employees]
    capacity = _company_subscription_capacity(c)
    assigned = sum(1 for allocation in allocs if allocation.user_id)
    create_form = CompanySeatAllocationForm()
    create_form.seat_id.choices = [(seat.id, f"{seat.location.name} / {seat.code} ({seat.seat_type.value.replace('_', ' ')})")
                                   for seat in Seat.query.filter(
                                       Seat.is_active.is_(True),
                                       Seat.seat_type.in_([SeatType.DEDICATED_DESK, SeatType.PRIVATE_OFFICE]),
                                       ~Seat.allocations.any(SeatAllocation.status == AllocationStatus.ACTIVE),
                                   ).order_by(Seat.code).all()]
    create_form.employee_id.choices = [(0, "— leave unassigned —")] + [
        (employee.id, employee.full_name) for employee in employees
    ]
    return render_template("company/allocations.html", company=c, allocations=allocs,
                           allocation_form=form, create_form=create_form, capacity=capacity, assigned=assigned)


@company_bp.route("/allocations/new", methods=["POST"])
@company_admin_required
def allocation_new():
    c = _own_company()
    form = CompanySeatAllocationForm()
    form.seat_id.choices = [(seat.id, seat.code) for seat in Seat.query.filter(
        Seat.is_active.is_(True),
        Seat.seat_type.in_([SeatType.DEDICATED_DESK, SeatType.PRIVATE_OFFICE]),
        ~Seat.allocations.any(SeatAllocation.status == AllocationStatus.ACTIVE),
    ).all()]
    employees = User.query.filter_by(company_id=c.id, role=UserRole.EMPLOYEE, is_active=True).all()
    form.employee_id.choices = [(0, "— leave unassigned —")] + [
        (employee.id, employee.full_name) for employee in employees
    ]
    active_allocations = SeatAllocation.query.filter_by(company_id=c.id, status=AllocationStatus.ACTIVE).count()
    if active_allocations >= _company_subscription_capacity(c):
        flash("Your active subscription does not have another seat available to allocate.", "warning")
    elif form.validate_on_submit():
        seat = Seat.query.filter(
            Seat.id == form.seat_id.data,
            Seat.is_active.is_(True),
            Seat.seat_type.in_([SeatType.DEDICATED_DESK, SeatType.PRIVATE_OFFICE]),
            ~Seat.allocations.any(SeatAllocation.status == AllocationStatus.ACTIVE),
        ).first()
        employee = User.query.filter_by(
            id=form.employee_id.data, company_id=c.id, role=UserRole.EMPLOYEE, is_active=True,
        ).first() if form.employee_id.data else None
        if seat is None:
            flash("That seat is no longer available.", "warning")
        else:
            db.session.add(SeatAllocation(
                seat_id=seat.id,
                company_id=c.id,
                user_id=employee.id if employee else None,
                status=AllocationStatus.ACTIVE,
                start_date=date.today(),
            ))
            db.session.commit()
            flash("Seat allocated to your company.", "success")
    else:
        flash("Pick a valid available seat.", "warning")
    return redirect(url_for("company.allocations"))


@company_bp.route("/allocations/<int:allocation_id>/assign", methods=["POST"])
@company_admin_required
def allocation_assign(allocation_id: int):
    c = _own_company()
    allocation = SeatAllocation.query.filter_by(
        id=allocation_id, company_id=c.id, status=AllocationStatus.ACTIVE, user_id=None,
    ).first_or_404()
    form = EmployeeAllocationForm()
    form.employee_id.choices = [
        (employee.id, employee.full_name)
        for employee in User.query.filter_by(company_id=c.id, role=UserRole.EMPLOYEE, is_active=True)
        .order_by(User.full_name).all()
    ]
    capacity = _company_subscription_capacity(c)
    assigned = SeatAllocation.query.filter_by(
        company_id=c.id, status=AllocationStatus.ACTIVE,
    ).filter(SeatAllocation.user_id.isnot(None)).count()
    if assigned >= capacity:
        flash("All seats included in your active subscription are already assigned.", "warning")
    elif form.validate_on_submit():
        allocation.user_id = form.employee_id.data
        db.session.commit()
        flash("Seat assigned to employee.", "success")
    else:
        flash("Pick a valid active employee.", "warning")
    return redirect(url_for("company.allocations"))


@company_bp.route("/allocations/<int:allocation_id>/release", methods=["POST"])
@company_admin_required
def allocation_release(allocation_id: int):
    c = _own_company()
    allocation = SeatAllocation.query.filter_by(
        id=allocation_id, company_id=c.id, status=AllocationStatus.ACTIVE,
    ).filter(SeatAllocation.user_id.isnot(None)).first_or_404()
    allocation.user_id = None
    db.session.commit()
    flash("Seat released and available for another employee.", "info")
    return redirect(url_for("company.allocations"))


# --------------------------------------------------------------- invoices --

@company_bp.route("/invoices")
@company_admin_required
def invoices():
    c = _own_company()
    invs = (Invoice.query.filter(Invoice.company_id == c.id,
                                 Invoice.status != InvoiceStatus.DRAFT)
            .order_by(Invoice.issued_at.desc().nullslast()).all())
    submissions = (PaymentSubmission.query.filter_by(company_id=c.id)
                   .order_by(PaymentSubmission.created_at.desc()).all())
    form = PaymentSubmissionForm()
    form.paid_on.data = date.today()
    return render_template("company/invoices.html", company=c, invoices=invs,
                           submissions=submissions, payment_form=form)


@company_bp.route("/invoices/<int:invoice_id>/payments", methods=["POST"])
@company_admin_required
def payment_submission_new(invoice_id: int):
    c = _own_company()
    invoice = Invoice.query.filter(
        Invoice.id == invoice_id, Invoice.company_id == c.id,
        Invoice.status != InvoiceStatus.DRAFT,
    ).first_or_404()
    form = PaymentSubmissionForm()
    if form.validate_on_submit():
        if form.amount.data > invoice.balance_due:
            flash("Reported amount cannot exceed the invoice balance.", "warning")
        else:
            db.session.add(PaymentSubmission(
                tenant_id=getattr(g, "tenant_id", None),
                invoice_id=invoice.id,
                company_id=c.id,
                amount=form.amount.data,
                paid_on=form.paid_on.data,
                reference=(form.reference.data or "").strip() or None,
                notes=(form.notes.data or "").strip() or None,
            ))
            db.session.commit()
            flash("Payment reported. It will appear as paid once the workspace operator confirms it.", "success")
    else:
        flash("Enter a valid payment amount and date.", "warning")
    return redirect(url_for("company.invoices"))


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
