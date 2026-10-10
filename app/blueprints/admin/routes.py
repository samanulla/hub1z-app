"""Admin (Super Admin + Location Manager) routes."""
from __future__ import annotations

from datetime import date, datetime
import re

from flask import Blueprint, render_template, redirect, url_for, flash, request, abort, g, session
from flask_login import current_user
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError

from ...extensions import db
from ...models import (
    User, UserRole, Location, Floor, Seat, SeatType, ConferenceRoom,
    Company, CompanyStatus, PricingPlan, PlanStatus, Subscription, SubscriptionStatus,
    SeatAllocation, AllocationStatus, SeatBooking, RoomBooking, BookingStatus,
    SubscriptionChangeRequest, SubscriptionRequestStatus,
    Document, DocumentKind, CompanyDocument, Invoice, DayPass, DayPassStatus, RoomCategory,
)
from ...services.storage import storage_service
from ...services import tier_limits
from ...utils.decorators import admin_required, super_admin_required, manager_or_super_required
from .forms import (
    LocationForm, FloorForm, SeatForm, BulkSeatForm, BulkSeatEditForm, RoomForm, PricingPlanForm,
    CompanyForm, AllocationForm, DocumentUploadForm,
)

admin_bp = Blueprint("admin", __name__, template_folder="../../templates")


def _room_category_choices(operator_id: int) -> list[tuple[int, str]]:
    cats = (RoomCategory.query.filter_by(operator_id=operator_id, is_active=True)
            .order_by(RoomCategory.credits_per_slot, RoomCategory.name).all())
    return [(0, "— none (1 credit, room rate) —")] + [
        (c.id, f"{c.name} · {c.credits_per_slot} cr / 30 min") for c in cats]


# ------------------------------------------------------------ dashboard --

@admin_bp.route("/")
@admin_required
def dashboard():
    from ...services.marketplace_partner import is_marketplace_partner
    if is_marketplace_partner(getattr(g, "operator", None)):
        return redirect(url_for("admin.marketplace"))
    # Seat/ConferenceRoom/SeatBooking/RoomBooking have no operator_id of their
    # own (scoped only via Location), so the ambient auto-scoping listener
    # doesn't filter them — these joins scope them explicitly.
    stats = {
        "locations": Location.query.count(),
        "seats": Seat.query.join(Location).count(),
        "rooms": ConferenceRoom.query.join(Location).count(),
        "companies": Company.query.count(),
        "members": User.query.filter(User.role.in_([UserRole.EMPLOYEE, UserRole.INDIVIDUAL])).count(),
        "active_subs": Subscription.query.filter_by(status=SubscriptionStatus.ACTIVE).count(),
        "today_seat_bookings": SeatBooking.query.join(Seat).join(Location).filter(
            func.date(SeatBooking.start_at) == date.today()).count(),
        "today_room_bookings": RoomBooking.query.join(ConferenceRoom).join(Location).filter(
            func.date(RoomBooking.start_at) == date.today()).count(),
    }
    recent_companies = Company.query.order_by(Company.created_at.desc()).limit(5).all()
    recent_bookings = (RoomBooking.query
                       .order_by(RoomBooking.created_at.desc()).limit(10).all())
    from ...services.alerts import operator_alerts
    from ...services import onboarding
    setup_steps = onboarding.steps(stats, current_user.is_super_admin) if getattr(g, "operator_id", None) else []
    setup_current = onboarding.current(setup_steps)
    guide = setup_current if setup_current and session.get("onboarding_dismissed") != setup_current["key"] else None
    return render_template("admin/dashboard.html",
                           stats=stats,
                           setup_steps=setup_steps, setup_guide=guide, setup_active=setup_current is not None,
                           alerts=operator_alerts(g.operator_id) if getattr(g, "operator_id", None) else [],
                           recent_companies=recent_companies,
                           recent_bookings=recent_bookings)


# ------------------------------------------------------------- locations --

@admin_bp.route("/onboarding/dismiss", methods=["POST"])
@admin_required
def onboarding_dismiss():
    session["onboarding_dismissed"] = request.form.get("step", "")[:30]
    return redirect(url_for("admin.dashboard"))


@admin_bp.route("/locations")
@admin_required
def locations_list():
    locations = Location.query.order_by(Location.name).all()
    return render_template("admin/locations/list.html", locations=locations)


@admin_bp.route("/locations/new", methods=["GET", "POST"])
@super_admin_required
def location_new():
    form = LocationForm()
    if form.validate_on_submit():
        ok, msg = tier_limits.check_limit(getattr(g, "operator", None), "location")
        if not ok:
            flash(msg, "warning")
            return render_template("admin/locations/form.html", form=form, title="New location")
        loc = Location(operator_id=getattr(g, "operator_id", None))
        form.populate_obj(loc)
        db.session.add(loc)
        if getattr(g, "operator", None) and g.operator.primary_location_id is None:
            db.session.flush()
            g.operator.primary_location_id = loc.id
        db.session.commit()
        flash("Location created.", "success")
        return redirect(url_for("admin.location_detail", location_id=loc.id))
    return render_template("admin/locations/form.html", form=form, title="New location")


@admin_bp.route("/locations/<int:location_id>", methods=["GET"])
@admin_required
def location_detail(location_id: int):
    loc = Location.query.get_or_404(location_id)
    return render_template("admin/locations/detail.html", location=loc)


@admin_bp.route("/locations/<int:location_id>/edit", methods=["GET", "POST"])
@super_admin_required
def location_edit(location_id: int):
    loc = Location.query.get_or_404(location_id)
    form = LocationForm(obj=loc)
    if form.validate_on_submit():
        form.populate_obj(loc)
        db.session.commit()
        flash("Location updated.", "success")
        return redirect(url_for("admin.location_detail", location_id=loc.id))
    return render_template("admin/locations/form.html", form=form, title="Edit location")


# --------------------------------------------------------------- floors --

@admin_bp.route("/locations/<int:location_id>/floors/new", methods=["GET", "POST"])
@admin_required
def floor_new(location_id: int):
    loc = Location.query.get_or_404(location_id)
    form = FloorForm()
    if form.validate_on_submit():
        floor = Floor(operator_id=loc.operator_id, location_id=loc.id,
                  level=form.level.data, name=form.name.data)
        db.session.add(floor)
        db.session.commit()
        flash("Floor added.", "success")
        return redirect(url_for("admin.location_detail", location_id=loc.id))
    return render_template("admin/floors/form.html", form=form, location=loc)


# ---------------------------------------------------------------- seats --

def _next_inventory_code(model, location_id, current_code):
    match = re.fullmatch(r"(.*?)(\d+)", current_code)
    if not match:
        return ""
    prefix, digits = match.groups()
    number = int(digits) + 1
    existing = {row.code for row in model.query.filter_by(location_id=location_id).with_entities(model.code).all()}
    candidate = f"{prefix}{number:0{len(digits)}d}"
    while candidate in existing:
        number += 1
        candidate = f"{prefix}{number:0{len(digits)}d}"
    return candidate if len(candidate) <= 30 else ""

@admin_bp.route("/locations/<int:location_id>/seats/bulk", methods=["GET", "POST"])
@admin_required
def seats_bulk_add(location_id: int):
    location = Location.query.get_or_404(location_id)
    form = BulkSeatForm()
    form.floor_id.choices = [(floor.id, f"L{floor.level} - {floor.name}") for floor in location.floors]
    if form.validate_on_submit():
        prefix = form.code_prefix.data.strip()
        codes = [f"{prefix}{number:0{form.number_digits.data}d}" for number in
                 range(form.start_number.data, form.start_number.data + form.count.data)]
        conflicts = Seat.query.filter(Seat.location_id == location.id, Seat.code.in_(codes)).all()
        if len(codes[-1]) > 30:
            form.code_prefix.errors.append("Generated seat codes must be 30 characters or fewer.")
        elif conflicts:
            form.code_prefix.errors.append("Already in use: " + ", ".join(seat.code for seat in conflicts) + ". No seats were added.")
        else:
            for code in codes:
                seat = Seat(operator_id=location.operator_id, location_id=location.id, code=code)
                for name in ("floor_id", "capacity", "hourly_rate", "daily_rate", "monthly_rate", "is_active", "notes"):
                    setattr(seat, name, form[name].data)
                seat.seat_type = SeatType(form.seat_type.data)
                db.session.add(seat)
            try:
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                form.code_prefix.errors.append("A seat code was added by another request. No seats were added; choose another range.")
            else:
                flash(f"{len(codes)} seats created.", "success")
                return redirect(url_for("admin.seats_list", location_id=location.id))
    return render_template("admin/seats/bulk.html", form=form, location=location)

@admin_bp.route("/locations/<int:location_id>/seats/bulk-edit", methods=["GET", "POST"])
@admin_required
def seats_bulk_edit(location_id: int):
    location = Location.query.get_or_404(location_id)
    available = Seat.query.filter_by(location_id=location.id).order_by(Seat.code).all()
    form = BulkSeatEditForm()
    form.seat_ids.choices = [(seat.id, seat.code) for seat in available]
    form.floor_id.choices = [(0, "Choose floor")] + [(floor.id, f"L{floor.level} - {floor.name}") for floor in location.floors]
    if not form.is_submitted():
        selected_ids = set(request.args.getlist("seat_id", type=int))
        if not selected_ids or len(selected_ids) > 100 or not selected_ids.issubset({seat.id for seat in available}):
            flash("Select between 1 and 100 seats from this location.", "warning")
            return redirect(url_for("admin.seats_list", location_id=location.id))
        form.seat_ids.data = sorted(selected_ids)
    if form.validate_on_submit():
        selected = [seat for seat in available if seat.id in form.seat_ids.data]
        for seat in selected:
            for name in form.apply_fields.data:
                value = form[name].data
                if name == "seat_type":
                    value = SeatType(value)
                elif name == "is_active":
                    value = value == "active"
                setattr(seat, name, value)
        db.session.commit()
        flash(f"{len(selected)} seats updated.", "success")
        return redirect(url_for("admin.seats_list", location_id=location.id))
    selected = [seat for seat in available if seat.id in (form.seat_ids.data or [])]
    return render_template("admin/seats/bulk_edit.html", form=form, location=location, seats=selected)

@admin_bp.route("/locations/<int:location_id>/seats", methods=["GET"])
@admin_required
def seats_list(location_id: int):
    loc = Location.query.get_or_404(location_id)
    seats = Seat.query.filter_by(location_id=loc.id).order_by(Seat.code).all()
    return render_template("admin/seats/list.html", location=loc, seats=seats)


@admin_bp.route("/locations/<int:location_id>/seats/new", methods=["GET", "POST"])
@admin_required
def seat_new(location_id: int):
    loc = Location.query.get_or_404(location_id)
    previous_id = request.args.get("previous", type=int)
    previous = Seat.query.filter_by(id=previous_id, location_id=loc.id).first_or_404() if previous_id else None
    carry = request.args.get("carry") == "1"
    form = SeatForm(obj=previous if carry else None)
    form.floor_id.choices = [(f.id, f"L{f.level} — {f.name}") for f in loc.floors]
    if previous and not form.is_submitted():
        form.code.data = _next_inventory_code(Seat, loc.id, previous.code)
        form.carry_details.data = carry
    if form.validate_on_submit():
        if Seat.query.filter_by(location_id=loc.id, code=form.code.data).first():
            form.code.errors.append("This seat code is already in use at this location.")
            return render_template("admin/seats/form.html", form=form, location=loc, title="New seat")
        resource = "private_office" if form.seat_type.data == SeatType.PRIVATE_OFFICE.value else "seat"
        ok, msg = tier_limits.check_limit(getattr(g, "operator", None), resource)
        if not ok:
            flash(msg, "warning")
            return render_template("admin/seats/form.html", form=form, location=loc, title="New seat")
        seat = Seat(operator_id=loc.operator_id, location_id=loc.id)
        form.populate_obj(seat)
        db.session.add(seat)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            form.code.errors.append("This seat code was just added. Choose another code.")
            return render_template("admin/seats/form.html", form=form, location=loc, title="New seat")
        flash("Seat created.", "success")
        if request.form.get("submit_action") == "save_next":
            return redirect(url_for("admin.seat_new", location_id=loc.id, previous=seat.id,
                                    carry="1" if form.carry_details.data else "0"))
        return redirect(url_for("admin.seats_list", location_id=loc.id))
    return render_template("admin/seats/form.html", form=form, location=loc, title="New seat")


@admin_bp.route("/seats/<int:seat_id>/edit", methods=["GET", "POST"])
@admin_required
def seat_edit(seat_id: int):
    seat = Seat.query.get_or_404(seat_id)
    form = SeatForm(obj=seat)
    form.floor_id.choices = [(f.id, f"L{f.level} — {f.name}") for f in seat.location.floors]
    if form.validate_on_submit():
        duplicate = Seat.query.filter(Seat.location_id == seat.location_id, Seat.code == form.code.data,
                                      Seat.id != seat.id).first()
        if duplicate:
            form.code.errors.append("This seat code is already in use at this location.")
            return render_template("admin/seats/form.html", form=form, location=seat.location, title="Edit seat")
        form.populate_obj(seat)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            form.code.errors.append("This seat code was just added. Choose another code.")
            return render_template("admin/seats/form.html", form=form, location=seat.location, title="Edit seat")
        flash("Seat updated.", "success")
        return redirect(url_for("admin.seats_list", location_id=seat.location_id))
    return render_template("admin/seats/form.html", form=form, location=seat.location, title="Edit seat")


# ----------------------------------------------------- conference rooms --

@admin_bp.route("/locations/<int:location_id>/rooms", methods=["GET"])
@admin_required
def rooms_list(location_id: int):
    loc = Location.query.get_or_404(location_id)
    rooms = ConferenceRoom.query.filter_by(location_id=loc.id).order_by(ConferenceRoom.name).all()
    return render_template("admin/rooms/list.html", location=loc, rooms=rooms)


@admin_bp.route("/locations/<int:location_id>/rooms/new", methods=["GET", "POST"])
@admin_required
def room_new(location_id: int):
    loc = Location.query.get_or_404(location_id)
    previous_id = request.args.get("previous", type=int)
    previous = ConferenceRoom.query.filter_by(id=previous_id, location_id=loc.id).first_or_404() if previous_id else None
    carry = request.args.get("carry") == "1"
    form = RoomForm(obj=previous if carry else None)
    form.floor_id.choices = [(f.id, f"L{f.level} — {f.name}") for f in loc.floors]
    form.category_id.choices = _room_category_choices(loc.operator_id)
    if previous and not form.is_submitted():
        form.code.data = _next_inventory_code(ConferenceRoom, loc.id, previous.code)
        form.name.data = ""
        form.category_id.data = (previous.category_id or 0) if carry else 0
        form.carry_details.data = carry
    if form.validate_on_submit():
        ok, msg = tier_limits.check_limit(getattr(g, "operator", None), "room")
        if not ok:
            flash(msg, "warning")
            return render_template("admin/rooms/form.html", form=form, location=loc, title="New room")
        room = ConferenceRoom(operator_id=loc.operator_id, location_id=loc.id)
        form.populate_obj(room)
        room.category_id = form.category_id.data or None
        db.session.add(room)
        db.session.commit()
        flash("Room created.", "success")
        if request.form.get("submit_action") == "save_next":
            return redirect(url_for("admin.room_new", location_id=loc.id, previous=room.id,
                                    carry="1" if form.carry_details.data else "0"))
        return redirect(url_for("admin.rooms_list", location_id=loc.id))
    return render_template("admin/rooms/form.html", form=form, location=loc, title="New room")


@admin_bp.route("/rooms/<int:room_id>/edit", methods=["GET", "POST"])
@admin_required
def room_edit(room_id: int):
    room = ConferenceRoom.query.get_or_404(room_id)
    form = RoomForm(obj=room)
    form.floor_id.choices = [(f.id, f"L{f.level} — {f.name}") for f in room.location.floors]
    form.category_id.choices = _room_category_choices(room.operator_id)
    if not form.is_submitted():
        form.category_id.data = room.category_id or 0
    if form.validate_on_submit():
        form.populate_obj(room)
        room.category_id = form.category_id.data or None
        db.session.commit()
        flash("Room updated.", "success")
        return redirect(url_for("admin.rooms_list", location_id=room.location_id))
    return render_template("admin/rooms/form.html", form=form, location=room.location, title="Edit room")


# ---------------------------------------------------------- pricing plans --

def _normalize_plan_conditions(plan, form):
    if form.scope.data != "company_custom":
        plan.company_id = None
    else:
        plan.company_id = form.company_id.data
    if form.plan_type.data not in ("private_office", "managed_office"):
        plan.office_capacity = None
    if form.billing_unit.data not in ("per_seat", "per_office", "flat_fee"):
        plan.included_seat_quantity = 0
    if form.plan_type.data == "day_pass":
        plan.minimum_contract_months = 0
    if form.plan_type.data not in ("private_office", "managed_office"):
        plan.office_capacity = None
    if form.billing_unit.data not in ("per_seat", "per_office", "flat_fee"):
        plan.included_seat_quantity = 0
    if not form.additional_seats_allowed.data:
        plan.additional_seat_rate = 0
        plan.maximum_additional_seats = None
    if not form.deposit_required.data:
        plan.deposit_calculation = None
        plan.deposit_value = 0
        plan.deposit_refundable = False
    if form.location_scope.data == "all":
        plan.locations = Location.query.order_by(Location.name).all()
    else:
        plan.locations = Location.query.filter(Location.id.in_(form.location_ids.data)).all()

@admin_bp.route("/plans")
@admin_required
def plans_list():
    plans = PricingPlan.query.order_by(PricingPlan.base_price).all()
    return render_template("admin/plans/list.html", plans=plans)


@admin_bp.route("/plans/new", methods=["GET", "POST"])
@super_admin_required
def plan_new():
    form = PricingPlanForm()
    form.company_id.choices = [(0, "— any company —")] + [(c.id, c.name) for c in Company.query.order_by(Company.name).all()]
    form.location_ids.choices = [(l.id, l.name) for l in Location.query.order_by(Location.name).all()]
    if form.validate_on_submit():
        plan = PricingPlan()
        form.populate_obj(plan)
        db.session.add(plan)
        _normalize_plan_conditions(plan, form)
        plan.is_active = form.status.data == PlanStatus.ACTIVE.value
        db.session.commit()
        flash("Plan created.", "success")
        return redirect(url_for("admin.plans_list"))
    return render_template("admin/plans/form.html", form=form, title="New plan")


@admin_bp.route("/plans/<int:plan_id>/edit", methods=["GET", "POST"])
@super_admin_required
def plan_edit(plan_id: int):
    plan = PricingPlan.query.get_or_404(plan_id)
    form = PricingPlanForm(obj=plan)
    form.company_id.choices = [(0, "— any company —")] + [(c.id, c.name) for c in Company.query.order_by(Company.name).all()]
    form.location_ids.choices = [(l.id, l.name) for l in Location.query.order_by(Location.name).all()]
    if not form.is_submitted():
        form.company_id.data = plan.company_id or 0
        form.location_ids.data = [location.id for location in plan.locations]
    if form.validate_on_submit():
        form.populate_obj(plan)
        _normalize_plan_conditions(plan, form)
        plan.is_active = form.status.data == PlanStatus.ACTIVE.value
        db.session.commit()
        flash("Plan updated.", "success")
        return redirect(url_for("admin.plans_list"))
    return render_template("admin/plans/form.html", form=form, title="Edit plan")


# ------------------------------------------------------------- companies --

@admin_bp.route("/companies/<int:company_id>/archive", methods=["POST"])
@manager_or_super_required
def company_archive(company_id: int):
    company = Company.query.get_or_404(company_id)
    if company.status == CompanyStatus.CHURNED:
        return redirect(url_for("admin.companies_list"))
    company.profile_details = {**(company.profile_details or {}), "archived_access": [
        {"id": user.id, "active": user.is_active, "revoked": user.invite_revoked} for user in company.users]}
    company.status = CompanyStatus.CHURNED
    for user in company.users:
        user.is_active = False
        user.invite_revoked = True
    db.session.commit()
    flash("Company archived and sign-in blocked. Contracts and billing records are retained.", "info")
    return redirect(url_for("admin.companies_list"))

@admin_bp.route("/companies/<int:company_id>/restore", methods=["POST"])
@manager_or_super_required
def company_restore(company_id: int):
    company = Company.query.get_or_404(company_id)
    if company.status != CompanyStatus.CHURNED:
        abort(400)
    company.status = CompanyStatus.ACTIVE
    details = dict(company.profile_details or {})
    previous = {row["id"]: row for row in details.pop("archived_access", [])}
    for user in company.users:
        if user.id in previous:
            user.invite_revoked = previous[user.id]["revoked"]
            user.is_active = previous[user.id]["active"]
    company.profile_details = details
    db.session.commit()
    flash("Company restored. Resend any pending invitations from Invites.", "success")
    return redirect(url_for("admin.company_detail", company_id=company.id))

@admin_bp.route("/companies")
@admin_required
def companies_list():
    from ...services import company_overview
    return render_template("admin/companies/list.html", overview=company_overview.build(g.operator_id))


@admin_bp.route("/people")
@admin_required
def people():
    from ...services import company_overview
    overview = company_overview.build(g.operator_id)
    individuals = User.query.filter_by(role=UserRole.INDIVIDUAL).order_by(User.full_name).all()
    rows = [{"name": card["company"].name, "email": card["company"].billing_email,
             "phone": card["company"].contact_phone, "kind": "Company", "status": card["company"].status.value,
             "seats": card["seats"], "due": card["due"],
             "url": url_for("admin.company_detail", company_id=card["company"].id)} for card in overview["cards"]]
    invoices = Invoice.query.filter(Invoice.user_id.in_([user.id for user in individuals] or [0]),
                                    Invoice.status.in_(["issued", "partial", "overdue"])).all()
    balances = {}
    for invoice in invoices:
        balances[invoice.user_id] = balances.get(invoice.user_id, 0) + invoice.balance_due
    for user in individuals:
        rows.append({"name": user.full_name, "email": user.email, "phone": user.phone, "kind": "Individual",
                     "status": "active" if user.is_active else "inactive", "seats": None, "due": balances.get(user.id, 0),
                     "url": url_for("admin.individuals_list") + f"#individual-{user.id}"})
    query = request.args.get("q", "").strip()
    kind = request.args.get("kind", "all")
    visible = [row for row in rows if (kind == "all" or row["kind"].lower() == kind) and
               query.lower() in " ".join(str(row[key] or "") for key in ("name", "email", "phone")).lower()]
    return render_template("admin/people.html", rows=visible, overview=overview, individual_count=len(individuals),
                           query=query, kind=kind)


@admin_bp.route("/companies/new", methods=["GET", "POST"])
@manager_or_super_required
def company_new():
    # Creating a company here alone leaves it with no admin login. Use the
    # invite flow instead, which creates the company + a pending admin user
    # and emails them a signup link.
    return redirect(url_for("admin.invite_company_new"))


@admin_bp.route("/companies/<int:company_id>")
@admin_required
def company_detail(company_id: int):
    c = Company.query.get_or_404(company_id)
    subs = Subscription.query.filter_by(company_id=c.id).order_by(Subscription.created_at.desc()).all()
    subscription_requests = (SubscriptionChangeRequest.query.filter_by(company_id=c.id)
                             .order_by(SubscriptionChangeRequest.created_at.desc()).all())
    return render_template("admin/companies/detail.html", company=c, subscriptions=subs,
                           subscription_requests=subscription_requests)


@admin_bp.route("/companies/<int:company_id>/edit", methods=["GET", "POST"])
@manager_or_super_required
def company_edit(company_id: int):
    c = Company.query.get_or_404(company_id)
    form = CompanyForm(obj=c, data=c.profile_details or {})
    if form.validate_on_submit():
        form.populate_obj(c)
        from ..profile_forms import save_details, business_address
        save_details(c, form)
        c.billing_address = business_address(c) or c.billing_address
        db.session.commit()
        flash("Company updated.", "success")
        return redirect(url_for("admin.company_detail", company_id=c.id))
    return render_template("admin/companies/form.html", form=form, title="Edit company", company=c)


# ----------------------------------------------------------- allocations --

@admin_bp.route("/allocations", methods=["GET", "POST"])
@admin_required
def allocations():
    form = AllocationForm()
    form.seat_id.choices = [(s.id, f"{s.location.code} / {s.code} ({s.seat_type.value})")
                            for s in Seat.query.filter_by(is_active=True).order_by(Seat.code).all()]
    form.company_id.choices = [(0, "— none —")] + [(c.id, c.name) for c in Company.query.order_by(Company.name).all()]
    form.user_id.choices = [(0, "— none —")] + [
        (u.id, f"{u.full_name} ({u.email})")
        for u in User.query.filter_by(role=UserRole.INDIVIDUAL).order_by(User.full_name).all()
    ]

    if form.validate_on_submit():
        if not form.company_id.data and not form.user_id.data:
            flash("Choose a company or an individual user.", "warning")
        else:
            alloc = SeatAllocation(
                seat_id=form.seat_id.data,
                company_id=form.company_id.data or None,
                user_id=form.user_id.data or None,
                start_date=form.start_date.data,
                end_date=form.end_date.data,
                status=AllocationStatus.ACTIVE,
            )
            db.session.add(alloc)
            db.session.commit()
            flash("Allocation created.", "success")
            return redirect(url_for("admin.allocations"))

    active = (SeatAllocation.query
              .filter_by(status=AllocationStatus.ACTIVE)
              .order_by(SeatAllocation.created_at.desc()).all())
    return render_template("admin/allocations/list.html", form=form, allocations=active)


@admin_bp.route("/allocations/<int:alloc_id>/end", methods=["POST"])
@admin_required
def allocation_end(alloc_id: int):
    alloc = SeatAllocation.query.get_or_404(alloc_id)
    alloc.status = AllocationStatus.ENDED
    alloc.end_date = date.today()
    db.session.commit()
    flash("Allocation ended.", "info")
    return redirect(url_for("admin.allocations"))


# ------------------------------------------------------------ documents --

@admin_bp.route("/documents", methods=["GET", "POST"])
@admin_required
def operator_documents():
    form = DocumentUploadForm()
    if form.validate_on_submit():
        f = form.file.data
        operator_id = getattr(g, "operator_id", None)
        stored = storage_service.upload(
            namespace=f"operators/{operator_id}/documents",
            filename=f.filename,
            stream=f.stream,
            content_type=f.mimetype,
            scope="operator",
        )
        db.session.add(Document(
            operator_id=operator_id,
            kind=DocumentKind(form.kind.data),
            owner_type="operator",
            owner_id=operator_id,
            filename=f.filename,
            tag=(form.tag.data or "").strip() or None,
            content_type=f.mimetype,
            size_bytes=stored.size_bytes,
            storage_backend=stored.backend,
            storage_bucket=stored.bucket,
            storage_key=stored.key,
            uploaded_by_id=current_user.id,
        ))
        db.session.commit()
        flash("Operator document uploaded.", "success")
        return redirect(url_for("admin.operator_documents"))
    q = (request.args.get("q") or "").strip()
    query = Document.query.filter_by(owner_type="operator")
    if q:
        query = query.filter(or_(Document.filename.icontains(q, autoescape=True), Document.tag.icontains(q, autoescape=True)))
    documents = query.order_by(Document.created_at.desc()).all()
    return render_template("admin/documents.html", form=form, documents=documents, q=q,
                           title="Workspace documents")

@admin_bp.route("/companies/<int:company_id>/documents", methods=["GET", "POST"])
@admin_required
def company_documents(company_id: int):
    c = Company.query.get_or_404(company_id)
    form = DocumentUploadForm()
    if form.validate_on_submit():
        f = form.file.data
        stored = storage_service.upload(
            namespace=f"operators/{getattr(g, 'operator_id', 'unscoped')}/companies/{c.id}",
            filename=f.filename,
            stream=f.stream,
            content_type=f.mimetype,
            scope="operator",
        )
        doc = Document(
            operator_id=getattr(g, "operator_id", None),
            kind=DocumentKind(form.kind.data),
            owner_type="company",
            owner_id=c.id,
            filename=f.filename,
            tag=(form.tag.data or "").strip() or None,
            content_type=f.mimetype,
            size_bytes=stored.size_bytes,
            storage_backend=stored.backend,
            storage_bucket=stored.bucket,
            storage_key=stored.key,
            uploaded_by_id=current_user.id,
        )
        db.session.add(doc)
        db.session.flush()
        db.session.add(CompanyDocument(company_id=c.id, document_id=doc.id))
        db.session.commit()
        flash("Document uploaded.", "success")
        return redirect(url_for("admin.company_documents", company_id=c.id))
    q = (request.args.get("q") or "").strip().lower()
    documents = [cd.document for cd in c.documents
                 if not q or q in cd.document.filename.lower() or q in (cd.document.tag or "").lower()]
    return render_template("admin/companies/documents.html", company=c, form=form, documents=documents, q=q)


# ------------------------------------------------------------- invoices --

@admin_bp.route("/invoices")
@admin_required
def invoices_list():
    from ...models import PaymentSubmission, PaymentSubmissionStatus
    invoices = Invoice.query.order_by(Invoice.issued_at.desc().nullslast()).limit(200).all()
    reported = {s.invoice_id for s in PaymentSubmission.query.filter_by(status=PaymentSubmissionStatus.PENDING).all()}
    invoices.sort(key=lambda i: i.id not in reported)  # invoices with a payment to confirm come first
    return render_template("admin/invoices/list.html", invoices=invoices, reported=reported)


@admin_bp.route("/billing/run", methods=["POST"])
@manager_or_super_required
def billing_run():
    from ...services.billing_service import run_monthly_billing
    invoices = run_monthly_billing(operator_id=g.operator_id, respect_issue_day=False)
    flash(f"Generated {len(invoices)} invoice(s).", "success")
    return redirect(url_for("admin.invoices_list"))


# ------------------------------------------------------ reception (day-pass) --

@admin_bp.route("/reception", methods=["GET", "POST"])
@admin_required
def reception():
    """Reception check-in: paste or scan a day-pass code to check the guest in."""
    checked = None
    error = None
    if request.method == "POST":
        code = (request.form.get("code") or "").strip()
        dp = DayPass.query.filter_by(code=code).first()
        if dp is None:
            error = "Unknown code."
        elif dp.status == DayPassStatus.CANCELLED:
            error = "This day pass was cancelled."
        elif dp.status == DayPassStatus.CHECKED_IN:
            error = f"Already checked in at {dp.checked_in_at:%Y-%m-%d %H:%M}."
            checked = dp
        elif dp.pass_date != date.today():
            error = f"Pass is valid on {dp.pass_date}, not today."
            checked = dp
        else:
            dp.status = DayPassStatus.CHECKED_IN
            dp.checked_in_at = datetime.utcnow()
            db.session.commit()
            checked = dp
            flash(f"{dp.user.full_name} checked in.", "success")
    todays = (DayPass.query.filter(DayPass.pass_date == date.today())
                             .order_by(DayPass.created_at.desc()).limit(50).all())
    return render_template("admin/reception.html",
                           checked=checked, error=error, todays=todays)
