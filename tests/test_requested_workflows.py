"""Regression coverage for recurring jobs, invoice snapshots, and tenant scope."""
import os
from datetime import date, datetime, timedelta, time
from decimal import Decimal

os.environ.setdefault("FLASK_ENV", "testing")

import pytest

from app import create_app
from app.extensions import db
from app.models import (
    Tenant, TenantStatus, User, UserRole, Location, Floor, ConferenceRoom,
    RecurringRoomBooking, RecurrencePattern, RoomBooking,
    PricingPlan, PlanType, BillingCycle, Subscription, SubscriptionStatus,
)


@pytest.fixture
def app():
    app = create_app({
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "WTF_CSRF_ENABLED": False,
        "STORAGE_BACKEND": "local",
        "LOCAL_STORAGE_DIR": "./var/test-uploads",
        "RATELIMIT_ENABLED": False,
    })
    with app.app_context():
        db.create_all()
        yield app


def _workspace():
    tenant = Tenant(slug="acme", name="Acme Workspace", status=TenantStatus.ACTIVE,
                    currency_code="INR", default_tax_rate=Decimal("18.00"))
    user = User(tenant=tenant, email="member@acme.example", full_name="Member",
                role=UserRole.INDIVIDUAL, is_active=True)
    user.set_password("password")
    location = Location(name="Main Office", code="MAIN",
                        address_line1="1 Main Street", city="Bengaluru",
                        state="KA", country="IN", postal_code="560001",
                        timezone="UTC")
    db.session.add_all([tenant, user])
    db.session.flush()
    location.tenant_id = tenant.id
    db.session.add(location)
    db.session.flush()
    tenant.primary_location_id = location.id
    floor = Floor(tenant_id=tenant.id, location_id=location.id, level=1, name="Ground")
    db.session.add(floor)
    db.session.flush()
    room = ConferenceRoom(tenant_id=tenant.id, location_id=location.id,
                          floor_id=floor.id, code="R1", name="Room 1", capacity=4,
                          hourly_rate=Decimal("100"))
    db.session.add(room)
    db.session.commit()
    return tenant, user, room


def test_recurring_materialization_is_idempotent(app):
    with app.app_context():
        tenant, user, room = _workspace()
        tomorrow = date.today() + timedelta(days=1)
        series = RecurringRoomBooking(
            tenant_id=tenant.id, room_id=room.id, user_id=user.id,
            pattern=RecurrencePattern.DAILY, start_time=time(9), end_time=time(10),
            start_date=tomorrow, end_date=tomorrow, is_active=True,
        )
        db.session.add(series)
        db.session.commit()

        from app.services.booking_service import materialize_recurring_room_bookings
        as_of = datetime.combine(date.today(), time(8))
        assert materialize_recurring_room_bookings(as_of=as_of) == 1
        assert materialize_recurring_room_bookings(as_of=as_of) == 0
        instance = RoomBooking.query.filter_by(recurring_booking_id=series.id).one()
        assert instance.tenant_id == tenant.id


def test_generated_invoice_snapshots_primary_location(app):
    with app.app_context():
        tenant, user, _ = _workspace()
        plan = PricingPlan(tenant_id=tenant.id, name="Monthly", plan_type=PlanType.HOT_DESK,
                           billing_cycle=BillingCycle.MONTHLY, base_price=Decimal("1000"))
        db.session.add(plan)
        db.session.flush()
        sub = Subscription(tenant_id=tenant.id, plan_id=plan.id, user_id=user.id,
                           unit_price=Decimal("1000"), start_date=date.today(),
                           status=SubscriptionStatus.ACTIVE)
        db.session.add(sub)
        db.session.commit()

        from app.services.billing_service import generate_invoice_for_subscription
        invoice = generate_invoice_for_subscription(sub, date.today(), date.today())
        assert invoice.currency == "INR"
        assert invoice.billing_name is None
        assert invoice.billing_address == "1 Main Street"
        assert invoice.billing_city == "Bengaluru"
        assert invoice.subscription_id == sub.id


def test_booking_rejects_cross_tenant_resource(app):
    with app.app_context():
        _, user, room = _workspace()
        other = Tenant(slug="other", name="Other Workspace", status=TenantStatus.ACTIVE)
        other_user = User(tenant=other, email="other@example.com", full_name="Other",
                          role=UserRole.INDIVIDUAL, is_active=True)
        other_user.set_password("password")
        db.session.add_all([other, other_user])
        db.session.commit()

        from app.services.booking_service import BookingError, create_room_booking
        start = datetime.utcnow() + timedelta(days=1)
        with pytest.raises(BookingError, match="does not belong"):
            create_room_booking(user=other_user, room=room,
                                start=start, end=start + timedelta(hours=1))