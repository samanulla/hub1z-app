"""Credits core: 30-minute units, the pool, allocations, lots, the monthly cycle and booking."""
import os
from datetime import date, datetime, time, timedelta
from decimal import Decimal

os.environ.setdefault("FLASK_ENV", "testing")

import pytest

from app import create_app
from app.extensions import db
from app.models import (
    Company, CompanyStatus, ConferenceRoom, CreditAllocation, CreditBucket, CreditSettings, Floor,
    Location, Operator, OperatorStatus, RoomBooking, RoomCategory, SeatBand, User, UserRole,
)
from app.services import credit_service
from app.services.booking_service import BookingError, cancel_booking, create_room_booking
from app.services.credit_service import CreditError

HOST = "cr.hub1z.com"
PW = "CreditPass123!"


@pytest.fixture
def world():
    app = create_app({"SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:", "WTF_CSRF_ENABLED": False,
                      "MAIL_SUPPRESS_SEND": True, "STORAGE_BACKEND": "local",
                      "LOCAL_STORAGE_DIR": "./var/test-uploads", "RATELIMIT_ENABLED": False})
    with app.app_context():
        db.create_all()
        op = Operator(slug="cr", name="Credit Space", primary_domain=HOST, status=OperatorStatus.ACTIVE)
        db.session.add(op); db.session.flush()
        loc = Location(operator_id=op.id, name="HQ", code="HQ", address_line1="x", city="c", country="IN",
                       timezone="Asia/Kolkata", open_time=time(9, 0), close_time=time(18, 0))
        db.session.add(loc); db.session.flush()
        floor = Floor(operator_id=op.id, location_id=loc.id, level=1, name="G")
        db.session.add(floor); db.session.flush()
        credit_service.seed_default_categories(op.id)
        std = RoomCategory.query.filter_by(operator_id=op.id, name="Standard").one()
        exe = RoomCategory.query.filter_by(operator_id=op.id, name="Executive").one()
        room = ConferenceRoom(operator_id=op.id, location_id=loc.id, floor_id=floor.id, code="R1", name="Room",
                              capacity=6, category_id=std.id)
        boardroom = ConferenceRoom(operator_id=op.id, location_id=loc.id, floor_id=floor.id, code="R2",
                                   name="Boardroom", capacity=12, category_id=exe.id)
        acme = Company(operator_id=op.id, name="Acme", billing_email="a@acme.com", status=CompanyStatus.ACTIVE)
        db.session.add_all([room, boardroom, acme]); db.session.flush()
        users = []
        for email, role, company in (("owner@cr.com", UserRole.SUPER_ADMIN, None),
                                     ("e1@cr.com", UserRole.EMPLOYEE, acme), ("e2@cr.com", UserRole.EMPLOYEE, acme),
                                     ("solo@cr.com", UserRole.INDIVIDUAL, None)):
            u = User(operator_id=op.id, email=email, full_name=email.split("@")[0], role=role,
                     company_id=company.id if company else None, is_active=True)
            u.set_password(PW)
            users.append(u)
        db.session.add_all(users)
        db.session.commit()
        yield {"app": app, "op": op.id, "room": room.id, "boardroom": boardroom.id, "acme": acme.id,
               "e1": users[1].id, "e2": users[2].id, "solo": users[3].id}


def _start(days=2, hour=10, minute=0):
    return (datetime.utcnow() + timedelta(days=days)).replace(hour=hour, minute=minute, second=0, microsecond=0)


def _book(w, who, room, start, hours=1):
    return create_room_booking(user=db.session.get(User, w[who]), room=db.session.get(ConferenceRoom, w[room]),
                               start=start, end=start + timedelta(hours=hours))


def test_pool_is_capacity_times_share_minus_reserve(world):
    s = credit_service.pool_summary(world["op"])
    # 9:00-18:00 = 18 slots x 26 days: Standard 1 credit, Executive 2 credits.
    assert s["capacity"] == 18 * 26 * 1 + 18 * 26 * 2 == 1404
    assert s["pool"] == 702 and s["reserve"] == 140 and s["allocatable"] == 562


def test_new_allocation_is_prorated_and_changes_start_next_month(world):
    op, acme = world["op"], world["acme"]
    r = credit_service.allocate(op, company_id=acme, monthly=20, today=date(2026, 9, 16))
    db.session.commit()
    assert r["starts"] == "now"
    assert credit_service.balance(op, company_id=acme, now=datetime(2026, 9, 20))["complimentary"] == 10  # 15 of 30 days

    later = credit_service.allocate(op, company_id=acme, monthly=30, today=date(2026, 9, 17))
    db.session.commit()
    assert later["starts"] == "01 Oct 2026"
    assert CreditAllocation.query.one().monthly_credits == 20  # unchanged until the cycle

    result = credit_service.run_cycle(op, date(2026, 10, 1))
    assert result == {"expired": 1, "changed": 1, "granted": 1}
    assert credit_service.balance(op, company_id=acme, now=datetime(2026, 10, 2))["complimentary"] == 30
    assert credit_service.run_cycle(op, date(2026, 10, 1)) == {"expired": 0, "changed": 0, "granted": 0}  # idempotent


def test_last_day_joiner_is_not_topped_up_to_a_full_month_by_the_cycle(world):
    op, acme = world["op"], world["acme"]
    credit_service.allocate(op, company_id=acme, monthly=20, today=date(2026, 9, 30))  # 1 of 30 days -> 0 credits
    db.session.commit()
    assert credit_service.run_cycle(op, date(2026, 9, 30))["granted"] == 0
    assert credit_service.balance(op, company_id=acme, now=datetime(2026, 9, 30, 12))["total"] == 0
    assert credit_service.run_cycle(op, date(2026, 10, 1))["granted"] == 1  # a full month from October


def test_pool_limit_warns_or_blocks(world):
    op, acme = world["op"], world["acme"]
    r = credit_service.allocate(op, company_id=acme, monthly=600)
    assert "exceed" in r["warning"]
    CreditSettings.for_operator(op).pool_mode = "block"
    with pytest.raises(CreditError, match="left to allocate"):
        credit_service.allocate(op, user_id=world["solo"], monthly=100)


def test_seat_bands_cannot_overlap_and_suggest_credits(world):
    op = world["op"]
    db.session.add(SeatBand(operator_id=op, min_seats=1, max_seats=10, monthly_credits=20))
    db.session.commit()
    assert credit_service.band_overlaps(op, 8, 12)
    assert not credit_service.band_overlaps(op, 11, 25)
    assert credit_service.suggest_credits(op, 6) == 20 and credit_service.suggest_credits(op, 40) == 0


def test_credits_are_spent_bonus_then_complimentary_then_purchased(world):
    op, acme = world["op"], world["acme"]
    credit_service.allocate(op, company_id=acme, monthly=10, today=date(2026, 9, 1))
    credit_service.grant_bonus(op, company_id=acme, credits=3, today=date(2026, 9, 1))
    credit_service._grant(op, {"company_id": acme}, CreditBucket.PURCHASED, 5, None, "purchase")
    db.session.commit()
    now = datetime(2026, 9, 5)
    taken = credit_service.spend(op, company_id=acme, credits=15, now=now)
    assert [(lot.bucket.value, n) for lot, n in taken] == [("bonus", 3), ("complimentary", 10), ("purchased", 2)]
    assert credit_service.balance(op, company_id=acme, now=now)["total"] == 3
    with pytest.raises(CreditError):
        credit_service.spend(op, company_id=acme, credits=4, now=now)


def test_booking_uses_30_minute_credits_shared_by_the_company_and_refunds_on_cancel(world):
    op, acme = world["op"], world["acme"]
    credit_service._grant(op, {"company_id": acme}, CreditBucket.COMPLIMENTARY, 6, None, "monthly", "test")
    db.session.commit()
    start = _start()
    b1 = _book(world, "e1", "room", start, hours=1)          # Standard: 2 slots x 1 credit
    assert b1.credits_used == 2 and b1.total_amount == 0
    b2 = _book(world, "e2", "boardroom", start, hours=1)    # Executive: 2 slots x 2 credits
    assert b2.credits_used == 4
    assert credit_service.balance(op, company_id=acme)["total"] == 0  # both employees drew on one pool
    cancel_booking(b2, db.session.get(User, world["e2"]))
    assert credit_service.balance(op, company_id=acme)["total"] == 4  # back into the lot it came from


def test_shortfall_is_charged_in_cash_or_refused_when_pay_per_use_is_off(world):
    op, solo = world["op"], world["solo"]
    credit_service._grant(op, {"user_id": solo}, CreditBucket.COMPLIMENTARY, 1, None, "monthly", "test")
    db.session.commit()
    b = _book(world, "solo", "room", _start(), hours=1)      # needs 2 credits, has 1 -> half in cash
    assert b.credits_used == 1 and b.total_amount == Decimal("150.00")  # Standard is Rs 300 / hour
    CreditSettings.for_operator(op).pay_per_use_enabled = False
    db.session.commit()
    with pytest.raises(BookingError, match="Buy more credits"):
        _book(world, "solo", "room", _start(days=3), hours=1)


def test_room_bookings_must_be_in_30_minute_steps(world):
    with pytest.raises(BookingError, match="30-minute"):
        _book(world, "solo", "room", _start(minute=15), hours=1)
    with pytest.raises(BookingError, match="30-minute"):
        create_room_booking(user=db.session.get(User, world["solo"]), room=db.session.get(ConferenceRoom, world["room"]),
                            start=_start(), end=_start() + timedelta(minutes=45))


def test_operator_owner_can_use_the_credits_pages(world):
    app, op = world["app"], world["op"]
    c = app.test_client()
    c.post("/auth/login", data={"email": "owner@cr.com", "password": PW}, headers={"Host": HOST})
    for path in ("/admin/credits", "/admin/credits/settings", "/admin/credits/activity"):
        assert c.get(path, headers={"Host": HOST}).status_code == 200, path
    r = c.post("/admin/credits/allocate", data={"subject": f"c:{world['acme']}", "monthly_credits": 12},
               headers={"Host": HOST}, follow_redirects=True)
    assert b"Allocated 12 credits" in r.data and b"Kept for new signups" in r.data
    c.post("/admin/credits/bands/new", data={"min_seats": 1, "max_seats": 10, "monthly_credits": 20},
           headers={"Host": HOST})
    r = c.post("/admin/credits/bands/new", data={"min_seats": 5, "max_seats": 12, "monthly_credits": 30},
               headers={"Host": HOST}, follow_redirects=True)
    assert b"overlaps" in r.data
    with app.app_context():
        assert SeatBand.query.count() == 1


def test_employees_cannot_open_the_credits_pages(world):
    c = world["app"].test_client()
    c.post("/auth/login", data={"email": "e1@cr.com", "password": PW}, headers={"Host": HOST})
    assert c.get("/admin/credits", headers={"Host": HOST}).status_code == 403
