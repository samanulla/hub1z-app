"""Admin (Super Admin + Location Manager) routes."""
from __future__ import annotations

from datetime import date, datetime

from flask import Blueprint, render_template, redirect, url_for, flash, request, abort, g
from flask_login import current_user
from sqlalchemy import func

from ...extensions import db
from ...models import (
    User, UserRole, Location, Floor, Seat, SeatType, ConferenceRoom,
    Company, CompanyStatus, PricingPlan, Subscription, SubscriptionStatus,
    SeatAllocation, AllocationStatus, SeatBooking, RoomBooking, BookingStatus,
    Document, DocumentKind, CompanyDocument, Invoice, DayPass, DayPassStatus,
)
from ...services.storage import storage_service
from ...services import tier_limits
from ...utils.decorators import admin_required, super_admin_required, manager_or_super_required
from .forms import (
    LocationForm, FloorForm, SeatForm, RoomForm, PricingPlanForm,
    CompanyForm, AllocationForm, DocumentUploadForm,
)

admin_bp = Blueprint("admin", __name__, template_folder="../../templates")


# ------------------------------------------------------------ dashboard --

@admin_bp.route("/")
@admin_required
def dashboard():
    # Seat/ConferenceRoom/SeatBooking/RoomBooking have no tenant_id of their
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
    return render_template("admin/dashboard.html",
                           stats=stats,
                           recent_companies=recent_companies,
                           recent_bookings=recent_bookings)


# ------------------------------------------------------------- locations --

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
        ok, msg = tier_limits.check_limit(getattr(g, "tenant", None), "location")
        if not ok:
            flash(msg, "warning")
            return render_template("admin/locations/form.html", form=form, title="New location")
        loc = Location(tenant_id=getattr(g, "tenant_id", None))
        form.populate_obj(loc)
        db.session.add(loc)
        if getattr(g, "tenant", None) and g.tenant.primary_location_id is None:
            db.session.flush()
            g.tenant.primary_location_id = loc.id
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
        floor = Floor(tenant_id=loc.tenant_id, location_id=loc.id,
                  level=form.level.data, name=form.name.data)
        db.session.add(floor)
        db.session.commit()
        flash("Floor added.", "success")
        return redirect(url_for("admin.location_detail", location_id=loc.id))
    return render_template("admin/floors/form.html", form=form, location=loc)


# ---------------------------------------------------------------- seats --

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
    form = SeatForm()
    form.floor_id.choices = [(f.id, f"L{f.level} — {f.name}") for f in loc.floors]
    if form.validate_on_submit():
        resource = "private_office" if form.seat_type.data == SeatType.PRIVATE_OFFICE.value else "seat"
        ok, msg = tier_limits.check_limit(getattr(g, "tenant", None), resource)
        if not ok:
            flash(msg, "warning")
            return render_template("admin/seats/form.html", form=form, location=loc, title="New seat")
        seat = Seat(tenant_id=loc.tenant_id, location_id=loc.id)
        form.populate_obj(seat)
        db.session.add(seat)
        db.session.commit()
        flash("Seat created.", "success")
        return redirect(url_for("admin.seats_list", location_id=loc.id))
    return render_template("admin/seats/form.html", form=form, location=loc, title="New seat")


@admin_bp.route("/seats/<int:seat_id>/edit", methods=["GET", "POST"])
@admin_required
def seat_edit(seat_id: int):
    seat = Seat.query.get_or_404(seat_id)
    form = SeatForm(obj=seat)
    form.floor_id.choices = [(f.id, f"L{f.level} — {f.name}") for f in seat.location.floors]
    if form.validate_on_submit():
        form.populate_obj(seat)
        db.session.commit()
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
    form = RoomForm()
    form.floor_id.choices = [(f.id, f"L{f.level} — {f.name}") for f in loc.floors]
    if form.validate_on_submit():
        ok, msg = tier_limits.check_limit(getattr(g, "tenant", None), "room")
        if not ok:
            flash(msg, "warning")
            return render_template("admin/rooms/form.html", form=form, location=loc, title="New room")
        room = ConferenceRoom(tenant_id=loc.tenant_id, location_id=loc.id)
        form.populate_obj(room)
        db.session.add(room)
        db.session.commit()
        flash("Room created.", "success")
        return redirect(url_for("admin.rooms_list", location_id=loc.id))
    return render_template("admin/rooms/form.html", form=form, location=loc, title="New room")


@admin_bp.route("/rooms/<int:room_id>/edit", methods=["GET", "POST"])
@admin_required
def room_edit(room_id: int):
    room = ConferenceRoom.query.get_or_404(room_id)
    form = RoomForm(obj=room)
    form.floor_id.choices = [(f.id, f"L{f.level} — {f.name}") for f in room.location.floors]
    if form.validate_on_submit():
        form.populate_obj(room)
        db.session.commit()
        flash("Room updated.", "success")
        return redirect(url_for("admin.rooms_list", location_id=room.location_id))
    return render_template("admin/rooms/form.html", form=form, location=room.location, title="Edit room")


# ---------------------------------------------------------- pricing plans --

@admin_bp.route("/plans")
@admin_required
def plans_list():
    plans = PricingPlan.query.order_by(PricingPlan.base_price).all()
    return render_template("admin/plans/list.html", plans=plans)


@admin_bp.route("/plans/new", methods=["GET", "POST"])
@super_admin_required
def plan_new():
    form = PricingPlanForm()
    if form.validate_on_submit():
        plan = PricingPlan()
        form.populate_obj(plan)
        db.session.add(plan)
        db.session.commit()
        flash("Plan created.", "success")
        return redirect(url_for("admin.plans_list"))
    return render_template("admin/plans/form.html", form=form, title="New plan")


@admin_bp.route("/plans/<int:plan_id>/edit", methods=["GET", "POST"])
@super_admin_required
def plan_edit(plan_id: int):
    plan = PricingPlan.query.get_or_404(plan_id)
    form = PricingPlanForm(obj=plan)
    if form.validate_on_submit():
        form.populate_obj(plan)
        db.session.commit()
        flash("Plan updated.", "success")
        return redirect(url_for("admin.plans_list"))
    return render_template("admin/plans/form.html", form=form, title="Edit plan")


# ------------------------------------------------------------- companies --

@admin_bp.route("/companies")
@admin_required
def companies_list():
    companies = Company.query.order_by(Company.name).all()
    return render_template("admin/companies/list.html", companies=companies)


@admin_bp.route("/companies/new", methods=["GET", "POST"])
@manager_or_super_required
def company_new():
    form = CompanyForm()
    if form.validate_on_submit():
        c = Company(tenant_id=getattr(g, "tenant_id", None))
        form.populate_obj(c)
        db.session.add(c)
        db.session.commit()
        flash("Company created.", "success")
        return redirect(url_for("admin.company_detail", company_id=c.id))
    return render_template("admin/companies/form.html", form=form, title="New company")


@admin_bp.route("/companies/<int:company_id>")
@admin_required
def company_detail(company_id: int):
    c = Company.query.get_or_404(company_id)
    subs = Subscription.query.filter_by(company_id=c.id).order_by(Subscription.created_at.desc()).all()
    return render_template("admin/companies/detail.html", company=c, subscriptions=subs)


@admin_bp.route("/companies/<int:company_id>/edit", methods=["GET", "POST"])
@manager_or_super_required
def company_edit(company_id: int):
    c = Company.query.get_or_404(company_id)
    form = CompanyForm(obj=c)
    if form.validate_on_submit():
        form.populate_obj(c)
        db.session.commit()
        flash("Company updated.", "success")
        return redirect(url_for("admin.company_detail", company_id=c.id))
    return render_template("admin/companies/form.html", form=form, title="Edit company")


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

@admin_bp.route("/companies/<int:company_id>/documents", methods=["GET", "POST"])
@admin_required
def company_documents(company_id: int):
    c = Company.query.get_or_404(company_id)
    form = DocumentUploadForm()
    if form.validate_on_submit():
        f = form.file.data
        stored = storage_service.upload(
            namespace=f"companies/{c.id}",
            filename=f.filename,
            stream=f.stream,
            content_type=f.mimetype,
        )
        doc = Document(
            kind=DocumentKind(form.kind.data),
            filename=f.filename,
            content_type=f.mimetype,
            size_bytes=stored.size_bytes,
            storage_backend=stored.backend,
            storage_key=stored.key,
            uploaded_by_id=current_user.id,
        )
        db.session.add(doc)
        db.session.flush()
        db.session.add(CompanyDocument(company_id=c.id, document_id=doc.id))
        db.session.commit()
        flash("Document uploaded.", "success")
        return redirect(url_for("admin.company_documents", company_id=c.id))
    return render_template("admin/companies/documents.html", company=c, form=form)


# ------------------------------------------------------------- invoices --

@admin_bp.route("/invoices")
@admin_required
def invoices_list():
    invoices = Invoice.query.order_by(Invoice.issued_at.desc().nullslast()).limit(200).all()
    return render_template("admin/invoices/list.html", invoices=invoices)


@admin_bp.route("/billing/run", methods=["POST"])
@manager_or_super_required
def billing_run():
    from ...services.billing_service import run_monthly_billing
    invoices = run_monthly_billing()
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
