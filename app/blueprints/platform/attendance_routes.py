"""Platform attendance: the Hub1z team's own check-ins, and head-counts across operators (no names)."""
from __future__ import annotations

from datetime import date, datetime

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user

from ...extensions import db
from ...models import AttendanceRecord
from ...models.attendance import METHOD_WEB
from ...services import attendance as att
from ...services.attendance import PLATFORM
from ...utils.decorators import platform_owner_required, platform_staff_required


def _parse_day(value: str | None, default: date) -> date:
    try:
        return date.fromisoformat(value) if value else default
    except ValueError:
        return default


def register_attendance_routes(bp):

    @bp.route("/attendance")
    @platform_staff_required
    def attendance():
        tz = att.zone(None)
        today = att.local_today(tz)
        is_owner = current_user.is_platform_owner
        can_roll_up = is_owner or current_user.has_platform_permission("reports")
        start = _parse_day(request.args.get("from"), today)
        end = _parse_day(request.args.get("to"), start)
        if end < start:
            start, end = end, start
        start_utc, _ = att.day_bounds(tz, start)
        _, end_utc = att.day_bounds(tz, end)
        qry = att.records_query(PLATFORM).filter(AttendanceRecord.check_in_at >= start_utc,
                                                 AttendanceRecord.check_in_at < end_utc)
        if not is_owner:
            qry = qry.filter(AttendanceRecord.user_id == current_user.id)
        rows = qry.order_by(AttendanceRecord.check_in_at.desc()).limit(500).all()
        mine = att.open_record(current_user.id)
        stats = att.summary(PLATFORM, tz) if is_owner else None
        peak = max((n for _, n in stats["series"]), default=0) if stats else 0
        peak = peak or 1
        return render_template("attendance/platform.html", rows=rows, mine=mine, stats=stats, peak=peak, tzname=tz.key,
                               start=start, end=end, today=today, is_owner=is_owner,
                               roll_up=att.rollup(tz) if can_roll_up else None, can_roll_up=can_roll_up)

    @bp.route("/attendance/toggle", methods=["POST"])
    @platform_staff_required
    def attendance_toggle():
        record, action = att.toggle(current_user, location=None, method=METHOD_WEB)
        db.session.commit()
        flash("Checked in." if action == "in" else f"Checked out. Time today: {att.format_minutes(record.minutes)}.", "success")
        return redirect(url_for("platform.attendance"))

    @bp.route("/attendance/<int:record_id>/checkout", methods=["POST"])
    @platform_owner_required
    def attendance_checkout(record_id: int):
        record = att.records_query(PLATFORM).filter(AttendanceRecord.id == record_id).first_or_404()
        if record.check_out_at is None:
            record.check_out_at = datetime.utcnow()
            db.session.commit()
            flash(f"{record.user.full_name} checked out.", "success")
        return redirect(url_for("platform.attendance"))
