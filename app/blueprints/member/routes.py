"""Member portal (employees & individual users)."""
from __future__ import annotations

from datetime import datetime, date
from io import BytesIO

import qrcode

from flask import Blueprint, render_template, redirect, url_for, flash, request, send_file, abort, g
from flask_login import current_user, login_required

from ...extensions import db
from ...models import (
    SeatBooking, RoomBooking, BookingStatus, Invoice, Subscription, SubscriptionStatus,
    Location, DayPass, DayPassStatus, User, UserRole,
)
from ...services.booking_service import cancel_booking, BookingError
from ...utils.decorators import member_required, member_or_admin_required

member_bp = Blueprint("member", __name__, template_folder="../../templates")


@member_bp.route("/")
@member_required
def dashboard():
    now = datetime.utcnow()

    upcoming_seats = (SeatBooking.query.filter_by(user_id=current_user.id)
                      .filter(SeatBooking.end_at >= now,
                              SeatBooking.status.in_([BookingStatus.CONFIRMED, BookingStatus.CHECKED_IN]))
                      .order_by(SeatBooking.start_at).limit(10).all())
    upcoming_rooms = (RoomBooking.query.filter_by(user_id=current_user.id)
                      .filter(RoomBooking.end_at >= now,
                              RoomBooking.status.in_([BookingStatus.CONFIRMED, BookingStatus.CHECKED_IN]))
                      .order_by(RoomBooking.start_at).limit(10).all())
    subs = Subscription.query.filter(
        (Subscription.user_id == current_user.id) |
        (Subscription.company_id == current_user.company_id),
        Subscription.status == SubscriptionStatus.ACTIVE,
    ).all()
    credits = sum(s.meeting_credits_balance for s in subs)
    invoices = (Invoice.query
                .filter((Invoice.user_id == current_user.id) |
                        (Invoice.company_id == current_user.company_id))
                .order_by(Invoice.issued_at.desc().nullslast()).limit(5).all())
    return render_template(
        "member/dashboard.html",
        upcoming_seats=upcoming_seats,
        upcoming_rooms=upcoming_rooms,
        credits=credits,
        subscriptions=subs,
        invoices=invoices,
    )


@member_bp.route("/bookings")
@member_required
def bookings():
    seat_bookings = (SeatBooking.query.filter_by(user_id=current_user.id)
                     .order_by(SeatBooking.start_at.desc()).limit(100).all())
    room_bookings = (RoomBooking.query.filter_by(user_id=current_user.id)
                     .order_by(RoomBooking.start_at.desc()).limit(100).all())
    return render_template("member/bookings.html",
                           seat_bookings=seat_bookings, room_bookings=room_bookings)


@member_bp.route("/bookings/seat/<int:booking_id>/cancel", methods=["POST"])
@member_required
def cancel_seat_booking(booking_id: int):
    booking = SeatBooking.query.get_or_404(booking_id)
    try:
        cancel_booking(booking, current_user)
        flash("Booking cancelled.", "info")
    except BookingError as e:
        flash(str(e), "warning")
    return redirect(url_for("member.bookings"))


@member_bp.route("/bookings/room/<int:booking_id>/cancel", methods=["POST"])
@member_required
def cancel_room_booking(booking_id: int):
    booking = RoomBooking.query.get_or_404(booking_id)
    try:
        cancel_booking(booking, current_user)
        flash("Booking cancelled.", "info")
    except BookingError as e:
        flash(str(e), "warning")
    return redirect(url_for("member.bookings"))


# ------- day passes -------

@member_bp.route("/day-passes")
@member_or_admin_required
def day_passes():
    if current_user.is_admin:
        passes = (DayPass.query.order_by(DayPass.pass_date.desc()).limit(100).all())
        recipients = (User.query
                     .filter(User.role.in_([UserRole.EMPLOYEE, UserRole.INDIVIDUAL]), User.is_active.is_(True))
                     .order_by(User.full_name).all())
    else:
        passes = (DayPass.query.filter_by(user_id=current_user.id)
                                .order_by(DayPass.pass_date.desc()).limit(60).all())
        recipients = []
    locations = Location.query.filter_by(is_active=True).order_by(Location.name).all()
    return render_template("member/day_passes.html", passes=passes, locations=locations,
                           recipients=recipients, today=date.today().isoformat())


@member_bp.route("/day-passes/new", methods=["POST"])
@member_or_admin_required
def day_pass_new():
    location_id = int(request.form.get("location_id", 0))
    loc = Location.query.get_or_404(location_id)
    pass_date_str = request.form.get("pass_date") or ""
    try:
        pd = date.fromisoformat(pass_date_str) if pass_date_str else date.today()
    except ValueError:
        pd = date.today()

    recipient_id = request.form.get("user_id", type=int)
    recipient = current_user
    if current_user.is_admin and recipient_id:
        # Operators can issue a day pass on behalf of any individual/employee
        # in their own workspace — never someone else's tenant.
        recipient = User.query.filter(
            User.id == recipient_id,
            User.role.in_([UserRole.EMPLOYEE, UserRole.INDIVIDUAL]),
        ).first()
        if recipient is None:
            flash("Pick a valid recipient for the day pass.", "warning")
            return redirect(url_for("member.day_passes"))

    dp = DayPass(
        tenant_id=getattr(g, "tenant_id", None),
        user_id=recipient.id,
        location_id=loc.id,
        pass_date=pd,
        code=DayPass.new_code(),
        status=DayPassStatus.ISSUED,
    )
    db.session.add(dp); db.session.commit()
    flash(f"Day pass issued for {recipient.full_name if recipient.id != current_user.id else 'you'} "
         f"at {loc.name} on {pd.isoformat()}.", "success")
    return redirect(url_for("member.day_pass_detail", pass_id=dp.id))


@member_bp.route("/day-passes/<int:pass_id>")
@member_or_admin_required
def day_pass_detail(pass_id: int):
    q = DayPass.query.filter_by(id=pass_id)
    if not current_user.is_admin:
        q = q.filter_by(user_id=current_user.id)
    dp = q.first_or_404()
    return render_template("member/day_pass_detail.html", dp=dp)


@member_bp.route("/day-passes/<int:pass_id>/qr.png")
@member_or_admin_required
def day_pass_qr(pass_id: int):
    q = DayPass.query.filter_by(id=pass_id)
    if not current_user.is_admin:
        q = q.filter_by(user_id=current_user.id)
    dp = q.first_or_404()
    img = qrcode.make(dp.code)
    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return send_file(buf, mimetype="image/png",
                     download_name=f"daypass-{dp.code}.png")
