"""Attendance and QR check-in, with no hardware beyond a phone camera.

Two signed QR codes drive it:
* a location code (printed poster, or a rotating one on a screen): people scan it with their own phone,
  which opens a check-in page on the operator's own address;
* a personal code shown on the person's phone: reception scans it with the browser camera.

Operator records carry the operator's id. The Platform team's records have no operator and are invisible to
operators; Platform queries are not filtered automatically, so they go through ``records_query``.
"""
from __future__ import annotations

import io
import secrets
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import qrcode
from flask import current_app, g, request, url_for
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import case, func

from ..extensions import db
from ..models import AttendanceRecord, Location, Operator, User

OPERATOR, PLATFORM = "operator", "platform"
ROTATING_SECONDS = 180       # a code on a display screen is good for three minutes
PERSON_SECONDS = 900         # a personal code is good for fifteen minutes
STALE_AFTER = timedelta(hours=16)   # a check-in never closed after this long is "no check-out", not "in now"
DEFAULT_TZ = "Asia/Kolkata"


class CheckinError(Exception):
    """A scan that cannot be used, with a message safe to show the person."""


# --------------------------------------------------------------- tokens --

def _signer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt="hub1z-checkin")


def ensure_key(location: Location) -> str:
    if not location.checkin_key:
        location.checkin_key = secrets.token_hex(4)
        db.session.flush()
    return location.checkin_key


def regenerate_key(location: Location) -> str:
    """Retire every printed poster for this location."""
    location.checkin_key = secrets.token_hex(4)
    db.session.flush()
    return location.checkin_key


# Short list payloads keep the QR code sparse: ["l", operator, location, key, rotating] and ["u", operator, user].
def location_token(location: Location, rotating: bool = False) -> str:
    return _signer().dumps(["l", location.operator_id, location.id, ensure_key(location), int(rotating)])


def person_token(user: User) -> str:
    return _signer().dumps(["u", user.operator_id, user.id])


def _read(token: str, kind: str) -> list:
    signer = _signer()
    try:
        data = signer.loads(token)
    except BadSignature:
        raise CheckinError("This QR code is not valid.")
    if not isinstance(data, list) or len(data) < 3 or data[0] != kind:
        raise CheckinError("This QR code is not valid here.")
    rotating = kind == "l" and len(data) > 4 and data[4]
    max_age = PERSON_SECONDS if kind == "u" else (ROTATING_SECONDS if rotating else None)
    if max_age is not None:
        try:
            signer.loads(token, max_age=max_age)
        except SignatureExpired:
            raise CheckinError("This QR code has expired. Please scan the latest one.")
    if data[1] != getattr(g, "operator_id", None):
        raise CheckinError("This QR code belongs to a different workspace.")
    return data


def location_from_token(token: str) -> Location:
    data = _read(token, "l")
    loc = Location.query.filter_by(id=data[2]).first() if len(data) > 3 else None
    if loc is None or not loc.is_active or not loc.checkin_key or loc.checkin_key != data[3]:
        raise CheckinError("This QR code is no longer valid. Ask reception for the current one.")
    return loc


def user_from_token(token: str) -> User:
    data = _read(token, "u")
    user = User.query.filter_by(id=data[2]).first()
    if user is None or not user.is_active:
        raise CheckinError("This person could not be found.")
    return user


def external_url(endpoint: str, **values) -> str:
    """Absolute link on the current host; https in production."""
    scheme = request.scheme if (current_app.debug or current_app.testing) else "https"
    return url_for(endpoint, _external=True, _scheme=scheme, **values)


def qr_png(text: str) -> bytes:
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=10, border=2)
    qr.add_data(text)
    qr.make(fit=True)
    buf = io.BytesIO()
    qr.make_image(fill_color="#151a2d", back_color="white").save(buf, format="PNG")
    return buf.getvalue()


# ------------------------------------------------------------- recording --

def open_record(user_id: int, now: datetime | None = None) -> AttendanceRecord | None:
    now = now or datetime.utcnow()
    return (AttendanceRecord.query
            .filter(AttendanceRecord.user_id == user_id, AttendanceRecord.check_out_at.is_(None),
                    AttendanceRecord.check_in_at >= now - STALE_AFTER)
            .order_by(AttendanceRecord.check_in_at.desc()).first())


def toggle(user: User, *, location: Location | None, method: str, recorded_by: User | None = None,
           now: datetime | None = None) -> tuple[AttendanceRecord, str]:
    """Check the person in, or out when they are already in. Returns (record, 'in' | 'out')."""
    now = now or datetime.utcnow()
    record = open_record(user.id, now)
    if record is not None:
        record.check_out_at = now
        return record, "out"
    record = AttendanceRecord(user_id=user.id, operator_id=user.operator_id,
                              location_id=location.id if location else None, check_in_at=now, method=method,
                              recorded_by_id=recorded_by.id if recorded_by and recorded_by.id != user.id else None)
    db.session.add(record)
    return record, "in"


# --------------------------------------------------------------- queries --

def records_query(scope: str):
    if scope == PLATFORM:
        return AttendanceRecord.query.filter(AttendanceRecord.operator_id.is_(None))
    return AttendanceRecord.query.filter(AttendanceRecord.operator_id == g.operator_id)


def zone(operator: Operator | None = None) -> ZoneInfo:
    name = getattr(operator, "timezone", None) or DEFAULT_TZ
    try:
        return ZoneInfo(name)
    except Exception:  # unknown zone name in settings
        return ZoneInfo(DEFAULT_TZ)


def day_bounds(tz: ZoneInfo, day: date) -> tuple[datetime, datetime]:
    """Start and end of a local day as naive UTC datetimes (how the database stores them)."""
    start = datetime.combine(day, time.min, tzinfo=tz).astimezone(timezone.utc).replace(tzinfo=None)
    return start, start + timedelta(days=1)


def local_today(tz: ZoneInfo, now: datetime | None = None) -> date:
    now = now or datetime.utcnow()
    return now.replace(tzinfo=timezone.utc).astimezone(tz).date()


def summary(scope: str, tz: ZoneInfo, now: datetime | None = None, location_ids: list[int] | None = None) -> dict:
    """In-now list, today's count, people this week, average stay and a 14-day series."""
    now = now or datetime.utcnow()
    today = local_today(tz, now)
    today_start, _ = day_bounds(tz, today)
    base = records_query(scope)
    if location_ids is not None:
        base = base.filter(AttendanceRecord.location_id.in_(location_ids))
    week_start, _ = day_bounds(tz, today - timedelta(days=6))
    series_start, _ = day_bounds(tz, today - timedelta(days=13))
    recent = base.filter(AttendanceRecord.check_in_at >= series_start).all()
    in_now = [r for r in recent if r.check_out_at is None and r.check_in_at >= now - STALE_AFTER]
    week = [r for r in recent if r.check_in_at >= week_start]
    stays = [r.minutes for r in week if r.minutes is not None]
    counts: dict[date, int] = {today - timedelta(days=i): 0 for i in range(13, -1, -1)}
    for r in recent:
        d = r.check_in_at.replace(tzinfo=timezone.utc).astimezone(tz).date()
        if d in counts:
            counts[d] += 1
    return {
        "in_now": sorted(in_now, key=lambda r: r.check_in_at),
        "today": sum(1 for r in recent if r.check_in_at >= today_start),
        "people_week": len({r.user_id for r in week}),
        "avg_minutes": round(sum(stays) / len(stays)) if stays else None,
        "series": list(counts.items()),
        "today_date": today,
    }


def rollup(tz: ZoneInfo, now: datetime | None = None) -> list[dict]:
    """Platform view: head-counts per operator, no names."""
    now = now or datetime.utcnow()
    today = local_today(tz, now)
    today_start, _ = day_bounds(tz, today)
    week_start, _ = day_bounds(tz, today - timedelta(days=6))
    month_start, _ = day_bounds(tz, today - timedelta(days=29))
    A = AttendanceRecord
    rows = (db.session.query(
                A.operator_id,
                func.sum(case((A.check_in_at >= today_start, 1), else_=0)),
                func.sum(case((A.check_in_at >= week_start, 1), else_=0)),
                func.count(A.id),
                func.sum(case(((A.check_out_at.is_(None)) & (A.check_in_at >= now - STALE_AFTER), 1), else_=0)))
            .filter(A.operator_id.isnot(None), A.check_in_at >= month_start)
            .group_by(A.operator_id).all())
    by_id = {r[0]: r for r in rows}
    out = []
    for op in Operator.query.order_by(Operator.name).all():
        r = by_id.get(op.id)
        out.append({"operator": op, "today": int(r[1] or 0) if r else 0, "week": int(r[2] or 0) if r else 0,
                    "month": int(r[3] or 0) if r else 0, "in_now": int(r[4] or 0) if r else 0})
    return out


def format_minutes(minutes: int | None) -> str:
    if minutes is None:
        return "—"
    h, m = divmod(int(minutes), 60)
    return f"{h}h {m:02d}m" if h else f"{m}m"
