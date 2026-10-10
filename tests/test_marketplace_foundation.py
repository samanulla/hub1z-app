"""Marketplace foundation: models, constraints, defaults and unbuilt entitlement keys."""
import os
from datetime import datetime, timedelta

os.environ.setdefault("FLASK_ENV", "testing")

import pytest
from sqlalchemy.exc import IntegrityError

from app import create_app
from app.extensions import db
from app.models import (
    CommissionLedgerEntry, ConferenceRoom, Floor, Location, MarketplaceBooking, MarketplaceCustomer,
    MarketplaceListing, Operator, RoomBooking, User, UserRole,
)
from app.services.catalog import BY_CODE, ENTITLEMENT_DEFINITIONS


@pytest.fixture()
def ctx():
    app = create_app({"SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:", "WTF_CSRF_ENABLED": False,
                      "MAIL_SUPPRESS_SEND": True, "STORAGE_BACKEND": "local",
                      "LOCAL_STORAGE_DIR": "./var/test-uploads"})
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()


def _setup():
    op = Operator(slug="mk", name="Mk Space")
    db.session.add(op)
    db.session.flush()
    loc = Location(operator_id=op.id, name="HQ", code="HQ", address_line1="1 Main Rd", city="Chennai",
                   state="TN", postal_code="600001")
    db.session.add(loc)
    db.session.flush()
    floor = Floor(operator_id=op.id, location_id=loc.id, name="1", level=1)
    db.session.add(floor)
    db.session.flush()
    room = ConferenceRoom(operator_id=op.id, location_id=loc.id, floor_id=floor.id, name="R1", code="R1")
    user = User(operator_id=op.id, email="m@x.in", full_name="M", role=UserRole.INDIVIDUAL,
                password_hash="x")
    db.session.add_all([room, user])
    db.session.flush()
    return op, loc, room, user


def _booking(op, listing, customer, **kw):
    start = datetime(2026, 11, 1, 10)
    return MarketplaceBooking(operator_id=op.id, listing_id=listing.id, customer_id=customer.id,
                              idempotency_key=kw.pop("key", "k1"), start_at=start,
                              end_at=start + timedelta(hours=1), customer_name="C",
                              customer_email="c@x.in", **kw)


def test_new_listing_is_private_draft_and_booking_defaults(ctx):
    op, loc, room, user = _setup()
    listing = MarketplaceListing(operator_id=op.id, location_id=loc.id, resource_type="room",
                                 room_id=room.id, title="Room")
    cust = MarketplaceCustomer(email="c@x.in", full_name="C")
    db.session.add_all([listing, cust])
    db.session.flush()
    booking = _booking(op, listing, cust)
    db.session.add(booking)
    rb = RoomBooking(operator_id=op.id, room_id=room.id, user_id=user.id,
                     start_at=booking.start_at, end_at=booking.end_at)
    db.session.add(rb)
    db.session.commit()
    assert listing.status == "draft"
    assert booking.source == "hub1z_marketplace" and booking.payment_status == "unpaid"
    assert booking.code and rb.booking_source == "operator_member"


def test_bad_source_and_duplicate_idempotency_rejected(ctx):
    op, loc, room, _ = _setup()
    listing = MarketplaceListing(operator_id=op.id, location_id=loc.id, resource_type="room",
                                 room_id=room.id, title="Room")
    cust = MarketplaceCustomer(email="c@x.in", full_name="C")
    db.session.add_all([listing, cust])
    db.session.flush()
    db.session.add(_booking(op, listing, cust, source="bogus"))
    with pytest.raises(IntegrityError):
        db.session.flush()
    db.session.rollback()


def test_duplicate_booking_key_for_same_customer_rejected(ctx):
    op, loc, room, _ = _setup()
    listing = MarketplaceListing(operator_id=op.id, location_id=loc.id, resource_type="room",
                                 room_id=room.id, title="Room")
    cust = MarketplaceCustomer(email="c@x.in", full_name="C")
    db.session.add_all([listing, cust])
    db.session.flush()
    db.session.add_all([_booking(op, listing, cust), _booking(op, listing, cust)])
    with pytest.raises(IntegrityError):
        db.session.flush()
    db.session.rollback()


def test_ledger_entry_type_checked(ctx):
    op, loc, room, _ = _setup()
    listing = MarketplaceListing(operator_id=op.id, location_id=loc.id, resource_type="room",
                                 room_id=room.id, title="Room")
    cust = MarketplaceCustomer(email="c@x.in", full_name="C")
    db.session.add_all([listing, cust])
    db.session.flush()
    booking = _booking(op, listing, cust)
    db.session.add(booking)
    db.session.flush()
    db.session.add(CommissionLedgerEntry(operator_id=op.id, booking_id=booking.id, entry_type="edit",
                                         gross_amount=100, commission_pct=10, amount=10))
    with pytest.raises(IntegrityError):
        db.session.flush()
    db.session.rollback()


def test_marketplace_entitlement_keys_registered_unbuilt():
    for key in ("marketplace_listing", "marketplace_featured"):
        assert BY_CODE[key].built is False
        assert BY_CODE[key].availability == "coming_soon"
        assert ENTITLEMENT_DEFINITIONS[key].built is False
