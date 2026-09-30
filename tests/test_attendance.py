"""QR attendance for operators (members and staff) and for the Platform team."""
import os
import time

os.environ.setdefault("FLASK_ENV", "testing")

from itsdangerous import TimestampSigner, URLSafeTimedSerializer

from app.cli import PERSONA_PASSWORD
from app.extensions import db
from app.models import AttendanceRecord, Location, Operator, User
from tests.test_role_paths import APEX, DEMO, OTHER, OWNER_PASSWORD, _login, _seeded_app


def _client(app, host, email, password):
    c = app.test_client()
    assert _login(c, host, email, password).status_code == 302, email
    return c


def _get(c, host, path):
    return c.get(path, headers={"Host": host})


def _signer(app):
    return URLSafeTimedSerializer(app.config["SECRET_KEY"], salt="hub1z-checkin")


def _ids(app, host, email="employee@acmeco.com"):
    with app.app_context():
        op = Operator.query.filter_by(primary_domain=host).one()
        loc = Location.query.execution_options(skip_operator_filter=True).filter_by(operator_id=op.id).first()
        user = User.query.execution_options(skip_operator_filter=True).filter_by(operator_id=op.id, email=email).first()
        return op.id, loc.id if loc else None, user.id if user else None, user.full_name if user else None


def _location_token(app, host, rotating=False):
    """The same token the poster encodes; the poster route makes sure the location has its key."""
    op_id, loc_id, _, _ = _ids(app, host)
    with app.app_context():
        key = Location.query.execution_options(skip_operator_filter=True).get(loc_id).checkin_key
    assert key, "open the poster first"
    return _signer(app).dumps(["l", op_id, loc_id, key, int(rotating)])


def _person_token(app, host, email="employee@acmeco.com"):
    op_id, _, user_id, _ = _ids(app, host, email)
    return _signer(app).dumps(["u", op_id, user_id])


def _records(app, **filters):
    with app.app_context():
        return AttendanceRecord.query.execution_options(skip_operator_filter=True).filter_by(**filters).all()


def _open_poster(app, owner, host=DEMO):
    _, loc_id, _, _ = _ids(app, host)
    assert _get(owner, host, f"/admin/attendance/qr/{loc_id}").status_code == 200
    png = _get(owner, host, f"/admin/attendance/qr/{loc_id}.png")
    assert png.status_code == 200 and png.mimetype == "image/png" and png.data[:4] == b"\x89PNG"
    return loc_id


def test_member_scans_the_location_qr_to_check_in_and_out():
    app, _ = _seeded_app()
    owner = _client(app, DEMO, "owner@demospace.com", PERSONA_PASSWORD)
    _open_poster(app, owner)
    token = _location_token(app, DEMO)
    employee = _client(app, DEMO, "employee@acmeco.com", PERSONA_PASSWORD)

    page = _get(employee, DEMO, f"/checkin/{token}")
    assert page.status_code == 200 and b"Check in" in page.data and b"Check out" not in page.data
    assert employee.post(f"/checkin/{token}", headers={"Host": DEMO}).status_code == 200
    rows = _records(app)
    assert len(rows) == 1 and rows[0].method == "qr_self" and rows[0].check_out_at is None and rows[0].location_id

    assert b"Check out" in _get(employee, DEMO, f"/checkin/{token}").data
    out = employee.post(f"/checkin/{token}", headers={"Host": DEMO})
    assert b"checked out" in out.data
    assert _records(app)[0].check_out_at is not None and len(_records(app)) == 1


def test_a_code_that_is_tampered_expired_or_for_another_workspace_is_refused():
    app, _ = _seeded_app()
    owner = _client(app, DEMO, "owner@demospace.com", PERSONA_PASSWORD)
    loc_id = _open_poster(app, owner)
    token = _location_token(app, DEMO)
    employee = _client(app, DEMO, "employee@acmeco.com", PERSONA_PASSWORD)

    bad = employee.post(f"/checkin/{token[:-3]}abc", headers={"Host": DEMO})
    assert bad.status_code == 400 and b"not valid" in bad.data

    # a rotating code older than three minutes
    real = TimestampSigner.get_timestamp
    TimestampSigner.get_timestamp = lambda self: int(time.time()) - 1000
    try:
        old = _location_token(app, DEMO, rotating=True)
    finally:
        TimestampSigner.get_timestamp = real
    expired = employee.post(f"/checkin/{old}", headers={"Host": DEMO})
    assert expired.status_code == 400 and b"expired" in expired.data
    assert _records(app) == []

    # the demo space's code scanned by someone at the other operator
    other = _client(app, OTHER, "owner@otherspace.com", PERSONA_PASSWORD)
    wrong = other.post(f"/checkin/{token}", headers={"Host": OTHER})
    assert wrong.status_code == 400 and b"different workspace" in wrong.data

    # a fresh poster code retires the old one
    assert owner.post(f"/admin/attendance/qr/{loc_id}/regenerate", headers={"Host": DEMO}).status_code == 302
    old_poster = employee.post(f"/checkin/{token}", headers={"Host": DEMO})
    assert old_poster.status_code == 400 and b"no longer valid" in old_poster.data
    assert _records(app) == []


def test_reception_scans_a_members_qr():
    app, _ = _seeded_app()
    owner = _client(app, DEMO, "owner@demospace.com", PERSONA_PASSWORD)
    _, loc_id, _, name = _ids(app, DEMO)
    token = _person_token(app, DEMO)
    js = {"Host": DEMO, "Accept": "application/json"}

    first = owner.post("/admin/attendance/scan", json={"token": token, "location_id": loc_id}, headers=js)
    assert first.status_code == 200 and first.json["ok"] and first.json["action"] == "in" and first.json["name"] == name
    assert _records(app)[0].method == "qr_reception" and _records(app)[0].recorded_by_id
    second = owner.post("/admin/attendance/scan", json={"token": token, "location_id": loc_id}, headers=js)
    assert second.json["action"] == "out" and second.json["minutes"]

    assert owner.post("/admin/attendance/scan", json={"token": "junk"}, headers=js).status_code == 400
    other_token = _person_token(app, OTHER, "owner@otherspace.com")
    assert owner.post("/admin/attendance/scan", json={"token": other_token}, headers=js).status_code == 400
    employee = _client(app, DEMO, "employee@acmeco.com", PERSONA_PASSWORD)
    assert employee.post("/admin/attendance/scan", json={"token": token}, headers=js).status_code == 403
    assert b"getUserMedia" in _get(owner, DEMO, "/admin/attendance/scan").data


def test_member_pass_and_the_phone_camera_route_for_reception():
    app, _ = _seeded_app()
    employee = _client(app, DEMO, "employee@acmeco.com", PERSONA_PASSWORD)
    assert b"My check-in QR" in _get(employee, DEMO, "/checkin/pass").data
    png = _get(employee, DEMO, "/checkin/pass.png")
    assert png.mimetype == "image/png" and png.headers["Cache-Control"] == "no-store"
    token = _person_token(app, DEMO)
    assert _get(employee, DEMO, f"/checkin/member/{token}").status_code == 403  # staff only
    owner = _client(app, DEMO, "owner@demospace.com", PERSONA_PASSWORD)
    assert b"Check in" in _get(owner, DEMO, f"/checkin/member/{token}").data
    done = owner.post(f"/checkin/member/{token}", headers={"Host": DEMO})
    assert b"Checked in" in done.data and len(_records(app)) == 1


def test_attendance_page_lists_who_is_in_and_the_log():
    app, _ = _seeded_app()
    owner = _client(app, DEMO, "owner@demospace.com", PERSONA_PASSWORD)
    _, loc_id, user_id, name = _ids(app, DEMO)
    owner.post("/admin/attendance/manual", data={"user_id": user_id, "location_id": loc_id}, headers={"Host": DEMO})
    page = _get(owner, DEMO, "/admin/attendance").data.decode()
    assert name in page and "In the space now" in page and "Marked by staff" in page
    record_id = _records(app)[0].id
    assert owner.post(f"/admin/attendance/{record_id}/checkout", headers={"Host": DEMO}).status_code == 302
    assert _records(app)[0].check_out_at is not None
    csv_out = _get(owner, DEMO, "/admin/attendance/export.csv")
    assert csv_out.mimetype == "text/csv" and name.encode() in csv_out.data
    # members cannot see the team's attendance
    employee = _client(app, DEMO, "employee@acmeco.com", PERSONA_PASSWORD)
    assert _get(employee, DEMO, "/admin/attendance").status_code == 403


def test_platform_team_attendance_and_head_counts_without_names():
    app, _ = _seeded_app()
    owner = _client(app, DEMO, "owner@demospace.com", PERSONA_PASSWORD)
    _, loc_id, user_id, name = _ids(app, DEMO)
    owner.post("/admin/attendance/manual", data={"user_id": user_id, "location_id": loc_id}, headers={"Host": DEMO})

    platform = _client(app, APEX, "admin@hub1z.com", OWNER_PASSWORD)
    assert b"You are not checked in" in _get(platform, APEX, "/platform/attendance").data
    assert platform.post("/platform/attendance/toggle", headers={"Host": APEX}).status_code == 302
    page = _get(platform, APEX, "/platform/attendance").data.decode()
    assert "You are checked in" in page and "Across operator spaces" in page and "Demo Space" in page
    assert name not in page  # head-counts only
    assert [r.operator_id for r in _records(app) if r.user_id != user_id] == [None]

    # the operator never sees the Platform team's check-in
    assert b"Platform Owner" not in _get(owner, DEMO, "/admin/attendance").data
    # and the platform page is not reachable from an operator's host
    assert _get(owner, DEMO, "/platform/attendance").status_code in (403, 404)


def test_menus_link_to_attendance_and_the_check_in_qr():
    app, _ = _seeded_app()
    owner = _client(app, DEMO, "owner@demospace.com", PERSONA_PASSWORD)
    html = _get(owner, DEMO, "/admin/").data
    assert b"/admin/attendance" in html and b"/checkin/pass" in html
    employee = _client(app, DEMO, "employee@acmeco.com", PERSONA_PASSWORD)
    html = _get(employee, DEMO, "/me/").data
    assert b"/checkin/pass" in html and b"/admin/attendance" not in html
    platform = _client(app, APEX, "admin@hub1z.com", OWNER_PASSWORD)
    assert b"/platform/attendance" in _get(platform, APEX, "/platform/").data
