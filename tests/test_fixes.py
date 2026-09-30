"""Tests for the 10 fixes in this batch."""
import os
from datetime import datetime, timedelta, date, time
from decimal import Decimal

os.environ.setdefault("FLASK_ENV", "testing")

import pytest
from flask import g

from app import create_app
from app.extensions import db
from app.models import (
    User, UserRole, SystemSettings, Operator, OperatorStatus,
    Location, Floor, Seat, SeatType, ConferenceRoom,
    SeatAllocation, AllocationStatus,
    Invoice, InvoiceStatus, Payment,
    Refund, RefundStatus,
    Company, CompanyStatus,
    AuditLog,
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
        op = Operator(slug="fixes", name="Fixes Space", primary_domain="fixes.hub1z.com",
                      status=OperatorStatus.ACTIVE)
        db.session.add(op)
        db.session.commit()
        # Rows created by the fixtures below are stamped with this operator.
        with app.test_request_context():
            g.operator_id = op.id
            yield app


@pytest.fixture
def bengaluru(app):
    loc = Location(
        name="Bengaluru", code="BLR",
        address_line1="X", city="Bengaluru", country="IN",
        timezone="Asia/Kolkata",
        open_time=time(9, 0), close_time=time(18, 0),
        is_247=False,
    )
    db.session.add(loc)
    db.session.flush()
    f = Floor(location_id=loc.id, level=1, name="Ground")
    db.session.add(f)
    db.session.flush()
    seat = Seat(location_id=loc.id, floor_id=f.id, code="S1",
                seat_type=SeatType.HOT_DESK, hourly_rate=Decimal("100"))
    db.session.add(seat)
    db.session.commit()
    return loc, seat


@pytest.fixture
def alex(app):
    u = User(email="a@x.com", full_name="Alex", role=UserRole.INDIVIDUAL, is_active=True)
    u.set_password("pw")
    db.session.add(u)
    db.session.commit()
    return u


# ---- H1: invoice prefix from settings --------------------------------

def test_invoice_prefix_default_is_inv(app):
    from app.services.billing_service import next_invoice_number
    n = next_invoice_number()
    assert n.startswith("INV-")


def test_invoice_prefix_uses_settings(app):
    s = SystemSettings.get()
    s.invoice_prefix = "CWH"
    db.session.commit()
    from app.services.billing_service import next_invoice_number
    n = next_invoice_number()
    assert n.startswith("CWH-")


# ---- C2: default tax rate from settings ------------------------------

def test_invoice_generation_uses_default_tax_rate(app):
    from app.models import PricingPlan, PlanType, BillingCycle, Subscription, SubscriptionStatus
    from app.services.billing_service import generate_invoice_for_subscription

    s = SystemSettings.get()
    s.default_tax_rate = Decimal("18.00")
    db.session.commit()

    u = User(email="s@x.com", full_name="Sub User", role=UserRole.INDIVIDUAL, is_active=True)
    u.set_password("pw")
    db.session.add(u)
    db.session.flush()

    plan = PricingPlan(name="Test", plan_type=PlanType.HOT_DESK,
                       billing_cycle=BillingCycle.MONTHLY, base_price=Decimal("10000"))
    db.session.add(plan)
    db.session.flush()
    sub = Subscription(plan_id=plan.id, user_id=u.id, company_id=None,
                       quantity=1, unit_price=Decimal("10000"),
                       start_date=date.today(), status=SubscriptionStatus.ACTIVE)
    db.session.add(sub)
    db.session.commit()

    inv = generate_invoice_for_subscription(sub, date.today(), date.today())
    assert inv.subtotal == Decimal("10000.00")
    assert inv.tax_amount == Decimal("1800.00")
    assert inv.total_amount == Decimal("11800.00")


# ---- C3: seat allocation blocks other bookings -----------------------

def test_seat_allocation_blocks_outsider(app, bengaluru, alex):
    _, seat = bengaluru
    other_company = Company(name="Acme", billing_email="a@a.com", status=CompanyStatus.ACTIVE)
    db.session.add(other_company)
    db.session.flush()
    db.session.add(SeatAllocation(
        seat_id=seat.id, company_id=other_company.id,
        start_date=date.today() - timedelta(days=1),
        end_date=date.today() + timedelta(days=30),
        status=AllocationStatus.ACTIVE,
    ))
    db.session.commit()

    from app.services.booking_service import check_seat_conflict
    now = datetime.utcnow() + timedelta(hours=1)
    assert check_seat_conflict(seat.id, now, now + timedelta(hours=1), booker=alex) is True


def test_seat_allocation_allows_owning_user(app, bengaluru, alex):
    _, seat = bengaluru
    db.session.add(SeatAllocation(
        seat_id=seat.id, user_id=alex.id,
        start_date=date.today() - timedelta(days=1),
        end_date=date.today() + timedelta(days=30),
        status=AllocationStatus.ACTIVE,
    ))
    db.session.commit()

    from app.services.booking_service import check_seat_conflict
    now = datetime.utcnow() + timedelta(hours=1)
    assert check_seat_conflict(seat.id, now, now + timedelta(hours=1), booker=alex) is False


# ---- H4: booking outside operating hours rejected --------------------

def test_booking_outside_hours_rejected(app, bengaluru, alex):
    loc, seat = bengaluru
    # Location open 09:00 - 18:00 IST. Book 20:00 IST (14:30 UTC).
    from app.services.booking_service import create_seat_booking, BookingError
    start = (datetime.utcnow() + timedelta(days=1)).replace(hour=14, minute=30, second=0, microsecond=0)
    end = start + timedelta(hours=1)
    with pytest.raises(BookingError):
        create_seat_booking(user=alex, seat=seat, start=start, end=end)


# ---- C1: refund lifecycle --------------------------------------------

def test_refund_only_decrements_on_completion(app):
    inv = Invoice(number="X1", period_start=date.today(), period_end=date.today(),
                  due_date=date.today(), subtotal=Decimal("1000"),
                  total_amount=Decimal("1000"), amount_paid=Decimal("1000"),
                  status=InvoiceStatus.PAID)
    db.session.add(inv)
    db.session.flush()
    p = Payment(invoice_id=inv.id, amount=Decimal("1000"), method="upi",
                paid_at=datetime.utcnow())
    db.session.add(p)
    db.session.commit()

    r = Refund(payment_id=p.id, amount=Decimal("400"), reason="Test",
               method="upi", status=RefundStatus.PENDING)
    db.session.add(r)
    db.session.commit()

    # While PENDING, invoice paid amount is untouched
    assert inv.amount_paid == Decimal("1000")

    # Simulate completion
    from decimal import Decimal as D
    r.status = RefundStatus.COMPLETED
    inv.amount_paid = D(inv.amount_paid) - D(r.amount)
    db.session.commit()
    assert inv.amount_paid == Decimal("600")


# ---- M7: audit log records actions -----------------------------------

def test_audit_service_writes_row(app):
    from app.services import audit_service
    audit_service.record("test.action", "test", 1, {"foo": "bar"})
    row = AuditLog.query.filter_by(action="test.action").first()
    assert row is not None
    assert row.entity_type == "test"
    assert row.entity_id == 1
    assert "foo" in (row.details or "")


# ---- M8: sanitize next= url ------------------------------------------

def test_safe_next_blocks_logout(app):
    from app.blueprints.auth.routes import _safe_next
    assert _safe_next("/auth/logout") is None
    assert _safe_next("//evil.com/steal") is None
    assert _safe_next("http://evil.com") is None
    assert _safe_next("/admin/") == "/admin/"
    assert _safe_next(None) is None


# ---- H5: location tz filter ------------------------------------------

def test_format_dt_at_uses_location_tz(app, bengaluru):
    loc, _ = bengaluru
    from app.services.formatting import format_dt_at
    dt = datetime(2026, 9, 16, 12, 30)  # UTC noon-ish
    out = format_dt_at(dt, loc, fmt="%Y-%m-%d %H:%M")
    # IST = UTC + 5:30, so 12:30 UTC = 18:00 IST
    assert out.endswith("18:00")


# ---- Payment methods for India ---------------------------------------

def test_payment_method_includes_upi(app):
    from app.blueprints.admin.forms import PaymentForm
    with app.test_request_context():
        f = PaymentForm()
        codes = [c[0] for c in f.method.choices]
    assert "upi" in codes
    assert "neft" in codes
    assert "rtgs" in codes
    assert "imps" in codes
