"""Public booking blueprint — members choose a location and reserve a seat/room."""
from __future__ import annotations

from datetime import datetime, timedelta, date as date_cls, time as time_cls
from decimal import Decimal
from zoneinfo import ZoneInfo

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, abort
from flask_login import current_user, login_required

from ...extensions import db
from ...models import (
    Location, Seat, ConferenceRoom, SeatType, RoomWaitlist, WaitlistStatus,
    RecurringRoomBooking, RecurrencePattern, RoomBooking, RoomBlock, SeatBooking, BookingStatus,
    User, UserRole,
)
from ...services import calendar_view, credit_service
from ...services.booking_service import (
    create_seat_booking, create_room_booking, quote_seat, quote_room, preview_room, check_in, can_check_in,
    BookingError, check_seat_conflict, check_room_conflict, can_manage_booking, update_room_booking, update_series,
)
from ...services.formatting import format_money, now_local, parse_local_naive_to_utc, to_local
from ...utils.decorators import member_or_admin_required

booking_bp = Blueprint("book", __name__, template_folder="../../templates")


def _current_user_credits() -> int:
    return credit_service.balance(current_user.operator_id, **credit_service.subject_for(current_user))["total"]


@booking_bp.route("/")
@login_required
def index():
    locations = Location.query.filter_by(is_active=True).order_by(Location.name).all()
    return render_template("booking/locations.html", locations=locations)


@booking_bp.route("/locations/<int:location_id>")
@login_required
def location_home(location_id: int):
    loc = Location.query.get_or_404(location_id)
    hot_desks = [s for s in loc.seats if s.seat_type == SeatType.HOT_DESK and s.is_active]
    rooms = [r for r in loc.rooms if r.is_active]
    return render_template("booking/location_home.html",
                           location=loc, hot_desks=hot_desks, rooms=rooms)


@booking_bp.route("/calendar")
@member_or_admin_required
def calendar():
    """Default entry point for the top-nav Calendar link — picks a sensible
    location (operator's primary, else the first active one) and redirects."""
    from flask import g
    operator = getattr(g, "operator", None)
    loc = None
    if operator and operator.primary_location_id:
        loc = Location.query.filter_by(id=operator.primary_location_id, is_active=True).first()
    if loc is None:
        loc = Location.query.filter_by(is_active=True).order_by(Location.name).first()
    if loc is None:
        flash("No active locations yet.", "info")
        return redirect(url_for("member.dashboard"))
    return redirect(url_for("book.location_calendar", location_id=loc.id))


@booking_bp.route("/locations/<int:location_id>/calendar")
@member_or_admin_required
def location_calendar(location_id: int):
    """A day view of conference-room availability for this location —
    click an open slot to book it (subject to available credits)."""
    loc = Location.query.get_or_404(location_id)
    rooms = [r for r in loc.rooms if r.is_active]

    # Rooms an operator has opted to make bookable from any of their
    # locations' calendars, not just their own.
    cross_location_rooms = (ConferenceRoom.query
                            .filter(ConferenceRoom.location_id != loc.id,
                                   ConferenceRoom.operator_id == loc.operator_id,
                                   ConferenceRoom.is_active.is_(True),
                                   ConferenceRoom.cross_location_bookable.is_(True))
                            .order_by(ConferenceRoom.name).all())
    bookable_rooms = rooms + cross_location_rooms
    tz = calendar_view.location_tz(loc)

    date_str = request.args.get("date")
    try:
        day = datetime.strptime(date_str, "%Y-%m-%d").date() if date_str else datetime.now(tz).date()
    except ValueError:
        day = datetime.now(tz).date()

    view = "week" if request.args.get("view") == "week" else "day"
    week_room = next((r for r in bookable_rooms if r.id == request.args.get("room", type=int)),
                     bookable_rooms[0] if bookable_rooms else None)
    cal = calendar_view.build_calendar(loc=loc, rooms=bookable_rooms, day=day, view=view,
                                       week_room=week_room, viewer=current_user)

    # The list under the grid: the operator sees every booking; everyone else only their own
    # and their company's, so other people's meetings stay private.
    days = cal["days"]
    start_utc = datetime.combine(days[0], time_cls.min).replace(tzinfo=tz).astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
    end_utc = start_utc + timedelta(days=len(days))
    room_ids = [r.id for r in bookable_rooms]
    bookings, blocks = [], []
    if room_ids:
        q = (RoomBooking.query.filter(RoomBooking.room_id.in_(room_ids),
                                      RoomBooking.status.in_([BookingStatus.CONFIRMED, BookingStatus.CHECKED_IN]),
                                      RoomBooking.start_at < end_utc, RoomBooking.end_at > start_utc))
        if not current_user.is_admin:
            q = q.filter((RoomBooking.user_id == current_user.id) |
                         ((RoomBooking.company_id == current_user.company_id) & RoomBooking.company_id.isnot(None)))
        bookings = q.order_by(RoomBooking.start_at).all()
        if current_user.is_admin:
            blocks = (RoomBlock.query.filter(RoomBlock.room_id.in_(room_ids), RoomBlock.start_at < end_utc,
                                             RoomBlock.end_at > start_utc).order_by(RoomBlock.start_at).all())

    locations = Location.query.filter_by(is_active=True).order_by(Location.name).all()
    recipients = []
    if current_user.is_admin:
        recipients = (User.query
                     .filter(User.role.in_([UserRole.EMPLOYEE, UserRole.INDIVIDUAL]), User.is_active.is_(True))
                     .order_by(User.full_name).all())

    step = timedelta(days=7 if view == "week" else 1)
    now = datetime.utcnow()
    return render_template(
        "booking/calendar.html", location=loc, locations=locations, bookable_rooms=bookable_rooms, cal=cal,
        view=view, week_room=week_room, recipients=recipients, day=day, prev_day=day - step, next_day=day + step,
        today=datetime.now(tz).date(), credits_available=_current_user_credits(),
        day_bookings=bookings, blocks=blocks, now=now, can_check_in=can_check_in, can_manage=can_manage_booking,
    )


@booking_bp.route("/rooms/<int:room_id>/quote")
@member_or_admin_required
def room_quote(room_id: int):
    """What booking this room for this time would do (credits, cash, or why it can't be done).
    Called by the calendar's side panel as the selection changes."""
    room = ConferenceRoom.query.get_or_404(room_id)
    try:
        start = parse_local_naive_to_utc(request.args["start"])
        end = parse_local_naive_to_utc(request.args["end"])
    except (KeyError, ValueError):
        return jsonify({"ok": False, "message": "Choose a start and end time."})
    for_user, waive = None, False
    if current_user.is_admin:
        recipient_id = request.args.get("for_user_id", type=int)
        if recipient_id:
            for_user = User.query.filter(User.id == recipient_id,
                                         User.role.in_([UserRole.EMPLOYEE, UserRole.INDIVIDUAL])).first()
        waive = bool(request.args.get("waive_charge"))
    out = preview_room(user=current_user, room=room, start=start, end=end,
                       attendees=request.args.get("attendees", 1, type=int), for_user=for_user, waive_charge=waive)
    if out["ok"]:
        out["cash_display"] = format_money(Decimal(out["cash"]))
    return jsonify(out)


@booking_bp.route("/locations/<int:location_id>/calendar/block", methods=["POST"])
@member_or_admin_required
def calendar_block(location_id: int):
    """The operator takes a room out of use (no credits involved)."""
    if not current_user.is_admin:
        abort(403)
    loc = Location.query.get_or_404(location_id)
    room = ConferenceRoom.query.get_or_404(request.form.get("room_id", type=int) or 0)
    back = redirect(url_for("book.location_calendar", location_id=loc.id, date=(request.form.get("start") or "")[:10]))
    try:
        start = parse_local_naive_to_utc(request.form["start"])
        end = parse_local_naive_to_utc(request.form["end"])
        credit_service.slots_between(start, end)
    except (KeyError, ValueError, credit_service.CreditError) as e:
        flash(str(e) if isinstance(e, credit_service.CreditError) else "Invalid start or end time.", "danger")
        return back
    clash = check_room_conflict(room.id, start, end)
    if clash:
        flash("That time already has bookings. Cancel or move them first, then block the room.", "warning")
        return back
    db.session.query(ConferenceRoom.id).filter(ConferenceRoom.id == room.id).with_for_update().first()
    db.session.add(RoomBlock(operator_id=room.operator_id, room_id=room.id, start_at=start, end_at=end,
                             reason=(request.form.get("reason") or "").strip()[:200] or None,
                             created_by_id=current_user.id))
    db.session.commit()
    flash(f"{room.name} is blocked for that time. No credits are used.", "success")
    return back


@booking_bp.route("/blocks/<int:block_id>/delete", methods=["POST"])
@member_or_admin_required
def calendar_block_delete(block_id: int):
    if not current_user.is_admin:
        abort(403)
    block = RoomBlock.query.get_or_404(block_id)
    location_id = block.room.location_id
    db.session.delete(block)
    db.session.commit()
    flash("Block removed.", "info")
    return redirect(url_for("book.location_calendar", location_id=location_id))


@booking_bp.route("/bookings/room/<int:booking_id>/check-in", methods=["POST"])
@member_or_admin_required
def room_check_in(booking_id: int):
    b = RoomBooking.query.get_or_404(booking_id)
    allowed = (b.user_id == current_user.id or current_user.is_admin
               or (current_user.is_company_admin and b.company_id == current_user.company_id))
    if not allowed:
        abort(403)
    try:
        check_in(b)
        flash("Checked in. Enjoy your meeting.", "success")
    except BookingError as e:
        flash(str(e), "warning")
    return redirect(request.referrer or url_for("member.bookings"))


@booking_bp.route("/bookings/room/<int:booking_id>/edit", methods=["GET", "POST"])
@member_or_admin_required
def room_booking_edit(booking_id: int):
    """Change one meeting, or every upcoming meeting in its series (time of day only), like a calendar app."""
    b = RoomBooking.query.get_or_404(booking_id)
    if not can_manage_booking(b, current_user):
        abort(403)
    series = b.recurring_booking
    fmt = "%Y-%m-%dT%H:%M"
    if request.method == "POST":
        form = request.form
        try:
            start = parse_local_naive_to_utc(form["start"])
            end = parse_local_naive_to_utc(form["end"])
        except (KeyError, ValueError):
            flash("Invalid start or end time.", "danger")
            return redirect(url_for("book.room_booking_edit", booking_id=b.id))
        title = (form.get("title") or "").strip()[:200] or None
        notes = (form.get("notes") or "").strip() or None
        attendees = form.get("attendees", type=int) or 1
        try:
            if series is not None and form.get("scope") == "series":
                tz = ZoneInfo(b.room.location.timezone or "UTC")
                utc = ZoneInfo("UTC")
                local_start = start.replace(tzinfo=utc).astimezone(tz)
                local_end = end.replace(tzinfo=utc).astimezone(tz)
                until = form.get("series_until")
                result = update_series(
                    series, current_user, start_time=local_start.time(), end_time=local_end.time(),
                    end_date=date_cls.fromisoformat(until) if until else None,
                    title=title, attendees=attendees, notes=notes)
                msg = f"Series updated: {result['updated']} upcoming meeting(s) changed."
                if result["cancelled"]:
                    msg += f" {result['cancelled']} after the new end date cancelled."
                if result["failed"]:
                    msg += (" Could not change " + ", ".join(d.strftime("%d %b") for d in result["failed"])
                            + " (room busy or too close to start).")
                flash(msg, "warning" if result["failed"] else "success")
            else:
                update_room_booking(b, current_user, start=start, end=end, title=title, attendees=attendees,
                                    notes=notes)
                flash("Meeting updated.", "success")
        except (BookingError, ValueError) as e:
            flash(str(e), "danger")
            return redirect(url_for("book.room_booking_edit", booking_id=b.id))
        return redirect(url_for("member.bookings"))
    return render_template("booking/room_booking_edit.html", booking=b, series=series,
                           start=to_local(b.start_at).strftime(fmt), end=to_local(b.end_at).strftime(fmt))


@booking_bp.route("/locations/<int:location_id>/calendar/quick-book", methods=["POST"])
@member_or_admin_required
def location_calendar_quick_book(location_id: int):
    """Create a meeting directly from the calendar's 'Add meeting' modal.
    The room may belong to this location, or to another of the operator's
    locations if that room was opted into cross-location booking."""
    loc = Location.query.get_or_404(location_id)
    room_id = request.form.get("room_id", type=int)
    room = ConferenceRoom.query.filter(
        ConferenceRoom.id == room_id, ConferenceRoom.operator_id == loc.operator_id,
        ConferenceRoom.is_active.is_(True),
        (ConferenceRoom.location_id == loc.id) | (ConferenceRoom.cross_location_bookable.is_(True)),
    ).first()
    if room is None:
        flash("Pick a valid room.", "warning")
        return redirect(url_for("book.location_calendar", location_id=loc.id))
    try:
        start = parse_local_naive_to_utc(request.form["start"])
        end = parse_local_naive_to_utc(request.form["end"])
    except (KeyError, ValueError):
        flash("Invalid start or end time.", "danger")
        return redirect(url_for("book.location_calendar", location_id=loc.id))

    day_param = start.strftime("%Y-%m-%d")
    for_user = None
    waive_charge = False
    if current_user.is_admin:
        recipient_id = request.form.get("for_user_id", type=int)
        if recipient_id:
            for_user = User.query.filter(
                User.id == recipient_id, User.role.in_([UserRole.EMPLOYEE, UserRole.INDIVIDUAL]),
            ).first()
        waive_charge = bool(request.form.get("waive_charge"))
    series = None
    if request.form.get("repeat") in ("daily", "weekly"):
        utc, tz = ZoneInfo("UTC"), ZoneInfo(room.location.timezone or "UTC")
        local_start, local_end = start.replace(tzinfo=utc).astimezone(tz), end.replace(tzinfo=utc).astimezone(tz)
        try:
            until = date_cls.fromisoformat(request.form["repeat_until"])
        except (KeyError, ValueError):
            until = None
        if until is None or until < local_start.date():
            flash("Choose the date the repeat ends (on or after the first meeting).", "warning")
            return redirect(url_for("book.location_calendar", location_id=loc.id, date=day_param))
        series = RecurringRoomBooking(
            operator_id=room.operator_id, room_id=room.id, user_id=(for_user or current_user).id,
            pattern=RecurrencePattern(request.form["repeat"]), start_time=local_start.time(),
            end_time=local_end.time(), start_date=local_start.date(), end_date=until, is_active=True)
        db.session.add(series)
        db.session.flush()
    try:
        b = create_room_booking(
            user=current_user, room=room, start=start, end=end,
            title=request.form.get("title"),
            attendees=request.form.get("attendees", 1, type=int),
            notes=request.form.get("notes"),
            for_user=for_user, waive_charge=waive_charge,
            recurring_booking_id=series.id if series else None,
        )
        msg = "Meeting booked."
        if series:
            msg = "Recurring meeting booked; later dates are created automatically each day."
        if b.credits_used:
            msg += f" Used {b.credits_used} credit(s)."
        if b.total_amount and b.total_amount > 0:
            msg += f" Charge {format_money(b.total_amount)}."
        elif waive_charge:
            msg += " No charge (waived)."
        flash(msg, "success")
    except BookingError as e:
        db.session.rollback()
        flash(str(e), "danger")
    return redirect(url_for("book.location_calendar", location_id=loc.id, date=day_param))


# ---------------------------------------------------------------- seats --

@booking_bp.route("/seats/<int:seat_id>", methods=["GET", "POST"])
@member_or_admin_required
def seat_book(seat_id: int):
    seat = Seat.query.get_or_404(seat_id)

    default_start = (now_local() + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0, tzinfo=None)
    default_end = default_start + timedelta(hours=4)

    ctx = {"seat": seat, "quote": None, "error": None,
           "start": default_start.strftime("%Y-%m-%dT%H:%M"),
           "end": default_end.strftime("%Y-%m-%dT%H:%M")}

    if request.method == "POST":
        action = request.form.get("action", "quote")
        try:
            start = parse_local_naive_to_utc(request.form["start"])
            end = parse_local_naive_to_utc(request.form["end"])
        except (KeyError, ValueError):
            flash("Invalid start or end time.", "danger")
            return render_template("booking/seat_book.html", **ctx)

        ctx["start"] = request.form["start"]
        ctx["end"] = request.form["end"]

        if action == "book":
            try:
                b = create_seat_booking(user=current_user, seat=seat, start=start, end=end,
                                        notes=request.form.get("notes"))
                flash(f"Seat booked. Total {format_money(b.total_amount)}.", "success")
                return redirect(url_for("member.bookings"))
            except BookingError as e:
                ctx["error"] = str(e)

        # Always show a quote
        if end > start:
            ctx["quote"] = quote_seat(seat, start, end)
            ctx["has_conflict"] = check_seat_conflict(seat.id, start, end, booker=current_user)

    return render_template("booking/seat_book.html", **ctx)


# ----------------------------------------------------- conference rooms --

@booking_bp.route("/rooms/<int:room_id>", methods=["GET", "POST"])
@member_or_admin_required
def room_book(room_id: int):
    room = ConferenceRoom.query.get_or_404(room_id)

    default_start = (now_local() + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0, tzinfo=None)
    default_end = default_start + timedelta(hours=1)

    recipients = []
    if current_user.is_admin:
        recipients = (User.query
                     .filter(User.role.in_([UserRole.EMPLOYEE, UserRole.INDIVIDUAL]), User.is_active.is_(True))
                     .order_by(User.full_name).all())

    ctx = {"room": room, "quote": None, "error": None, "recipients": recipients,
           "start": request.args.get("start") or default_start.strftime("%Y-%m-%dT%H:%M"),
           "end": request.args.get("end") or default_end.strftime("%Y-%m-%dT%H:%M")}

    if request.method == "POST":
        action = request.form.get("action", "quote")
        try:
            start = parse_local_naive_to_utc(request.form["start"])
            end = parse_local_naive_to_utc(request.form["end"])
        except (KeyError, ValueError):
            flash("Invalid start or end time.", "danger")
            return render_template("booking/room_book.html", **ctx)

        ctx["start"] = request.form["start"]
        ctx["end"] = request.form["end"]
        attendees = int(request.form.get("attendees", 1))
        title = request.form.get("title")
        notes = request.form.get("notes")

        for_user = None
        waive_charge = False
        if current_user.is_admin:
            recipient_id = request.form.get("for_user_id", type=int)
            if recipient_id:
                for_user = User.query.filter(
                    User.id == recipient_id, User.role.in_([UserRole.EMPLOYEE, UserRole.INDIVIDUAL]),
                ).first()
            waive_charge = bool(request.form.get("waive_charge"))
        booked_for = for_user or current_user

        if action == "book":
            try:
                b = create_room_booking(user=current_user, room=room, start=start, end=end,
                                        title=title, attendees=attendees, notes=notes,
                                        for_user=for_user, waive_charge=waive_charge)
                msg = f"Room booked. "
                if b.credits_used:
                    msg += f"Used {b.credits_used} credit(s). "
                if b.total_amount and b.total_amount > 0:
                    msg += f"Charge {format_money(b.total_amount)}."
                elif waive_charge:
                    msg += "No charge (waived)."
                flash(msg, "success")
                return redirect(url_for("member.bookings"))
            except BookingError as e:
                ctx["error"] = str(e)

        if end > start and not waive_charge:
            try:
                ctx["quote"] = quote_room(booked_for, room, start, end)
            except BookingError as e:
                ctx["error"] = str(e)
            ctx["has_conflict"] = check_room_conflict(room.id, start, end)
        elif end > start:
            ctx["has_conflict"] = check_room_conflict(room.id, start, end)

    return render_template("booking/room_book.html", **ctx)


# --------- waitlist + recurring room bookings ----------

@booking_bp.route("/rooms/<int:room_id>/waitlist", methods=["POST"])
@member_or_admin_required
def room_waitlist_join(room_id: int):
    from flask import g
    room = ConferenceRoom.query.get_or_404(room_id)
    try:
        start = parse_local_naive_to_utc(request.form["start"])
        end = parse_local_naive_to_utc(request.form["end"])
    except (KeyError, ValueError):
        flash("Invalid slot.", "warning")
        return redirect(url_for("book.room_book", room_id=room_id))
    from ...extensions import db as _db
    entry = RoomWaitlist(
        operator_id=getattr(g, "operator_id", None),
        room_id=room.id, user_id=current_user.id,
        start_at=start, end_at=end, status=WaitlistStatus.WAITING,
    )
    _db.session.add(entry); _db.session.commit()
    flash("You've been added to the waitlist. We'll email you if a slot opens up.", "info")
    return redirect(url_for("member.dashboard"))


@booking_bp.route("/rooms/<int:room_id>/recurring", methods=["POST"])
@member_or_admin_required
def room_recurring_create(room_id: int):
    from flask import g
    from datetime import date as _date, time as _time
    room = ConferenceRoom.query.get_or_404(room_id)
    try:
        pattern = RecurrencePattern(request.form.get("pattern", "weekly"))
        start_time = _time.fromisoformat(request.form["start_time"])
        end_time = _time.fromisoformat(request.form["end_time"])
        start_date = _date.fromisoformat(request.form["start_date"])
        end_date = _date.fromisoformat(request.form["end_date"])
    except (KeyError, ValueError):
        flash("Invalid recurring request.", "warning")
        return redirect(url_for("book.room_book", room_id=room_id))
    from ...extensions import db as _db
    rec = RecurringRoomBooking(
        operator_id=getattr(g, "operator_id", None),
        room_id=room.id, user_id=current_user.id,
        pattern=pattern, start_time=start_time, end_time=end_time,
        start_date=start_date, end_date=end_date, is_active=True,
    )
    _db.session.add(rec); _db.session.commit()
    flash("Recurring booking series saved. Individual slots will be created nightly.", "success")
    return redirect(url_for("member.dashboard"))
