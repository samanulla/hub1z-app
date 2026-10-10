"""Operator marketplace controls: opt-in, listing form, publish gate, pause/unlist and isolation."""
import os

os.environ.setdefault("FLASK_ENV", "testing")

from app.cli import PERSONA_PASSWORD, marketplace_approve_cmd
from app.extensions import db
from app.models import (
    ConferenceRoom, Floor, Location, MarketplaceBooking, MarketplaceCustomer, MarketplaceListing, Operator,
    OperatorMarketplaceTerms,
)
from tests.test_role_paths import DEMO, OTHER, _login, _seeded_app


def _client(app, host, email="owner@demospace.com"):
    c = app.test_client()
    assert _login(c, host, email, PERSONA_PASSWORD).status_code == 302
    return c


def _app(enabled=True):
    app, _ = _seeded_app()
    app.config["MARKETPLACE_ENABLED"] = enabled
    return app


def _room_id(app, host=DEMO):
    with app.app_context():
        op = Operator.query.execution_options(skip_operator_filter=True).filter_by(primary_domain=host).one()
        loc = (Location.query.execution_options(skip_operator_filter=True).filter_by(operator_id=op.id).first())
        floor = Floor(operator_id=op.id, location_id=loc.id, name="MK", level=9)
        db.session.add(floor)
        db.session.flush()
        room = ConferenceRoom(operator_id=op.id, location_id=loc.id, floor_id=floor.id, name="Mkt Room",
                              code="MKR", capacity=6)
        db.session.add(room)
        db.session.commit()
        return room.id


ROOM_FORM = {"resource_type": "room", "title": "Boardroom", "approval_mode": "instant", "price": "500",
             "gst_rate_pct": "18", "daily_cap_hours_pct": "50", "days": ["0", "1", "2", "3", "4"],
             "window_from": "09:00", "window_to": "18:00", "min_lead_hours": "2", "max_length_hours": "4",
             "cancellation_preset": "flexible", "blackout_dates": "2026-12-25\n2026-12-26", "room_id": "0",
             "location_id": "0"}


def _listing(app, title="Boardroom"):
    with app.app_context():
        return MarketplaceListing.query.execution_options(skip_operator_filter=True).filter_by(title=title).one().id


def test_marketplace_is_hidden_when_switched_off_and_from_non_managers():
    app = _app(enabled=False)
    demo = _client(app, DEMO)
    assert demo.get("/admin/marketplace", headers={"Host": DEMO}).status_code == 404
    app.config["MARKETPLACE_ENABLED"] = True
    assert demo.get("/admin/marketplace", headers={"Host": DEMO}).status_code == 200


def test_new_listing_is_a_private_draft_and_publishing_needs_optin_and_approval():
    app = _app()
    room_id = _room_id(app)
    demo = _client(app, DEMO)
    h = {"Host": DEMO}
    r = demo.post("/admin/marketplace/listings/new", data={**ROOM_FORM, "room_id": str(room_id)}, headers=h)
    assert r.status_code == 302
    lid = _listing(app)
    with app.app_context():
        listing = db.session.get(MarketplaceListing, lid)
        assert listing.status == "draft" and listing.daily_cap_hours_pct == 50
        assert listing.blackout_dates == ["2026-12-25", "2026-12-26"]
        assert listing.availability_windows == [{"days": [0, 1, 2, 3, 4], "from": "09:00", "to": "18:00"}]
    demo.post(f"/admin/marketplace/listings/{lid}/status", data={"status": "live"}, headers=h)
    with app.app_context():
        assert db.session.get(MarketplaceListing, lid).status == "draft"           # not opted in

    demo.post("/admin/marketplace/settings", data={"enabled": "1", "payment_methods": ["pay_at_venue"],
                                                   "compensation": "0"}, headers=h)
    demo.post(f"/admin/marketplace/listings/{lid}/status", data={"status": "live"}, headers=h)
    with app.app_context():
        assert db.session.get(MarketplaceListing, lid).status == "draft"           # Hub1z hasn't approved

    with app.app_context():
        op = Operator.query.execution_options(skip_operator_filter=True).filter_by(primary_domain=DEMO).one()
        OperatorMarketplaceTerms.query.execution_options(skip_operator_filter=True).filter_by(
            operator_id=op.id).one().kyc_approved = True
        db.session.commit()
    demo.post(f"/admin/marketplace/listings/{lid}/status", data={"status": "live"}, headers=h)
    demo.post(f"/admin/marketplace/listings/{lid}/status", data={"status": "paused"}, headers=h)
    with app.app_context():
        assert db.session.get(MarketplaceListing, lid).status == "paused"


def test_listing_form_requires_the_caps_that_protect_members():
    app = _app()
    demo = _client(app, DEMO)
    room_id = _room_id(app)
    bad = {**ROOM_FORM, "room_id": str(room_id), "daily_cap_hours_pct": ""}
    page = demo.post("/admin/marketplace/listings/new", data=bad, headers={"Host": DEMO})
    assert page.status_code == 200 and b"share of the room" in page.data
    day = {**ROOM_FORM, "resource_type": "day_access", "location_id": "1", "daily_cap_hours_pct": ""}
    assert b"passes you will share" in demo.post("/admin/marketplace/listings/new", data=day,
                                                 headers={"Host": DEMO}).data


def test_other_operators_cannot_touch_a_listing_or_booking():
    app = _app()
    room_id = _room_id(app)
    demo = _client(app, DEMO)
    demo.post("/admin/marketplace/listings/new", data={**ROOM_FORM, "room_id": str(room_id)}, headers={"Host": DEMO})
    lid = _listing(app)
    with app.app_context():
        listing = db.session.get(MarketplaceListing, lid)
        cust = MarketplaceCustomer(email="g@x.in", full_name="Guest")
        db.session.add(cust)
        db.session.flush()
        from datetime import datetime, timedelta
        booking = MarketplaceBooking(operator_id=listing.operator_id, listing_id=listing.id, customer_id=cust.id,
                                     idempotency_key="k", start_at=datetime(2030, 1, 1, 10),
                                     end_at=datetime(2030, 1, 1, 11), customer_name="Guest ZZGUEST",
                                     customer_email="g@x.in")
        db.session.add(booking)
        db.session.commit()
        bid = booking.id
    other = _client(app, OTHER, "owner@otherspace.com")
    h = {"Host": OTHER}
    assert other.get(f"/admin/marketplace/listings/{lid}/edit", headers=h).status_code == 404
    assert other.post(f"/admin/marketplace/listings/{lid}/status", data={"status": "live"}, headers=h).status_code == 404
    assert other.post(f"/admin/marketplace/bookings/{bid}/approve", headers=h).status_code == 404
    page = other.get("/admin/marketplace", headers=h)
    assert page.status_code == 200 and b"Boardroom" not in page.data
    assert b"ZZGUEST" not in other.get("/admin/marketplace/bookings?status=all", headers=h).data
    demo_page = demo.get("/admin/marketplace/bookings?status=all", headers={"Host": DEMO})
    assert b"ZZGUEST" in demo_page.data


def test_cli_approves_and_revokes():
    app = _app()
    with app.app_context():
        slug = Operator.query.execution_options(skip_operator_filter=True).filter_by(primary_domain=DEMO).one().slug
    runner = app.test_cli_runner()
    out = runner.invoke(marketplace_approve_cmd, [slug, "--commission", "9"])
    assert out.exit_code == 0 and "approved at 9%" in out.output
    with app.app_context():
        terms = OperatorMarketplaceTerms.query.execution_options(skip_operator_filter=True).one()
        assert terms.kyc_approved and str(terms.commission_pct) == "9.00"
    assert runner.invoke(marketplace_approve_cmd, [slug, "--revoke"]).exit_code == 0


def test_marketplace_pages_render_for_a_listing():
    app = _app()
    room_id = _room_id(app)
    demo = _client(app, DEMO)
    h = {"Host": DEMO}
    assert demo.get("/admin/marketplace/listings/new", headers=h).status_code == 200
    demo.post("/admin/marketplace/listings/new", data={**ROOM_FORM, "room_id": str(room_id)}, headers=h)
    lid = _listing(app)
    edit = demo.get(f"/admin/marketplace/listings/{lid}/edit", headers=h)
    assert edit.status_code == 200 and b"Boardroom" in edit.data and b"2026-12-25" in edit.data
    index = demo.get("/admin/marketplace", headers=h)
    assert index.status_code == 200 and b"Boardroom" in index.data and b"Awaiting Hub1z approval" in index.data
    assert demo.get("/admin/marketplace/bookings", headers=h).status_code == 200
    posted = demo.post(f"/admin/marketplace/listings/{lid}/edit", data={**ROOM_FORM, "price": "650"}, headers=h)
    assert posted.status_code == 302
    with app.app_context():
        assert str(db.session.get(MarketplaceListing, lid).price) == "650.00"
