import os
os.environ.setdefault("FLASK_ENV", "testing")

from app.models import Floor, Location, Operator, Seat, SeatType, ConferenceRoom
from app.extensions import db
from tests.test_release_upi_parcels_alerts import DEMO, OTHER, _client, _get, _post, _seeded_app


def _location(app, host=DEMO):
    with app.app_context():
        operator = Operator.query.filter_by(primary_domain=host).one()
        location = Location.query.execution_options(skip_operator_filter=True).filter_by(operator_id=operator.id).first()
        floor = Floor.query.execution_options(skip_operator_filter=True).filter_by(location_id=location.id).first()
        return location.id, floor.id


def _batch(floor_id, **overrides):
    values = {"floor_id": str(floor_id), "seat_type": "dedicated_desk", "capacity": "1", "code_prefix": "D-",
              "start_number": "1", "count": "10", "number_digits": "2", "hourly_rate": "0",
              "daily_rate": "500", "monthly_rate": "10000", "is_active": "y", "notes": "Window row"}
    values.update(overrides)
    return values


def test_bulk_add_is_atomic_and_location_scoped():
    app, _ = _seeded_app()
    location_id, floor_id = _location(app)
    owner = _client(app, DEMO, "owner@demospace.com")
    path = f"/admin/locations/{location_id}/seats/bulk"
    assert _post(owner, DEMO, path, _batch(floor_id)).status_code == 302
    with app.app_context():
        seats = Seat.query.execution_options(skip_operator_filter=True).filter_by(location_id=location_id).filter(Seat.code.like("D-%")).order_by(Seat.code).all()
        assert len(seats) == 10 and seats[0].code == "D-01" and seats[-1].code == "D-10"
        assert all(seat.seat_type == SeatType.DEDICATED_DESK and seat.monthly_rate == 10000 for seat in seats)
    response = _post(owner, DEMO, path, _batch(floor_id, start_number="8"))
    assert response.status_code == 200 and b'No seats were added' in response.data
    with app.app_context():
        assert Seat.query.execution_options(skip_operator_filter=True).filter_by(location_id=location_id).filter(Seat.code.like("D-%")).count() == 10
    other_location, other_floor = _location(app, OTHER)
    assert _post(owner, DEMO, path, _batch(other_floor, code_prefix="BAD-")).status_code == 200
    assert _get(owner, DEMO, f"/admin/locations/{other_location}/seats/bulk").status_code == 404


def test_bulk_edit_changes_only_explicit_fields_and_rejects_foreign_seats():
    app, _ = _seeded_app()
    location_id, floor_id = _location(app)
    owner = _client(app, DEMO, "owner@demospace.com")
    assert _post(owner, DEMO, f"/admin/locations/{location_id}/seats/bulk", _batch(floor_id)).status_code == 302
    with app.app_context():
        seats = Seat.query.execution_options(skip_operator_filter=True).filter_by(location_id=location_id).filter(Seat.code.like("D-%")).order_by(Seat.code).all()
        chosen = [seat.id for seat in seats[:3]]
        untouched_id = seats[-1].id
        other_location, _ = _location(app, OTHER)
        other_seat_id = Seat.query.execution_options(skip_operator_filter=True).filter_by(location_id=other_location).first().id
    path = f"/admin/locations/{location_id}/seats/bulk-edit"
    assert _post(owner, DEMO, path, {"seat_ids": [str(value) for value in chosen], "apply_fields": ["monthly_rate"], "monthly_rate": "0", "floor_id": "0"}).status_code == 302
    with app.app_context():
        for seat_id in chosen:
            seat = db.session.get(Seat, seat_id)
            assert seat.monthly_rate == 0 and seat.daily_rate == 500 and seat.floor_id == floor_id and seat.notes == "Window row"
        assert db.session.get(Seat, untouched_id).monthly_rate == 10000
    response = _post(owner, DEMO, path, {"seat_ids": [str(chosen[0]), str(other_seat_id)], "apply_fields": ["monthly_rate"], "monthly_rate": "9000", "floor_id": "0"})
    assert response.status_code == 200
    with app.app_context():
        assert db.session.get(Seat, chosen[0]).monthly_rate == 0
    page = _get(owner, DEMO, f"/admin/locations/{location_id}/seats")
    assert b'aria-label="Inventory path"' in page.data
    assert f'/admin/locations/{location_id}/rooms'.encode() in page.data


def test_save_next_preserves_details_and_suggests_unused_seat_code():
    app, _ = _seeded_app()
    location_id, floor_id = _location(app)
    owner = _client(app, DEMO, "owner@demospace.com")
    data = {"floor_id": str(floor_id), "code": "ROW-01", "seat_type": "dedicated_desk", "capacity": "1",
            "hourly_rate": "100", "daily_rate": "500", "monthly_rate": "10000", "is_active": "y",
            "notes": "Window row", "carry_details": "y", "submit_action": "save_next"}
    path = f"/admin/locations/{location_id}/seats/new"
    response = _post(owner, DEMO, path, data)
    assert response.status_code == 302 and "previous=" in response.location
    page = _get(owner, DEMO, response.location)
    assert b'value="ROW-02"' in page.data and b'selected value="dedicated_desk"' in page.data
    assert b'Window row' in page.data and b'value="10000.00"' in page.data
    assert _post(owner, DEMO, path, data).status_code == 200
    data.update(code="ROW-02", carry_details="")
    response = _post(owner, DEMO, path, data)
    page = _get(owner, DEMO, response.location)
    assert b'value="ROW-03"' in page.data and b'Window row' not in page.data
    with app.app_context():
        assert Seat.query.execution_options(skip_operator_filter=True).filter_by(location_id=location_id, code="ROW-01").count() == 1


def test_rooms_offer_save_next_and_direct_seat_navigation():
    app, _ = _seeded_app()
    location_id, floor_id = _location(app)
    owner = _client(app, DEMO, "owner@demospace.com")
    response = _post(owner, DEMO, f"/admin/locations/{location_id}/rooms/new", {
        "floor_id": str(floor_id), "code": "MEET-01", "name": "First room", "capacity": "8",
        "hourly_rate": "1000", "category_id": "0", "is_active": "y", "carry_details": "y", "submit_action": "save_next"})
    assert response.status_code == 302
    page = _get(owner, DEMO, response.location)
    assert page.status_code == 200 and b'value="MEET-02"' in page.data and b'value="1000.00"' in page.data
    assert f'/admin/locations/{location_id}/seats'.encode() in page.data