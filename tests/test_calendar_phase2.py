"""Phase 2: shared calendar privacy, operator blocks, company rules, check-in and no-shows."""
import re
from datetime import datetime, timedelta

import pytest

from app.extensions import db
from app.models import (
    BookingStatus, CompanyCreditPolicy, ConferenceRoom, CreditBucket, CreditLedger, Floor, LedgerType, Location,
    RoomBlock, RoomBooking, User, UserRole,
)
from app.services import credit_service
from app.services.booking_service import (
    BookingError, can_check_in, check_in, check_room_conflict, create_room_booking, release_no_shows,
)
from tests.test_credits_core import HOST, PW, _book, _start, world  # noqa: F401 - world is a fixture


def _fund(w, credits=20):
    credit_service._grant(w["op"], {"company_id": w["acme"]}, CreditBucket.COMPLIMENTARY, credits, None, "monthly", "t")
    db.session.commit()


class _As:
    """A signed-in browser. Each request gets its own app context: the fixture keeps one open, and
    Flask-Login would otherwise reuse the first user it cached on ``g`` for every later request."""

    def __init__(self, app, email):
        self.app, self.client = app, app.test_client()
        self.post("/auth/login", data={"email": email, "password": PW})

    def get(self, url, **kw):
        with self.app.app_context():
            return self.client.get(url, headers={"Host": HOST}, **kw)

    def post(self, url, **kw):
        with self.app.app_context():
            return self.client.post(url, headers={"Host": HOST}, **kw)


def _login(w, email):
    return _As(w["app"], email)


def _loc_id():
    return Location.query.filter_by(code="HQ").one().id


def _local(dt):
    """The location's wall clock (IST) as the calendar forms send it."""
    return (dt + timedelta(hours=5, minutes=30)).strftime("%Y-%m-%dT%H:%M")


def test_other_people_see_only_booked_but_the_company_and_operator_see_details(world):
    _fund(world)
    start = _start(days=3)
    create_room_booking(user=db.session.get(User, world["e1"]), room=db.session.get(ConferenceRoom, world["room"]),
                        start=start, end=start + timedelta(hours=1), title="Secret pitch")
    url = f"/book/locations/{_loc_id()}/calendar?date={start.date().isoformat()}"
    seen = {who: _login(world, email).get(url).data
            for who, email in (("colleague", "e2@cr.com"), ("operator", "owner@cr.com"), ("outsider", "solo@cr.com"))}
    assert b"Secret pitch" in seen["colleague"] and b"Secret pitch" in seen["operator"]
    assert b"Secret pitch" not in seen["outsider"] and b'class="lbl">Booked<' in seen["outsider"]


def test_operator_blocks_take_a_room_out_of_use_without_credits(world):
    start = _start(days=3)
    db.session.add(RoomBlock(operator_id=world["op"], room_id=world["room"], start_at=start,
                             end_at=start + timedelta(hours=1), reason="Painting"))
    db.session.commit()
    with pytest.raises(BookingError, match="not available"):
        _book(world, "solo", "room", start, hours=1)
    _book(world, "solo", "room", start + timedelta(hours=1), hours=1)  # right after the block is fine


def test_only_the_operator_can_block_and_never_over_existing_bookings(world):
    _fund(world)
    start = _start(days=3)
    _book(world, "e1", "room", start, hours=1)
    url = f"/book/locations/{_loc_id()}/calendar/block"
    over = {"room_id": world["room"], "start": _local(start), "end": _local(start + timedelta(hours=1))}
    assert _login(world, "e1@cr.com").post(url, data=over).status_code == 403
    owner = _login(world, "owner@cr.com")
    assert b"already has bookings" in owner.post(url, data=over, follow_redirects=True).data
    assert RoomBlock.query.count() == 0
    free = {"room_id": world["room"], "start": _local(start + timedelta(hours=2)),
            "end": _local(start + timedelta(hours=3)), "reason": "Deep clean"}
    assert b"is blocked for that time" in owner.post(url, data=free, follow_redirects=True).data
    assert RoomBlock.query.count() == 1


def test_company_admin_decides_who_books_and_how_much(world):
    _fund(world)
    e1, acme = db.session.get(User, world["e1"]), world["acme"]
    policy = CompanyCreditPolicy.for_company(world["op"], acme)
    policy.booking_mode = "admin_only"
    boss = User(operator_id=world["op"], email="boss@cr.com", full_name="Boss", role=UserRole.COMPANY_ADMIN,
                company_id=acme, is_active=True)
    boss.set_password(PW)
    db.session.add(boss); db.session.commit()
    with pytest.raises(BookingError, match="not turned on"):
        _book(world, "e1", "room", _start(days=3))
    create_room_booking(user=boss, room=db.session.get(ConferenceRoom, world["room"]), start=_start(days=3),
                        end=_start(days=3) + timedelta(hours=1))  # admins are never held to the rule

    policy.booking_mode = "selected"
    db.session.commit()
    with pytest.raises(BookingError, match="not turned on"):
        _book(world, "e1", "room", _start(days=4))
    e1.credit_booking_allowed = True
    policy.per_employee_monthly_cap = 2
    db.session.commit()
    _book(world, "e1", "room", _start(days=4), hours=1)            # 2 credits: at the cap
    with pytest.raises(BookingError, match="allows 2 credits"):
        _book(world, "e1", "room", _start(days=5), hours=1)


def test_check_in_window_and_permissions(world):
    _fund(world)
    now = datetime.utcnow()
    b = _book(world, "e1", "room", _start(days=3), hours=1)
    b.start_at, b.end_at = now + timedelta(minutes=60), now + timedelta(minutes=120)
    db.session.commit()
    with pytest.raises(BookingError, match="opens 15 minutes"):
        check_in(b, now)
    b.start_at, b.end_at = now + timedelta(minutes=10), now + timedelta(minutes=70)
    db.session.commit()
    assert can_check_in(b, db.session.get(User, world["e1"]), now)
    assert not can_check_in(b, db.session.get(User, world["solo"]), now)
    url = f"/book/bookings/room/{b.id}/check-in"
    assert _login(world, "solo@cr.com").post(url).status_code == 403
    assert _login(world, "e1@cr.com").post(url).status_code == 302
    db.session.expire_all()
    assert db.session.get(RoomBooking, b.id).status == BookingStatus.CHECKED_IN


def test_no_shows_free_the_room_but_keep_the_credits_spent(world):
    _fund(world)
    op, acme = world["op"], world["acme"]
    b = _book(world, "e1", "room", _start(days=3), hours=1)
    now = datetime.utcnow()
    b.start_at, b.end_at = now - timedelta(minutes=30), now + timedelta(minutes=30)
    done = _book(world, "e2", "boardroom", _start(days=4), hours=1)
    done.start_at, done.end_at, done.status = now - timedelta(hours=2), now - timedelta(hours=1), BookingStatus.CHECKED_IN
    db.session.commit()
    spent = credit_service.balance(op, company_id=acme)["total"]
    assert release_no_shows(now) == {"released": 1, "completed": 1}
    assert db.session.get(RoomBooking, b.id).status == BookingStatus.NO_SHOW
    assert db.session.get(RoomBooking, done.id).status == BookingStatus.COMPLETED
    assert not check_room_conflict(b.room_id, b.start_at, b.end_at)          # the slot is open again
    assert credit_service.balance(op, company_id=acme)["total"] == spent      # nothing came back
    assert CreditLedger.query.filter_by(entry_type=LedgerType.FORFEIT, room_booking_id=b.id).count() == 1
    assert release_no_shows(now) == {"released": 0, "completed": 0}          # safe to re-run


def test_calendar_grid_quote_and_views(world):
    _fund(world)
    day = datetime.utcnow() + timedelta(days=3)
    c = _login(world, "e1@cr.com")
    page = c.get(f"/book/locations/{_loc_id()}/calendar?date={day.date().isoformat()}").data.decode()
    assert page.count('data-col="0"') == 18 and page.count('data-col="1"') == 18   # 9:00-18:00 in 30-minute rows
    m = re.search(r'class="slot available" data-col="\d+"\s+data-room="(\d+)" data-start="([^"]+)" data-end="([^"]+)"', page)
    room_id, s, e = m.groups()
    q = c.get(f"/book/rooms/{room_id}/quote?start={s}&end={e}").get_json()
    assert q["ok"] and q["credits_needed"] >= 1 and q["breakdown"][0][0] == "complimentary" and float(q["cash"]) == 0
    db.session.add(RoomBlock(operator_id=world["op"], room_id=int(room_id), start_at=day - timedelta(days=1),
                             end_at=day + timedelta(days=2), reason="x"))
    db.session.commit()
    assert "not available" in c.get(f"/book/rooms/{room_id}/quote?start={s}&end={e}").get_json()["message"]
    week = c.get(f"/book/locations/{_loc_id()}/calendar?view=week&room={room_id}&date={day.date().isoformat()}")
    assert week.status_code == 200 and week.data.count(b"<th>") >= 8


def test_cross_location_rooms_appear_on_every_calendar(world):
    op = world["op"]
    annex = Location(operator_id=op, name="Annex", code="AX", address_line1="x", city="c", country="IN",
                     timezone="Asia/Kolkata", is_247=True)
    db.session.add(annex); db.session.flush()
    floor = Floor(operator_id=op, location_id=annex.id, level=1, name="G")
    db.session.add(floor); db.session.flush()
    db.session.add(ConferenceRoom(operator_id=op, location_id=annex.id, floor_id=floor.id, code="AR", name="Annex Room",
                                  capacity=4, cross_location_bookable=True))
    db.session.commit()
    assert b"Annex Room" in _login(world, "e1@cr.com").get(f"/book/locations/{_loc_id()}/calendar").data


def test_company_admin_credits_page_saves_rules(world):
    _fund(world)
    acme = world["acme"]
    boss = User(operator_id=world["op"], email="boss@cr.com", full_name="Boss", role=UserRole.COMPANY_ADMIN,
                company_id=acme, is_active=True)
    boss.set_password(PW)
    db.session.add(boss); db.session.commit()
    c = _login(world, "boss@cr.com")
    assert c.get("/company/credits").status_code == 200
    r = c.post("/company/credits", data={"booking_mode": "selected", "per_employee_monthly_cap": "8",
                                         "allowed": [world["e1"]]}, follow_redirects=True)
    assert b"Credit rules saved" in r.data
    db.session.expire_all()
    policy = CompanyCreditPolicy.query.filter_by(company_id=acme).one()
    assert (policy.booking_mode, policy.per_employee_monthly_cap) == ("selected", 8)
    assert db.session.get(User, world["e1"]).credit_booking_allowed
    assert not db.session.get(User, world["e2"]).credit_booking_allowed
