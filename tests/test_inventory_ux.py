"""Inventory usability: floor numbering, workspace types, active-only seat counts, seat delete, pricing hints."""
import os
from datetime import datetime, timedelta

os.environ.setdefault("FLASK_ENV", "testing")

from app.extensions import db
from app.models import (BookingStatus, Floor, Location, Operator, PlanType, Seat, SeatBooking, SeatType, User)
from app.services.formatting import floor_label, floor_level_label
from tests.test_release_upi_parcels_alerts import DEMO, _client, _get, _post, _seeded_app


def _demo(app):
    with app.app_context():
        operator = Operator.query.filter_by(primary_domain=DEMO).one()
        location = Location.query.execution_options(skip_operator_filter=True).filter_by(operator_id=operator.id).first()
        floor = Floor.query.execution_options(skip_operator_filter=True).filter_by(location_id=location.id).first()
        return operator.id, location.id, floor.id


def _add_seat(app, code, active=True):
    operator_id, location_id, floor_id = _demo(app)
    with app.app_context():
        seat = Seat(operator_id=operator_id, location_id=location_id, floor_id=floor_id, code=code,
                    seat_type=SeatType.HOT_DESK, is_active=active)
        db.session.add(seat)
        db.session.commit()
        return seat.id


def test_floor_numbers_read_ground_then_1_2_3():
    assert [floor_level_label(n) for n in (0, 1, 2, 3, -1)] == ["Ground", "1", "2", "3", "B1"]
    ground, first, other = (type("F", (), {"level": level, "name": name}) for level, name in
                            ((0, "Ground floor"), (1, "Cabin block"), (2, ""))
                            )
    assert floor_label(ground) == "Ground floor"        # no "Ground — Ground floor"
    assert floor_label(first) == "1 \u2014 Cabin block"
    assert floor_label(other) == "2"


def test_ground_floor_can_be_added_as_zero_and_shows_as_ground():
    app, _ = _seeded_app()
    _, location_id, _ = _demo(app)
    owner = _client(app, DEMO, "owner@demospace.com")
    page = _get(owner, DEMO, f"/admin/locations/{location_id}/floors/new").get_data(as_text=True)
    assert "0 is the Ground floor" in page
    response = _post(owner, DEMO, f"/admin/locations/{location_id}/floors/new", {"level": "0", "name": "Terrace lounge"})
    assert response.status_code == 302
    with app.app_context():
        assert Floor.query.execution_options(skip_operator_filter=True).filter_by(
            location_id=location_id, name="Terrace lounge").one().level == 0
    detail = _get(owner, DEMO, f"/admin/locations/{location_id}").get_data(as_text=True)
    assert "Ground \u2014 Terrace lounge" in detail and "L0" not in detail
    assert _post(owner, DEMO, f"/admin/locations/{location_id}/floors/new", {"level": "", "name": "x"}).status_code == 200


def test_plan_form_offers_executive_office_and_not_managed_office():
    app, _ = _seeded_app()
    owner = _client(app, DEMO, "owner@demospace.com")
    page = _get(owner, DEMO, "/admin/plans/new").get_data(as_text=True)
    assert 'value="executive_office"' in page and "Executive Office" in page
    assert 'value="private_office"' in page
    assert 'value="managed_office"' not in page
    assert PlanType.EXECUTIVE_OFFICE.value == "executive_office"


def test_seats_list_shows_active_seats_with_an_option_for_inactive_ones():
    app, _ = _seeded_app()
    _, location_id, _ = _demo(app)
    _add_seat(app, "ACT-1")
    _add_seat(app, "OFF-1", active=False)
    owner = _client(app, DEMO, "owner@demospace.com")
    default = _get(owner, DEMO, f"/admin/locations/{location_id}/seats").get_data(as_text=True)
    assert "ACT-1" in default and "OFF-1" not in default
    assert "Include inactive seats (1)" in default and "Inactive seats</h5>" not in default
    shown = _get(owner, DEMO, f"/admin/locations/{location_id}/seats?include_inactive=1").get_data(as_text=True)
    assert "Inactive seats</h5>" in shown and "OFF-1" in shown
    assert shown.index("ACT-1") < shown.index("Inactive seats</h5>") < shown.index("OFF-1")


def test_inactive_seats_are_not_counted_in_inventory():
    app, _ = _seeded_app()
    _, location_id, _ = _demo(app)
    with app.app_context():
        before = len(Location.query.execution_options(skip_operator_filter=True).get(location_id).active_seats)
    _add_seat(app, "ACT-2")
    _add_seat(app, "OFF-2", active=False)
    with app.app_context():
        location = Location.query.execution_options(skip_operator_filter=True).get(location_id)
        assert len(location.active_seats) == before + 1 and len(location.inactive_seats) >= 1
    owner = _client(app, DEMO, "owner@demospace.com")
    detail = _get(owner, DEMO, f"/admin/locations/{location_id}").get_data(as_text=True)
    assert f"Offices &amp; desks ({before + 1}, " in detail and "inactive" in detail
    listing = _get(owner, DEMO, "/admin/locations").get_data(as_text=True)
    assert f"{before + 1} <span" in listing or f"<td>{before + 1}" in listing


def test_a_seat_without_history_can_be_deleted():
    app, _ = _seeded_app()
    seat_id = _add_seat(app, "DEL-1", active=False)
    owner = _client(app, DEMO, "owner@demospace.com")
    assert _post(owner, DEMO, f"/admin/seats/{seat_id}/delete", {}).status_code == 302
    with app.app_context():
        assert db.session.get(Seat, seat_id) is None


def test_a_seat_with_bookings_is_not_deleted_and_the_message_suggests_inactive():
    app, _ = _seeded_app()
    operator_id, _, _ = _demo(app)
    seat_id = _add_seat(app, "KEEP-1")
    with app.app_context():
        user = User.query.execution_options(skip_operator_filter=True).filter_by(operator_id=operator_id).first()
        start = datetime.utcnow() + timedelta(days=1)
        db.session.add(SeatBooking(operator_id=operator_id, seat_id=seat_id, user_id=user.id, start_at=start,
                                   end_at=start + timedelta(hours=2), status=BookingStatus.CONFIRMED))
        db.session.commit()
    owner = _client(app, DEMO, "owner@demospace.com")
    response = _post(owner, DEMO, f"/admin/seats/{seat_id}/delete", {})
    assert response.status_code == 302 and f"/seats/{seat_id}/edit" in response.headers["Location"]
    page = _get(owner, DEMO, f"/admin/seats/{seat_id}/edit").get_data(as_text=True)
    assert "cannot be deleted" in page and "inactive" in page
    with app.app_context():
        assert db.session.get(Seat, seat_id) is not None


def test_company_admins_cannot_delete_seats():
    app, _ = _seeded_app()
    seat_id = _add_seat(app, "NOPE-1")
    company_admin = _client(app, DEMO, "admin@acmeco.com")
    assert _post(company_admin, DEMO, f"/admin/seats/{seat_id}/delete", {}).status_code in (302, 403)
    with app.app_context():
        assert db.session.get(Seat, seat_id) is not None


def test_rate_fields_point_to_where_prices_are_set():
    app, _ = _seeded_app()
    _, location_id, _ = _demo(app)
    owner = _client(app, DEMO, "owner@demospace.com")
    room_form = _get(owner, DEMO, f"/admin/locations/{location_id}/rooms/new").get_data(as_text=True)
    assert 'href="/admin/credits/settings"' in room_form and "Room categories" in room_form
    assert 'href="/admin/plans"' in room_form
    seat_form = _get(owner, DEMO, f"/admin/locations/{location_id}/seats/new").get_data(as_text=True)
    assert "walk-in rates" in seat_form and 'href="/admin/plans"' in seat_form
    assert "walk-in prices" in _get(owner, DEMO, "/admin/plans").get_data(as_text=True)


def _seat_form(floor_id, code, seat_type, capacity=""):
    return {"floor_id": floor_id, "code": code, "seat_type": seat_type, "capacity": capacity,
            "hourly_rate": "0", "daily_rate": "0", "monthly_rate": "0", "is_active": "y"}


def test_private_office_needs_a_capacity_but_a_desk_does_not():
    app, _ = _seeded_app()
    _, location_id, floor_id = _demo(app)
    owner = _client(app, DEMO, "owner@demospace.com")
    url = f"/admin/locations/{location_id}/seats/new"
    missing = _post(owner, DEMO, url, _seat_form(floor_id, "CAP-OFC", "private_office"))
    assert missing.status_code == 200 and "how many people this office seats" in missing.get_data(as_text=True)
    assert _post(owner, DEMO, url, _seat_form(floor_id, "CAP-OFC", "private_office", "4")).status_code == 302
    assert _post(owner, DEMO, url, _seat_form(floor_id, "CAP-DESK", "dedicated_desk")).status_code == 302
    with app.app_context():
        rows = {s.code: s.capacity for s in Seat.query.execution_options(skip_operator_filter=True)
                .filter(Seat.code.in_(["CAP-OFC", "CAP-DESK"]))}
    assert rows == {"CAP-OFC": 4, "CAP-DESK": 1}


def test_offices_and_desks_list_shows_free_or_held_and_filters_by_type():
    from datetime import date
    from app.models import AllocationStatus, Company, SeatAllocation
    app, _ = _seeded_app()
    operator_id, location_id, floor_id = _demo(app)
    with app.app_context():
        company = Company.query.execution_options(skip_operator_filter=True).filter_by(operator_id=operator_id).first()
        free = Seat(operator_id=operator_id, location_id=location_id, floor_id=floor_id, code="CABIN-A",
                    seat_type=SeatType.PRIVATE_OFFICE, capacity=4)
        held = Seat(operator_id=operator_id, location_id=location_id, floor_id=floor_id, code="CABIN-B",
                    seat_type=SeatType.PRIVATE_OFFICE, capacity=4)
        unset = Seat(operator_id=operator_id, location_id=location_id, floor_id=floor_id, code="CABIN-C",
                     seat_type=SeatType.PRIVATE_OFFICE)
        db.session.add_all([free, held, unset])
        db.session.flush()
        db.session.add(SeatAllocation(operator_id=operator_id, seat_id=held.id, company_id=company.id,
                                      status=AllocationStatus.ACTIVE, start_date=date.today()))
        db.session.commit()
        company_name = company.name
    owner = _client(app, DEMO, "owner@demospace.com")
    page = _get(owner, DEMO, f"/admin/locations/{location_id}/seats").get_data(as_text=True)
    row = lambda code: page[page.index(f"<strong>{code}</strong>"):].split("</tr>")[0]
    assert "Free" in row("CABIN-A") and "Held" in row("CABIN-B") and company_name in row("CABIN-B")
    assert "Capacity 1 is the unset default" in row("CABIN-C")
    assert "Offices &amp; desks at" in page and "create the subscription" in page
    offices = _get(owner, DEMO, f"/admin/locations/{location_id}/seats?type=private_office").get_data(as_text=True)
    assert "CABIN-A" in offices and "HD-" not in offices.split("<tbody>")[1]
    desks = _get(owner, DEMO, f"/admin/locations/{location_id}/seats?type=dedicated_desk").get_data(as_text=True)
    assert "CABIN-A" not in desks
    sidebar = _get(owner, DEMO, "/admin/locations").get_data(as_text=True)
    assert ">Inventory<" in sidebar and "Meeting rooms" in sidebar


def _held_office(app, code="HELD-1"):
    from datetime import date
    from app.models import AllocationStatus, Company, SeatAllocation
    operator_id, location_id, floor_id = _demo(app)
    with app.app_context():
        company = Company.query.execution_options(skip_operator_filter=True).filter_by(operator_id=operator_id).first()
        seat = Seat(operator_id=operator_id, location_id=location_id, floor_id=floor_id, code=code,
                    seat_type=SeatType.PRIVATE_OFFICE, capacity=4)
        db.session.add(seat)
        db.session.flush()
        db.session.add(SeatAllocation(operator_id=operator_id, seat_id=seat.id, company_id=company.id,
                                      status=AllocationStatus.ACTIVE, start_date=date.today()))
        db.session.commit()
        return seat.id, company.name


def test_held_office_keeps_type_capacity_and_status_but_other_details_can_change():
    app, _ = _seeded_app()
    _, _, floor_id = _demo(app)
    seat_id, company_name = _held_office(app)
    owner = _client(app, DEMO, "owner@demospace.com")
    page = _get(owner, DEMO, f"/admin/seats/{seat_id}/edit").get_data(as_text=True)
    assert f"Held by {company_name}" in page and "locked" in page
    assert "Cannot be deleted" in page and "Delete this office or desk" not in page
    # Tampered values are ignored: only the code, rates and notes are applied.
    data = _seat_form(floor_id, "HELD-1B", "dedicated_desk", "9")
    data.pop("is_active")
    data["monthly_rate"] = "1500"
    assert _post(owner, DEMO, f"/admin/seats/{seat_id}/edit", data).status_code == 302
    with app.app_context():
        seat = db.session.get(Seat, seat_id)
        assert (seat.code, seat.seat_type, seat.capacity, seat.is_active, int(seat.monthly_rate)) == \
            ("HELD-1B", SeatType.PRIVATE_OFFICE, 4, True, 1500)


def test_free_office_can_be_changed_and_deleted_and_held_one_has_no_trash_button():
    app, _ = _seeded_app()
    operator_id, location_id, floor_id = _demo(app)
    held_id, _ = _held_office(app, "HELD-2")
    free_id = _add_seat(app, "FREE-1")
    owner = _client(app, DEMO, "owner@demospace.com")
    page = _get(owner, DEMO, f"/admin/locations/{location_id}/seats").get_data(as_text=True)
    assert f'form="delete-seat-{free_id}"' in page and f'form="delete-seat-{held_id}"' not in page
    edit = _get(owner, DEMO, f"/admin/seats/{free_id}/edit").get_data(as_text=True)
    assert "Delete this office or desk" in edit and "locked" not in edit
    assert _post(owner, DEMO, f"/admin/seats/{free_id}/edit",
                 _seat_form(floor_id, "FREE-1", "dedicated_desk", "1")).status_code == 302
    with app.app_context():
        assert db.session.get(Seat, free_id).seat_type == SeatType.DEDICATED_DESK


def test_inventory_menu_has_no_calendar_book_or_repeated_tabs():
    app, _ = _seeded_app()
    owner = _client(app, DEMO, "owner@demospace.com")
    html = _get(owner, DEMO, "/admin/locations").get_data(as_text=True)
    sidebar = html.split('<aside class="h-side"', 1)[1].split("</aside>", 1)[0]
    assert ">Inventory<" in sidebar and ">Credits<" in sidebar and ">Calendar<" not in sidebar
    assert 'aria-label="Section navigation"' not in html


def test_credits_page_explains_the_room_calculation_in_plain_steps():
    app, _ = _seeded_app()
    owner = _client(app, DEMO, "owner@demospace.com")
    page = _get(owner, DEMO, "/admin/credits").get_data(as_text=True)
    for text in ("Your rooms offer", "You give away", "Still to give", "hours open a day",
                 "Credits/hour", "Give monthly credits", "Give a one-off bonus"):
        assert text in page, text
    assert "Band suggests" not in page and "Complimentary" not in page
    assert _get(owner, DEMO, "/admin/credits/settings").status_code == 200
