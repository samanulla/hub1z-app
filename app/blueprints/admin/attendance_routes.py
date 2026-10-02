"""Operator attendance: who is in, the log, location QR codes, the reception scanner and manual check-in."""
from __future__ import annotations

import csv
import io
from datetime import date, datetime, timezone, timedelta

from flask import (Response, abort, flash, g, jsonify, redirect, render_template, request, url_for)
from flask_login import current_user

from ...extensions import db
from ...models import AttendanceRecord, Location, User, UserRole
from ...models.attendance import METHOD_MANUAL, METHOD_QR_RECEPTION
from ...services import attendance as att
from ...services.attendance import CheckinError, OPERATOR
from ...services.entitlements import has_feature
from ...utils.decorators import admin_required, manager_or_super_required
from ..checkin import locations_for

STAFF_ROLES = [UserRole.SUPER_ADMIN, UserRole.MANAGER, UserRole.LOCATION_MANAGER]
MEMBER_ROLES = [UserRole.COMPANY_ADMIN, UserRole.EMPLOYEE, UserRole.INDIVIDUAL]


def _parse_day(value: str | None, default: date) -> date:
    try:
        return date.fromisoformat(value) if value else default
    except ValueError:
        return default


def register_attendance_routes(bp):

    def visible_locations() -> list[Location]:
        return locations_for(current_user)

    def location_or_404(location_id: int) -> Location:
        loc = next((l for l in visible_locations() if l.id == location_id), None)
        if loc is None:
            abort(404)
        return loc

    def filtered(start: date, end: date, location_id: int | None, q: str, who: str):
        tz = att.zone(g.operator)
        start_utc, _ = att.day_bounds(tz, start)
        _, end_utc = att.day_bounds(tz, end)
        qry = (att.records_query(OPERATOR).join(User, AttendanceRecord.user_id == User.id)
               .filter(AttendanceRecord.check_in_at >= start_utc, AttendanceRecord.check_in_at < end_utc))
        allowed = [l.id for l in visible_locations()]
        if current_user.role == UserRole.LOCATION_MANAGER:
            qry = qry.filter(AttendanceRecord.location_id.in_(allowed))
        if location_id:
            qry = qry.filter(AttendanceRecord.location_id == location_id)
        if q:
            like = f"%{q}%"
            qry = qry.filter(User.full_name.ilike(like) | User.email.ilike(like))
        if who == "staff":
            qry = qry.filter(User.role.in_(STAFF_ROLES))
        elif who == "members":
            qry = qry.filter(User.role.in_(MEMBER_ROLES))
        return qry.order_by(AttendanceRecord.check_in_at.desc())

    # ------------------------------------------------------------- log --
    @bp.route("/attendance")
    @admin_required
    def attendance():
        tz = att.zone(g.operator)
        today = att.local_today(tz)
        start = _parse_day(request.args.get("from"), today)
        end = _parse_day(request.args.get("to"), start)
        if end < start:
            start, end = end, start
        if not has_feature(g.operator, "attendance_reports"):
            start = max(start, today - timedelta(days=6))
            end = max(start, min(end, today))
        location_id = request.args.get("location", type=int)
        q = (request.args.get("q") or "").strip()
        who = request.args.get("who", "all")
        rows = filtered(start, end, location_id, q, who).limit(500).all()
        allowed = [l.id for l in visible_locations()]
        stats = att.summary(OPERATOR, tz, location_ids=allowed if current_user.role == UserRole.LOCATION_MANAGER else None)
        if not has_feature(g.operator, "attendance_reports"):
            stats["series"] = stats["series"][-7:]
        people = (User.query.filter(User.operator_id == g.operator_id, User.is_active.is_(True),
                                    User.role.in_(STAFF_ROLES + MEMBER_ROLES))
                  .order_by(User.full_name).limit(500).all())
        peak = max((n for _, n in stats["series"]), default=0) or 1
        return render_template("attendance/operator.html", rows=rows, stats=stats, peak=peak, tzname=tz.key,
                               locations=visible_locations(), people=people, start=start, end=end, today=today,
                               location_id=location_id, q=q, who=who, staff_roles=[r.value for r in STAFF_ROLES])

    @bp.route("/attendance/export.csv")
    @admin_required
    def attendance_export():
        tz = att.zone(g.operator)
        today = att.local_today(tz)
        start = _parse_day(request.args.get("from"), today)
        end = _parse_day(request.args.get("to"), start)
        rows = filtered(start, end, request.args.get("location", type=int), (request.args.get("q") or "").strip(),
                        request.args.get("who", "all")).limit(20000).all()
        out = io.StringIO()
        w = csv.writer(out)
        w.writerow(["Date", "Name", "Role", "Location", "Check in", "Check out", "Minutes", "How"])
        for r in rows:
            li = r.check_in_at.replace(tzinfo=timezone.utc).astimezone(tz)
            lo = r.check_out_at.replace(tzinfo=timezone.utc).astimezone(tz) if r.check_out_at else None
            w.writerow([li.strftime("%Y-%m-%d"), r.user.full_name, r.user.role.value, r.location.name if r.location else "",
                        li.strftime("%H:%M"), lo.strftime("%H:%M") if lo else "", r.minutes if r.minutes is not None else "",
                        r.method_label])
        return Response(out.getvalue(), mimetype="text/csv",
                        headers={"Content-Disposition": "attachment; filename=attendance.csv"})

    @bp.route("/attendance/manual", methods=["POST"])
    @admin_required
    def attendance_manual():
        person = User.query.filter(User.id == request.form.get("user_id", type=int),
                                   User.operator_id == g.operator_id).first_or_404()
        location = next((l for l in visible_locations() if l.id == request.form.get("location_id", type=int)), None)
        if location is None and visible_locations():
            location = visible_locations()[0]
        record, action = att.toggle(person, location=location, method=METHOD_MANUAL, recorded_by=current_user)
        db.session.commit()
        flash(f"{person.full_name} checked {action}.", "success")
        return redirect(url_for("admin.attendance"))

    @bp.route("/attendance/<int:record_id>/checkout", methods=["POST"])
    @admin_required
    def attendance_checkout(record_id: int):
        record = att.records_query(OPERATOR).filter(AttendanceRecord.id == record_id).first_or_404()
        if record.check_out_at is None:
            record.check_out_at = datetime.utcnow()
            db.session.commit()
            flash(f"{record.user.full_name} checked out.", "success")
        return redirect(request.referrer or url_for("admin.attendance"))

    # --------------------------------------------------- reception scan --
    @bp.route("/attendance/scan")
    @admin_required
    def attendance_scan():
        return render_template("attendance/scan.html", locations=visible_locations())

    @bp.route("/attendance/scan", methods=["POST"])
    @admin_required
    def attendance_scan_post():
        data = request.get_json(silent=True) or {}
        token = str(data.get("token") or "")
        try:
            person = att.user_from_token(token)
        except CheckinError as e:
            return jsonify(ok=False, error=str(e)), 400
        location = next((l for l in visible_locations() if l.id == data.get("location_id")), None)
        if location is None and visible_locations():
            location = visible_locations()[0]
        record, action = att.toggle(person, location=location, method=METHOD_QR_RECEPTION, recorded_by=current_user)
        db.session.commit()
        return jsonify(ok=True, action=action, name=person.full_name, role=person.role.value.replace("_", " ").title(),
                       minutes=att.format_minutes(record.minutes) if action == "out" else None)

    # ------------------------------------------------------- QR codes --
    @bp.route("/attendance/qr")
    @admin_required
    def attendance_qr():
        return render_template("attendance/qr_list.html", locations=visible_locations())

    @bp.route("/attendance/qr/<int:location_id>")
    @admin_required
    def attendance_poster(location_id: int):
        loc = location_or_404(location_id)
        att.ensure_key(loc)
        db.session.commit()
        return render_template("attendance/poster.html", location=loc)

    @bp.route("/attendance/qr/<int:location_id>.png")
    @admin_required
    def attendance_qr_png(location_id: int):
        loc = location_or_404(location_id)
        token = att.location_token(loc, rotating=request.args.get("rotating") == "1")
        db.session.commit()
        png = att.qr_png(att.external_url("checkin.scan", token=token))
        resp = Response(png, mimetype="image/png")
        resp.headers["Cache-Control"] = "no-store"
        return resp

    @bp.route("/attendance/qr/<int:location_id>/regenerate", methods=["POST"])
    @manager_or_super_required
    def attendance_qr_regenerate(location_id: int):
        loc = location_or_404(location_id)
        att.regenerate_key(loc)
        db.session.commit()
        flash(f"New QR code created for {loc.name}. Printed posters of the old code no longer work.", "success")
        return redirect(url_for("admin.attendance_qr"))

    @bp.route("/attendance/screen/<int:location_id>")
    @admin_required
    def attendance_screen(location_id: int):
        return render_template("attendance/screen.html", location=location_or_404(location_id),
                               refresh_seconds=att.ROTATING_SECONDS // 3)
