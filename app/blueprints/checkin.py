"""Check-in pages: scan a location QR with your own phone, show your own QR to reception."""
from __future__ import annotations

from flask import Blueprint, Response, render_template, request
from flask_login import current_user, login_required

from ..extensions import db
from ..models import Location, UserRole
from ..models.attendance import METHOD_QR_RECEPTION, METHOD_QR_SELF
from ..services import attendance
from ..services.attendance import CheckinError
from ..utils.decorators import admin_required

checkin_bp = Blueprint("checkin", __name__)


@checkin_bp.app_template_filter("stay")
def stay_filter(minutes):
    return attendance.format_minutes(minutes)


def locations_for(user) -> list[Location]:
    """Locations this staff member can record attendance for."""
    q = Location.query.filter_by(is_active=True).order_by(Location.name)
    if user.role == UserRole.LOCATION_MANAGER and user.managed_location_id:
        q = q.filter(Location.id == user.managed_location_id)
    return q.all()


@checkin_bp.route("/pass")
@login_required
def pass_page():
    return render_template("checkin/pass.html", open_record=attendance.open_record(current_user.id))


@checkin_bp.route("/pass.png")
@login_required
def pass_png():
    url = attendance.external_url("checkin.member_scan", token=attendance.person_token(current_user))
    resp = Response(attendance.qr_png(url), mimetype="image/png")
    resp.headers["Cache-Control"] = "no-store"
    return resp


@checkin_bp.route("/member/<token>", methods=["GET", "POST"])
@admin_required
def member_scan(token: str):
    """Reception opens a person's QR: confirm to check them in or out."""
    try:
        person = attendance.user_from_token(token)
    except CheckinError as e:
        return render_template("checkin/member.html", error=str(e), person=None), 400
    locations = locations_for(current_user)
    record = attendance.open_record(person.id)
    done = None
    if request.method == "POST":
        location = next((l for l in locations if l.id == request.form.get("location_id", type=int)), None)
        if location is None and locations:
            location = locations[0]
        record, done = attendance.toggle(person, location=location, method=METHOD_QR_RECEPTION, recorded_by=current_user)
        db.session.commit()
    return render_template("checkin/member.html", error=None, person=person, locations=locations,
                           record=record, done=done, open_record=attendance.open_record(person.id))


@checkin_bp.route("/<token>", methods=["GET", "POST"])
@login_required
def scan(token: str):
    """A person scanned a location QR with their own phone."""
    try:
        location = attendance.location_from_token(token)
    except CheckinError as e:
        return render_template("checkin/scan.html", error=str(e), location=None), 400
    done = None
    record = attendance.open_record(current_user.id)
    if request.method == "POST":
        record, done = attendance.toggle(current_user, location=location, method=METHOD_QR_SELF)
        db.session.commit()
    return render_template("checkin/scan.html", error=None, location=location, record=record, done=done,
                           open_record=attendance.open_record(current_user.id))
