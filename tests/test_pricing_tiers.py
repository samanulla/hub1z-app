"""Pricing tiers: Owner-only CRUD, and resource-cap enforcement on tenants."""
import os
os.environ.setdefault("FLASK_ENV", "testing")

from app import create_app
from app.extensions import db
from app.models import User, UserRole, Tenant, TenantStatus, PricingTier, Location, Floor


def _app():
    app = create_app({"SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
                      "WTF_CSRF_ENABLED": False,
                      "MAIL_SUPPRESS_SEND": True,
                      "STORAGE_BACKEND": "local",
                      "LOCAL_STORAGE_DIR": "./var/test-uploads"})
    with app.app_context():
        db.create_all()
    return app


def _seed_owner(app, email="platform@hub1z.com", password="OwnerPass123!"):
    with app.app_context():
        u = User(email=email, full_name="Owner", role=UserRole.PLATFORM_OWNER, is_active=True)
        u.set_password(password)
        db.session.add(u); db.session.commit()


def _login(client, email, password):
    return client.post("/auth/login", data={"email": email, "password": password})


def test_owner_can_create_and_edit_tier():
    app = _app()
    _seed_owner(app)
    c = app.test_client()
    _login(c, "platform@hub1z.com", "OwnerPass123!")

    r = c.post("/platform/tiers/new", data={
        "key": "starter", "name": "Starter", "monthly_price": "4999",
        "is_active": "y", "max_locations": "1", "max_seats": "30",
        "max_private_offices": "3", "max_rooms": "2",
    }, follow_redirects=False)
    assert r.status_code == 302
    with app.app_context():
        tier = PricingTier.query.filter_by(key="starter").first()
        assert tier is not None
        assert tier.max_seats == 30
        tid = tier.id

    r = c.post(f"/platform/tiers/{tid}/edit", data={
        "key": "renamed-should-be-ignored", "name": "Starter Plus", "monthly_price": "5999",
        "is_active": "y", "max_locations": "1", "max_seats": "40",
        "max_private_offices": "3", "max_rooms": "2",
    }, follow_redirects=False)
    assert r.status_code == 302
    with app.app_context():
        tier = db.session.get(PricingTier, tid)
        assert tier.name == "Starter Plus"
        assert tier.max_seats == 40
        assert tier.key == "starter"  # immutable once created


def test_manager_cannot_manage_tiers_even_with_billing_permission():
    app = _app()
    _seed_owner(app)
    with app.app_context():
        mgr = User(email="mgr@hub1z.com", full_name="Mgr", role=UserRole.PLATFORM_MANAGER, is_active=True)
        mgr.set_password("MgrPass123!")
        mgr.set_platform_permissions(["tenants", "billing", "reports"])
        db.session.add(mgr); db.session.commit()

    c = app.test_client()
    _login(c, "mgr@hub1z.com", "MgrPass123!")
    assert c.get("/platform/tiers").status_code == 403
    assert c.get("/platform/tiers/new").status_code == 403


def _seed_tenant_with_tier(app, max_seats=1, max_locations=1, max_rooms=1, max_private_offices=1):
    with app.app_context():
        t = Tenant(slug="smallco", name="Small Co", primary_domain="smallco.hub1z.com",
                   status=TenantStatus.ACTIVE, plan_tier="starter")
        db.session.add(t); db.session.flush()
        db.session.add(PricingTier(key="starter", name="Starter", monthly_price=4999, is_active=True,
                                   max_locations=max_locations, max_seats=max_seats,
                                   max_private_offices=max_private_offices, max_rooms=max_rooms))
        admin = User(tenant_id=t.id, email="admin@smallco.com", full_name="Admin",
                    role=UserRole.SUPER_ADMIN, is_active=True)
        admin.set_password("AdminPass123!")
        db.session.add(admin)
        loc = Location(tenant_id=t.id, name="HQ", code="HQ", address_line1="x",
                       city="c", country="IN", timezone="Asia/Kolkata")
        db.session.add(loc); db.session.flush()
        fl = Floor(location_id=loc.id, level=1, name="Ground")
        db.session.add(fl); db.session.commit()
        return loc.id, fl.id


def test_seat_creation_blocked_at_tier_cap():
    app = _app()
    loc_id, fl_id = _seed_tenant_with_tier(app, max_seats=1)
    c = app.test_client()
    _login(c, "admin@smallco.com", "AdminPass123!")

    seat_data = lambda code: {
        "floor_id": fl_id, "code": code, "seat_type": "hot_desk", "capacity": 1,
        "hourly_rate": 0, "daily_rate": 0, "monthly_rate": 0,
    }
    r1 = c.post(f"/admin/locations/{loc_id}/seats/new", data=seat_data("HD-01"), follow_redirects=True)
    assert b"Seat created" in r1.data

    r2 = c.post(f"/admin/locations/{loc_id}/seats/new", data=seat_data("HD-02"), follow_redirects=True)
    assert b"plan allows up to 1 seat" in r2.data
    with app.app_context():
        from app.models import Seat
        assert Seat.query.filter_by(code="HD-02").first() is None


def test_private_office_and_seat_limits_are_independent():
    app = _app()
    loc_id, fl_id = _seed_tenant_with_tier(app, max_seats=1, max_private_offices=1)
    c = app.test_client()
    _login(c, "admin@smallco.com", "AdminPass123!")

    def add(code, seat_type):
        return c.post(f"/admin/locations/{loc_id}/seats/new", data={
            "floor_id": fl_id, "code": code, "seat_type": seat_type, "capacity": 1,
            "hourly_rate": 0, "daily_rate": 0, "monthly_rate": 0,
        }, follow_redirects=True)

    assert b"Seat created" in add("HD-01", "hot_desk").data
    # Private office is a separate bucket, so this should still succeed even
    # though the desk bucket is already full.
    assert b"Seat created" in add("PO-01", "private_office").data
    # But a second private office should now be blocked.
    r = add("PO-02", "private_office")
    assert b"plan allows up to 1 private office" in r.data


def test_room_and_location_limits_enforced():
    app = _app()
    loc_id, fl_id = _seed_tenant_with_tier(app, max_rooms=0, max_locations=1)
    c = app.test_client()
    _login(c, "admin@smallco.com", "AdminPass123!")

    r = c.post(f"/admin/locations/{loc_id}/rooms/new", data={
        "floor_id": fl_id, "code": "R1", "name": "Room 1", "capacity": 4,
        "hourly_rate": 0, "credit_cost_per_hour": 1,
    }, follow_redirects=True)
    assert b"plan allows up to 0 room" in r.data

    r = c.post("/admin/locations/new", data={
        "name": "Branch", "code": "BR", "address_line1": "y",
        "city": "c2", "country": "IN", "timezone": "Asia/Kolkata",
    }, follow_redirects=True)
    assert b"plan allows up to 1 location" in r.data


def test_no_tier_configured_fails_open():
    """A tenant on a plan_tier string with no matching PricingTier row isn't blocked."""
    app = _app()
    with app.app_context():
        t = Tenant(slug="notier", name="No Tier Co", primary_domain="notier.hub1z.com",
                   status=TenantStatus.ACTIVE, plan_tier="nonexistent")
        db.session.add(t); db.session.flush()
        admin = User(tenant_id=t.id, email="admin@notier.com", full_name="Admin",
                    role=UserRole.SUPER_ADMIN, is_active=True)
        admin.set_password("AdminPass123!")
        db.session.add(admin)
        loc = Location(tenant_id=t.id, name="HQ", code="HQ", address_line1="x",
                       city="c", country="IN", timezone="Asia/Kolkata")
        db.session.add(loc); db.session.commit()
        loc_id = loc.id

    c = app.test_client()
    _login(c, "admin@notier.com", "AdminPass123!")
    r = c.post("/admin/locations/new", data={
        "name": "Branch", "code": "BR", "address_line1": "y",
        "city": "c2", "country": "IN", "timezone": "Asia/Kolkata",
    }, follow_redirects=True)
    assert b"Location created" in r.data
