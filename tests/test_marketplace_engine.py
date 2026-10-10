"""Marketplace booking engine: rules, capacity, holds, payment, cancellation and commission."""
import os
from datetime import datetime, timedelta
from decimal import Decimal

os.environ.setdefault("FLASK_ENV", "testing")

import pytest

from app import create_app
from app.extensions import db
from app.models import (
    CommissionLedgerEntry, ConferenceRoom, Floor, Location, MarketplaceBooking, MarketplaceCustomer,
    MarketplaceListing, Operator, OperatorMarketplaceTerms, RoomBlock, RoomBooking, User, UserRole,
)
from app.services import booking_service
from app.services import marketplace as mk
from app.services.marketplace import MarketplaceError

NOW = datetime(2026, 11, 1, 6, 0)       # a Sunday morning, UTC
SLOT = datetime(2026, 11, 3, 10, 0)     # Tuesday 15:30 IST


@pytest.fixture()
def world():
    app = create_app({"SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:", "WTF_CSRF_ENABLED": False,
                      "MAIL_SUPPRESS_SEND": True, "STORAGE_BACKEND": "local",
                      "LOCAL_STORAGE_DIR": "./var/test-uploads", "MARKETPLACE_ENABLED": True})
    with app.app_context():
        db.create_all()
        op = Operator(slug="mk", name="Mk Space")
        db.session.add(op)
        db.session.flush()
        loc = Location(operator_id=op.id, name="HQ", code="HQ", address_line1="1 Main Rd", city="Chennai",
                       state="TN", postal_code="600001", timezone="Asia/Kolkata")
        db.session.add(loc)
        db.session.flush()
        floor = Floor(operator_id=op.id, location_id=loc.id, name="1", level=1)
        db.session.add(floor)
        db.session.flush()
        room = ConferenceRoom(operator_id=op.id, location_id=loc.id, floor_id=floor.id, name="R1", code="R1",
                              capacity=8)
        member = User(operator_id=op.id, email="m@x.in", full_name="M", role=UserRole.INDIVIDUAL,
                      password_hash="x")
        terms = OperatorMarketplaceTerms(operator_id=op.id, enabled=True, kyc_approved=True,
                                         commission_pct=Decimal("10"),
                                         payment_methods=["manual_upi", "pay_at_venue"])
        cust = MarketplaceCustomer(email="c@x.in", full_name="Cust", phone="9")
        db.session.add_all([room, member, terms, cust])
        db.session.flush()
        w = type("W", (), {})()
        w.op, w.loc, w.room, w.member, w.cust = op, loc, room, member, cust
        w.room_listing = _listing(w, "room", room_id=room.id, price=500, approval_mode="instant")
        w.day_listing = _listing(w, "day_access", price=300, approval_mode="instant", daily_cap_units=2)
        db.session.commit()
        yield w
        db.session.remove()


def _listing(w, kind, **kw):
    listing = MarketplaceListing(operator_id=w.op.id, location_id=w.loc.id, resource_type=kind,
                                 title=f"{kind} listing", status="live", **kw)
    db.session.add(listing)
    db.session.flush()
    return listing


def _book(w, listing, start=SLOT, hours=2, key="k1", method="pay_at_venue", **kw):
    return mk.create_booking(listing=listing, customer=w.cust, start=start, end=start + timedelta(hours=hours),
                             idempotency_key=key, payment_method=method, now=NOW, **kw)


def test_instant_pay_at_venue_confirms_blocks_room_and_accrues_commission(world):
    b = _book(world, world.room_listing)
    assert b.status == "confirmed" and b.source == "hub1z_marketplace"
    assert b.subtotal == Decimal("1000.00") and b.gst_amount == Decimal("180.00") and b.total == Decimal("1180.00")
    assert booking_service.room_blocked(world.room.id, SLOT, SLOT + timedelta(hours=1))
    entry = CommissionLedgerEntry.query.one()
    assert entry.entry_type == "accrual" and entry.amount == Decimal("100.00")
    assert mk.access_revealed(b)


def test_member_booking_wins_and_marketplace_cannot_overlap_it(world):
    db.session.add(RoomBooking(operator_id=world.op.id, room_id=world.room.id, user_id=world.member.id,
                               start_at=SLOT, end_at=SLOT + timedelta(hours=1)))
    db.session.commit()
    with pytest.raises(MarketplaceError, match="no longer free"):
        _book(world, world.room_listing)


def test_confirmed_marketplace_slot_blocks_members(world):
    _book(world, world.room_listing)
    with pytest.raises(booking_service.BookingError):
        booking_service.create_room_booking(user=world.member, room=world.room, start=SLOT,
                                            end=SLOT + timedelta(hours=1))


def test_request_mode_does_not_block_until_approved_and_recheck_loses_to_member(world):
    world.room_listing.approval_mode = "request"
    db.session.commit()
    b = _book(world, world.room_listing)
    assert b.status == "requested" and not booking_service.room_blocked(world.room.id, SLOT, SLOT + timedelta(hours=1))
    db.session.add(RoomBooking(operator_id=world.op.id, room_id=world.room.id, user_id=world.member.id,
                               start_at=SLOT, end_at=SLOT + timedelta(hours=1)))
    db.session.commit()
    with pytest.raises(MarketplaceError, match="no longer free"):
        mk.approve(b, now=NOW)


def test_request_approval_pay_at_venue_confirms(world):
    world.room_listing.approval_mode = "request"
    db.session.commit()
    b = mk.approve(_book(world, world.room_listing), now=NOW)
    assert b.status == "confirmed"


def test_day_access_cap_is_enforced(world):
    _book(world, world.day_listing, key="a", units=2, hours=8)
    with pytest.raises(MarketplaceError, match="No more passes"):
        _book(world, world.day_listing, key="b", units=1, hours=8)


def test_daily_cap_counts_local_days_across_midnight(world):
    world.day_listing.daily_cap_units = 1
    db.session.commit()
    late = datetime(2026, 11, 3, 18, 0)           # 23:30 IST on the 3rd
    _book(world, world.day_listing, start=late, hours=0.25, key="a")
    _book(world, world.day_listing, start=late + timedelta(minutes=45), hours=0.25, key="b")   # 00:15 IST on the 4th
    with pytest.raises(MarketplaceError):
        _book(world, world.day_listing, start=late + timedelta(hours=1), hours=0.25, key="c")


def test_room_hours_cap_is_a_share_of_open_hours(world):
    world.room_listing.daily_cap_hours_pct = 50
    db.session.commit()
    day = datetime(2026, 11, 3, 3, 0)             # 08:30 IST
    _book(world, world.room_listing, start=day, hours=8, key="a")
    with pytest.raises(MarketplaceError, match="fully used"):
        _book(world, world.room_listing, start=day + timedelta(hours=8), hours=5, key="b")


def test_blackout_window_lead_time_and_length_rules(world):
    world.room_listing.blackout_dates = ["2026-11-03"]
    db.session.commit()
    with pytest.raises(MarketplaceError, match="not available"):
        _book(world, world.room_listing)
    world.room_listing.blackout_dates = []
    world.room_listing.availability_windows = [{"days": [0, 1, 2, 3, 4], "from": "09:00", "to": "18:00"}]
    db.session.commit()
    with pytest.raises(MarketplaceError, match="outside the available hours"):
        _book(world, world.room_listing, start=datetime(2026, 11, 3, 14, 0))      # 19:30 IST
    with pytest.raises(MarketplaceError, match="notice"):
        _book(world, world.room_listing, start=NOW + timedelta(hours=1))
    world.room_listing.max_length_hours = 2
    db.session.commit()
    with pytest.raises(MarketplaceError, match="longest booking"):
        _book(world, world.room_listing, hours=3)


def test_manual_payment_flow_and_address_gate(world):
    b = _book(world, world.room_listing, method="manual_upi")
    assert b.status == "held" and b.payment_status == "unpaid" and not mk.access_revealed(b)
    mk.submit_payment(b, "UTR123")
    assert b.payment_status == "pending_verification" and not mk.access_revealed(b)
    mk.confirm_payment(b, now=NOW)
    assert b.status == "confirmed" and b.payment_status == "paid" and mk.access_revealed(b)


def test_unpaid_hold_expires_and_frees_the_slot(world):
    b = _book(world, world.room_listing, method="manual_upi")
    assert booking_service.room_blocked(world.room.id, SLOT, SLOT + timedelta(hours=1))
    assert mk.release_expired(now=NOW + timedelta(hours=1)) == 1
    assert b.status == "expired" and RoomBlock.query.count() == 0


def test_late_cancellation_refunds_half_and_reverses_commission_in_proportion(world):
    b = _book(world, world.room_listing, method="manual_upi")
    mk.submit_payment(b, "UTR1")
    mk.confirm_payment(b, now=NOW)
    pct = mk.cancel(b, by_operator=False, now=SLOT - timedelta(hours=3))
    assert pct == 50 and b.status == "cancelled_customer" and b.payment_status == "part_refunded"
    total = sum(e.amount for e in CommissionLedgerEntry.query.all())
    assert total == Decimal("50.00") and RoomBlock.query.count() == 0


def test_early_and_operator_cancellations_refund_in_full(world):
    b = _book(world, world.room_listing)
    assert mk.cancel(b, by_operator=False, now=SLOT - timedelta(days=2)) == 100
    b2 = _book(world, world.room_listing, key="k2")
    assert mk.cancel(b2, by_operator=True, now=SLOT - timedelta(hours=1)) == 100
    assert sum(e.amount for e in CommissionLedgerEntry.query.all()) == Decimal("0.00")


def test_idempotent_retry_returns_same_booking_and_open_holds_are_capped(world):
    first = _book(world, world.room_listing, method="manual_upi", key="same")
    assert _book(world, world.room_listing, method="manual_upi", key="same").id == first.id
    for i in range(2):
        _book(world, world.room_listing, start=SLOT + timedelta(days=i + 1), method="manual_upi", key=f"n{i}")
    with pytest.raises(MarketplaceError, match="pending bookings"):
        _book(world, world.room_listing, start=SLOT + timedelta(days=9), method="manual_upi", key="over")


def test_pause_blocks_new_bookings_but_honours_existing(world):
    b = _book(world, world.room_listing)
    mk.set_listing_status(world.room_listing, "paused")
    with pytest.raises(MarketplaceError, match="not available"):
        _book(world, world.room_listing, start=SLOT + timedelta(days=1), key="x")
    assert b.status == "confirmed"


def test_unlisting_declines_undecided_requests(world):
    world.room_listing.approval_mode = "request"
    db.session.commit()
    b = _book(world, world.room_listing)
    mk.set_listing_status(world.room_listing, "unlisted")
    assert b.status == "declined"


def test_not_bookable_unless_operator_approved_and_enabled(world):
    OperatorMarketplaceTerms.query.one().kyc_approved = False
    db.session.commit()
    with pytest.raises(MarketplaceError, match="not available"):
        _book(world, world.room_listing)


def test_unaccepted_payment_method_rejected(world):
    with pytest.raises(MarketplaceError, match="payment option"):
        _book(world, world.room_listing, method="razorpay")
