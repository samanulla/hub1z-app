"""Public marketplace host: discovery, guest sign-in, booking, ID check, isolation."""
import io
import os
import re
from datetime import date, timedelta

os.environ.setdefault("FLASK_ENV", "testing")

import pytest
from flask import g

from app.cli import PERSONA_PASSWORD
from app.extensions import db
from app.models import (
    ConferenceRoom, Floor, Location, MarketplaceBooking, MarketplaceCustomer, MarketplaceListing, Operator,
    OperatorMarketplaceTerms,
)
from app.services import marketplace as mk
from tests.test_role_paths import DEMO, OTHER, _login, _seeded_app

SPACES = "spaces.localhost"
SECRET_DOOR = "DOORCODE-9917"
PRIVATE_ADDRESS = "77 Hidden Street"


def _day(offset=3):
    d = date.today() + timedelta(days=offset)
    return d.isoformat()


def _make_listing(op, loc, room, **kw):
    row = MarketplaceListing(operator_id=op.id, location_id=loc.id, resource_type="room", room_id=room.id,
                             status="live", price=500, approval_mode="instant", daily_cap_hours_pct=100, **kw)
    db.session.add(row)
    db.session.flush()
    return row


def _approve(op, methods=("pay_at_venue", "manual_upi")):
    db.session.add(OperatorMarketplaceTerms(operator_id=op.id, enabled=True, kyc_approved=True,
                                            payment_methods=list(methods)))


def _world():
    app, _ = _seeded_app()
    app.config.update(MARKETPLACE_ENABLED=True, MARKETPLACE_SHOW_DEV_CODE=True, RATELIMIT_ENABLED=False)
    with app.app_context():
        ops = {}
        for key, host in (("demo", DEMO), ("other", OTHER)):
            op = Operator.query.execution_options(skip_operator_filter=True).filter_by(primary_domain=host).one()
            loc = Location.query.execution_options(skip_operator_filter=True).filter_by(operator_id=op.id).first()
            loc.address_line1 = PRIVATE_ADDRESS if key == "demo" else "1 Other Rd"
            loc.city = "Chennai" if key == "demo" else "Pune"
            floor = Floor(operator_id=op.id, location_id=loc.id, name="MK", level=7)
            db.session.add(floor)
            db.session.flush()
            room = ConferenceRoom(operator_id=op.id, location_id=loc.id, floor_id=floor.id, name=f"{key} room",
                                  code=f"MK{key[0].upper()}", capacity=8)
            db.session.add(room)
            db.session.flush()
            ops[key] = (op, loc, room)
        op, loc, room = ops["demo"]
        op.payment_upi_id = "demo@upi"
        _approve(op)
        live = _make_listing(op, loc, room, title="Demo Boardroom", access_instructions=SECRET_DOOR)
        needs_id = _make_listing(op, loc, room, title="Demo ID Room", access_instructions=SECRET_DOOR,
                                 guest_rules={"id_required": True})
        draft = _make_listing(op, loc, room, title="Demo Draft")
        draft.status = "draft"
        oop, oloc, oroom = ops["other"]
        unapproved = _make_listing(oop, oloc, oroom, title="Other Unapproved")
        db.session.commit()
        return app, {"live": live.id, "id": needs_id.id, "draft": draft.id, "unapproved": unapproved.id}


def _signin(client, email="guest@example.com", name="Gita Guest"):
    r = client.post("/marketplace/login", data={"email": email, "name": name}, headers={"Host": SPACES})
    assert r.status_code == 302, r.data[:300]
    page = client.get("/marketplace/verify", headers={"Host": SPACES}).data.decode()
    code = re.search(r"your code is (\d{6})", page).group(1)
    r = client.post("/marketplace/verify", data={"code": code}, headers={"Host": SPACES})
    assert r.status_code == 302
    return client


def _book(client, listing_id, method="pay_at_venue", date_offset=3, **extra):
    data = {"date": _day(date_offset), "start": "10:00", "hours": "2", "guests": "2", "payment_method": method,
            "agree": "1", "key": os.urandom(6).hex(), **extra}
    return client.post(f"/marketplace/l/{listing_id}/book", data=data, headers={"Host": SPACES})


def _code(response):
    return re.search(r"/marketplace/b/([A-Z0-9]+)", response.headers["Location"]).group(1)


def test_marketplace_only_exists_on_its_own_host_and_root_redirects():
    app, ids = _world()
    c = app.test_client()
    assert c.get("/marketplace/", headers={"Host": DEMO}).status_code == 404
    assert c.get("/marketplace/", headers={"Host": "localhost"}).status_code == 404
    assert c.get("/marketplace/", headers={"Host": SPACES}).status_code == 200
    r = c.get("/", headers={"Host": SPACES})
    assert r.status_code == 302 and "/marketplace" in r.headers["Location"]
    app.config["MARKETPLACE_ENABLED"] = False
    assert c.get("/marketplace/", headers={"Host": SPACES}).status_code == 404


def test_search_shows_only_live_approved_listings_and_never_private_details():
    app, ids = _world()
    c = app.test_client()
    page = c.get("/marketplace/", headers={"Host": SPACES}).data.decode()
    assert "Demo Boardroom" in page and "Demo ID Room" in page
    assert "Demo Draft" not in page and "Other Unapproved" not in page
    assert SECRET_DOOR not in page and PRIVATE_ADDRESS not in page and "demo@upi" not in page
    detail = c.get(f"/marketplace/l/{ids['live']}", headers={"Host": SPACES}).data.decode()
    assert SECRET_DOOR not in detail and PRIVATE_ADDRESS not in detail and "demo@upi" not in detail
    assert c.get(f"/marketplace/l/{ids['draft']}", headers={"Host": SPACES}).status_code == 404
    assert c.get(f"/marketplace/l/{ids['unapproved']}", headers={"Host": SPACES}).status_code == 404
    assert "Demo Boardroom" in c.get("/marketplace/?city=chennai", headers={"Host": SPACES}).data.decode()
    assert "Demo Boardroom" not in c.get("/marketplace/?city=Pune", headers={"Host": SPACES}).data.decode()


def test_tenant_tables_cannot_be_read_implicitly_on_the_marketplace_host():
    app, ids = _world()
    with app.test_request_context("/marketplace/", headers={"Host": SPACES}):
        app.preprocess_request()
        assert g.marketplace_host is True
        with pytest.raises(RuntimeError, match="must be explicit"):
            MarketplaceListing.query.all()
        assert MarketplaceListing.query.execution_options(marketplace_read=True).count() >= 3


def test_booking_needs_sign_in_and_a_wrong_code_is_refused():
    app, ids = _world()
    c = app.test_client()
    r = _book(c, ids["live"])
    assert r.status_code == 302 and "/marketplace/login" in r.headers["Location"]
    c.post("/marketplace/login", data={"email": "g@example.com", "name": "G"}, headers={"Host": SPACES})
    r = c.post("/marketplace/verify", data={"code": "000000"}, headers={"Host": SPACES})
    assert r.status_code == 200 and b"isn" in r.data
    assert c.get("/marketplace/bookings", headers={"Host": SPACES}).status_code == 302


def test_pay_at_venue_booking_confirms_and_reveals_address_only_when_allowed():
    app, ids = _world()
    c = _signin(app.test_client())
    r = _book(c, ids["live"])
    assert r.status_code == 302
    code = _code(r)
    page = c.get(f"/marketplace/b/{code}", headers={"Host": SPACES}).data.decode()
    assert "Confirmed" in page and SECRET_DOOR in page and PRIVATE_ADDRESS in page
    mine = c.get("/marketplace/bookings", headers={"Host": SPACES}).data.decode()
    assert "Demo Boardroom" in mine


def test_manual_upi_booking_holds_until_the_operator_confirms_payment():
    app, ids = _world()
    c = _signin(app.test_client())
    code = _code(_book(c, ids["live"], method="manual_upi"))
    page = c.get(f"/marketplace/b/{code}", headers={"Host": SPACES}).data.decode()
    assert "Payment due" in page and "demo@upi" in page and SECRET_DOOR not in page
    assert c.get(f"/marketplace/b/{code}/upi.png", headers={"Host": SPACES}).mimetype == "image/png"
    c.post(f"/marketplace/b/{code}/pay", data={"reference": "UTR555"}, headers={"Host": SPACES})
    assert "Payment being checked" in c.get(f"/marketplace/b/{code}", headers={"Host": SPACES}).data.decode()
    with app.app_context():
        booking = MarketplaceBooking.query.execution_options(skip_operator_filter=True).filter_by(code=code).one()
        mk.confirm_payment(booking)
    page = c.get(f"/marketplace/b/{code}", headers={"Host": SPACES}).data.decode()
    assert SECRET_DOOR in page and PRIVATE_ADDRESS in page


def test_existing_member_is_sent_to_their_member_portal():
    app, ids = _world()
    c = _signin(app.test_client(), email="individual@demospace.com", name="Member Person")
    r = _book(c, ids["live"])
    assert r.status_code == 302 and f"/marketplace/l/{ids['live']}" in r.headers["Location"]
    page = c.get(r.headers["Location"], headers={"Host": SPACES}).data.decode()
    assert "member portal" in page
    with app.app_context():
        assert MarketplaceBooking.query.execution_options(skip_operator_filter=True).count() == 0


def test_a_guest_cannot_open_or_change_someone_elses_booking():
    app, ids = _world()
    a = _signin(app.test_client(), email="a@example.com", name="A")
    code = _code(_book(a, ids["live"]))
    b = _signin(app.test_client(), email="b@example.com", name="B")
    assert b.get(f"/marketplace/b/{code}", headers={"Host": SPACES}).status_code == 404
    assert b.post(f"/marketplace/b/{code}/cancel", headers={"Host": SPACES}).status_code == 404
    assert a.get(f"/marketplace/b/{code}", headers={"Host": SPACES}).status_code == 200


def test_guest_session_is_not_an_operator_login():
    app, ids = _world()
    c = _signin(app.test_client())
    r = c.get("/admin/marketplace", headers={"Host": DEMO})
    assert r.status_code in (302, 401, 403) and "/auth/login" in r.headers.get("Location", "/auth/login")


def test_id_must_be_uploaded_and_approved_before_access_is_shown_then_can_be_rejected_at_the_door():
    app, ids = _world()
    c = _signin(app.test_client())
    code = _code(_book(c, ids["id"]))
    page = c.get(f"/marketplace/b/{code}", headers={"Host": SPACES}).data.decode()
    assert "Photo ID" in page and SECRET_DOOR not in page
    bad = c.post(f"/marketplace/b/{code}/id", data={"id_file": (io.BytesIO(b"x"), "id.exe")},
                 headers={"Host": SPACES}, content_type="multipart/form-data")
    assert bad.status_code == 302
    c.post(f"/marketplace/b/{code}/id", data={"id_file": (io.BytesIO(b"\x89PNG data"), "id.png")},
           headers={"Host": SPACES}, content_type="multipart/form-data")
    with app.app_context():
        row = MarketplaceBooking.query.execution_options(skip_operator_filter=True).filter_by(code=code).one()
        assert row.id_status == "pending_review" and row.id_document_key
        bid = row.id

    owner = app.test_client()
    assert _login(owner, DEMO, "owner@demospace.com", PERSONA_PASSWORD).status_code == 302
    h = {"Host": DEMO}
    assert owner.get(f"/admin/marketplace/bookings/{bid}/id-document", headers=h).status_code == 200
    other = app.test_client()
    assert _login(other, OTHER, "owner@otherspace.com", PERSONA_PASSWORD).status_code == 302
    assert other.get(f"/admin/marketplace/bookings/{bid}/id-document", headers={"Host": OTHER}).status_code == 404

    owner.post(f"/admin/marketplace/bookings/{bid}/reject_id", data={"reason": "Blurry"}, headers=h)
    page = c.get(f"/marketplace/b/{code}", headers={"Host": SPACES}).data.decode()
    assert "Blurry" in page and SECRET_DOOR not in page
    c.post(f"/marketplace/b/{code}/id", data={"id_file": (io.BytesIO(b"\x89PNG again"), "id2.png")},
           headers={"Host": SPACES}, content_type="multipart/form-data")
    owner.post(f"/admin/marketplace/bookings/{bid}/approve_id", headers=h)
    page = c.get(f"/marketplace/b/{code}", headers={"Host": SPACES}).data.decode()
    assert SECRET_DOOR in page

    owner.post(f"/admin/marketplace/bookings/{bid}/reject_id_venue", data={"reason": "Name does not match", "refund": "0"},
               headers=h)
    with app.app_context():
        row = db.session.get(MarketplaceBooking, bid)
        assert row.status == "cancelled_operator" and row.id_status == "rejected" and row.id_document_key is None
    assert SECRET_DOOR not in c.get(f"/marketplace/b/{code}", headers={"Host": SPACES}).data.decode()


def test_guest_can_cancel_and_sees_the_refund():
    app, ids = _world()
    c = _signin(app.test_client())
    code = _code(_book(c, ids["live"]))
    r = c.post(f"/marketplace/b/{code}/cancel", headers={"Host": SPACES}, follow_redirects=True)
    assert b"Refund: 100%" in r.data
