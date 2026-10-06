"""Hub1 SaaS tiers: catalog configuration and location-only enforcement."""
import os
os.environ.setdefault("FLASK_ENV", "testing")

import re
from decimal import Decimal

from app import create_app
from app.extensions import db
from app.models import (
    User, UserRole, Operator, OperatorStatus, PricingTier, TierStatus, PlatformModule, Location, Floor,
)


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
    with app.app_context():
        module = PlatformModule(code="payroll", name="Payroll", kind="feature", monthly_price=0, is_active=True)
        db.session.add(module)
        db.session.commit()
        module_id = module.id
    c = app.test_client()
    _login(c, "platform@hub1z.com", "OwnerPass123!")

    r = c.post("/platform/tiers/new", data={
        "name": "Starter", "monthly_price": "4999", "status": "active",
        "max_locations": "1", "included_active_contracted_seats": "50", "additional_seat_rate": "50",
        "additional_location_rate": "1000", "annual_discount": "10", "max_staff_users": "3",
        "max_open_leads": "100", "storage_mb": "500", "is_public": "y",
        "seat_overage_policy": "allow_and_charge", "location_overage_policy": "require_plan_upgrade",
        "effective_from": "2026-01-01", "feature_ids": [module_id],
        "seat_usage_method": "maximum_during_billing_period",
    }, follow_redirects=False)
    assert r.status_code == 302
    with app.app_context():
        tier = PricingTier.query.filter_by(key="starter_v1").first()
        assert tier is not None
        assert tier.included_active_contracted_seats == 50
        assert tier.max_staff_users == 3 and tier.max_open_leads == 100 and tier.storage_mb == 500
        assert tier.is_public and tier.status == TierStatus.ACTIVE
        assert [m.code for m in tier.module_catalog] == ["payroll"]
        assert tier.annual_price == Decimal("53989.20")  # 12 months less 10%
        tid = tier.id

    html = c.get(f"/platform/tiers/{tid}/edit").data.decode()
    for field_name, expected in (("status", "active"), ("seat_overage_policy", "allow_and_charge"),
                                 ("location_overage_policy", "require_plan_upgrade"),
                                 ("seat_usage_method", "maximum_during_billing_period")):
        options = re.search(rf'<select[^>]*id="{field_name}"[^>]*>(.*?)</select>', html, re.S).group(1)
        assert re.search(rf'<option(?=[^>]*value="{expected}")(?=[^>]*selected)[^>]*>', options)

    r = c.post(f"/platform/tiers/{tid}/edit", data={
        "name": "Starter Plus", "monthly_price": "5999", "status": "active",
        "max_locations": "1", "included_active_contracted_seats": "60", "additional_seat_rate": "50",
        "additional_location_rate": "1000", "annual_discount": "10",
        "max_staff_users": "", "max_open_leads": "", "storage_mb": "",
        "seat_overage_policy": "allow_and_charge", "location_overage_policy": "require_plan_upgrade",
        "effective_from": "2026-01-01",
        "seat_usage_method": "maximum_during_billing_period",
    }, follow_redirects=False)
    assert r.status_code == 302
    with app.app_context():
        tier = db.session.get(PricingTier, tid)
        assert tier.name == "Starter Plus"
        assert tier.included_active_contracted_seats == 60
        assert tier.key == "starter_v1"  # generated, immutable
        assert tier.module_catalog == []  # unticked features are removed
        assert tier.max_staff_users is None  # blank means unlimited


def test_contact_sales_tier_needs_no_price_to_activate():
    app = _app()
    _seed_owner(app)
    c = app.test_client()
    _login(c, "platform@hub1z.com", "OwnerPass123!")
    r = c.post("/platform/tiers/new", data={
        "name": "Enterprise", "status": "active", "contact_sales": "y", "all_features": "y",
        "max_locations": "2", "max_staff_users": "5", "storage_mb": "500",
        "seat_overage_policy": "require_plan_upgrade", "location_overage_policy": "require_plan_upgrade",
        "seat_usage_method": "maximum_during_billing_period",
    }, follow_redirects=False)
    assert r.status_code == 302
    with app.app_context():
        tier = PricingTier.query.filter_by(key="enterprise_v1").one()
        assert tier.max_locations is None and tier.max_staff_users is None and tier.storage_mb is None
        tier_id = tier.id
    html = c.get(f"/platform/tiers/{tier_id}/edit").data.decode()
    assert "Included in every plan" in html and "Bookings" in html
    assert re.search(r'<div[^>]*id="feature-choices"[^>]*hidden', html)
    assert 'id="all-feature-note"' in html and 'name="all_features"' in html
    # A normal tier still needs its price and limits before it can go live.
    r = c.post("/platform/tiers/new", data={
        "name": "Growth", "status": "active",
        "seat_overage_policy": "require_plan_upgrade", "location_overage_policy": "require_plan_upgrade",
        "seat_usage_method": "maximum_during_billing_period",
    })
    assert r.status_code == 200 and b"Monthly price is required" in r.data
    with app.app_context():
        assert PricingTier.query.filter_by(key="enterprise_v1").one().contact_sales is True
        assert PricingTier.query.filter_by(key="growth_v1").first() is None


def test_manager_cannot_manage_tiers_without_the_pricing_permission():
    app = _app()
    _seed_owner(app)
    with app.app_context():
        mgr = User(email="mgr@hub1z.com", full_name="Mgr", role=UserRole.PLATFORM_MANAGER, is_active=True)
        mgr.set_password("MgrPass123!")
        mgr.set_platform_permissions(["operators", "billing", "reports"])
        db.session.add(mgr); db.session.commit()

    c = app.test_client()
    _login(c, "mgr@hub1z.com", "MgrPass123!")
    for path in ("/platform/tiers", "/platform/tiers/new", "/platform/catalog", "/platform/payment-details",
                 "/platform/documents"):
        assert c.get(path).status_code == 403, path


def test_owner_can_grant_a_manager_pricing_and_payment_setup():
    app = _app()
    _seed_owner(app)
    with app.app_context():
        mgr = User(email="mgr@hub1z.com", full_name="Mgr", role=UserRole.PLATFORM_MANAGER, is_active=True)
        mgr.set_password("MgrPass123!")
        mgr.set_platform_permissions(["pricing", "payment_setup"])
        db.session.add(mgr); db.session.commit()

    c = app.test_client()
    _login(c, "mgr@hub1z.com", "MgrPass123!")
    assert c.get("/platform/tiers").status_code == 200
    assert c.get("/platform/catalog").status_code == 200
    assert c.get("/platform/payment-details").status_code == 200
    # Granting one permission never opens the others, or the owner-only team page.
    assert c.get("/platform/finance").status_code == 403
    assert c.get("/platform/team").status_code == 403


def test_catalog_items_that_are_not_built_cannot_be_made_available():
    app = _app()
    _seed_owner(app)
    c = app.test_client()
    _login(c, "platform@hub1z.com", "OwnerPass123!")
    assert c.get("/platform/catalog").status_code == 200  # first visit seeds the catalog
    with app.app_context():
        modules = {m.code: m.id for m in PlatformModule.query.all()}
        assert PlatformModule.query.filter_by(kind="feature").count() == 10
        assert PlatformModule.query.filter_by(code="api_webhooks").one().availability == "coming_soon"

    base = {"name": "API & Webhooks", "monthly_price": "0", "is_active": "y", "sort_order": "10"}
    r = c.post(f"/platform/catalog/{modules['api_webhooks']}/edit", data={**base, "availability": "available"})
    assert r.status_code == 200 and b"isn&#39;t built yet" in r.data
    r = c.post(f"/platform/catalog/{modules['extra_storage']}/edit", data={
        **base, "name": "Extra Storage", "availability": "available", "monthly_price": "299",
        "unit_label": "per 5 GB"})
    assert r.status_code == 302
    with app.app_context():
        assert PlatformModule.query.filter_by(code="api_webhooks").one().availability == "coming_soon"
        assert PlatformModule.query.filter_by(code="extra_storage").one().monthly_price == Decimal("299")


def test_new_manager_form_leaves_sensitive_permissions_off():
    app = _app()
    _seed_owner(app)
    c = app.test_client()
    _login(c, "platform@hub1z.com", "OwnerPass123!")
    page = c.get("/platform/team/new").data.decode()

    def tag(key):
        return re.search(rf'<input[^>]*name="perm_{key}"[^>]*>', page).group(0)

    for key in ("pricing", "payment_setup", "operator_suspension", "documents"):
        assert "checked" not in tag(key), key
    assert "checked" in tag("reports")


def _seed_operator_with_tier(app, max_locations=1):
    with app.app_context():
        t = Operator(slug="smallco", name="Small Co", primary_domain="smallco.hub1z.com",
                   status=OperatorStatus.ACTIVE, plan_tier="starter")
        db.session.add(t); db.session.flush()
        db.session.add(PricingTier(key="starter", name="Starter", monthly_price=4999, is_active=True,
                                   max_locations=max_locations))
        admin = User(operator_id=t.id, email="admin@smallco.com", full_name="Admin",
                    role=UserRole.SUPER_ADMIN, is_active=True)
        admin.set_password("AdminPass123!")
        db.session.add(admin)
        loc = Location(operator_id=t.id, name="HQ", code="HQ", address_line1="x",
                       city="c", country="IN", timezone="Asia/Kolkata")
        db.session.add(loc); db.session.flush()
        fl = Floor(operator_id=t.id, location_id=loc.id, level=1, name="Ground")
        db.session.add(fl); db.session.commit()
        return loc.id, fl.id


def test_physical_seat_creation_is_not_a_saas_tier_cap():
    app = _app()
    loc_id, fl_id = _seed_operator_with_tier(app)
    c = app.test_client()
    _login(c, "admin@smallco.com", "AdminPass123!")

    seat_data = lambda code: {
        "floor_id": fl_id, "code": code, "seat_type": "hot_desk", "capacity": 1,
        "hourly_rate": 0, "daily_rate": 0, "monthly_rate": 0,
    }
    r1 = c.post(f"/admin/locations/{loc_id}/seats/new", data=seat_data("HD-01"), follow_redirects=True)
    assert b"Seat created" in r1.data

    r2 = c.post(f"/admin/locations/{loc_id}/seats/new", data=seat_data("HD-02"), follow_redirects=True)
    assert b"Seat created" in r2.data
    with app.app_context():
        from app.models import Seat
        assert Seat.query.filter_by(code="HD-02").first() is not None


def test_private_offices_are_operational_inventory_not_saas_caps():
    app = _app()
    loc_id, fl_id = _seed_operator_with_tier(app)
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
    assert b"Seat created" in add("PO-02", "private_office").data


def test_rooms_are_not_capped_but_locations_are_enforced():
    app = _app()
    loc_id, fl_id = _seed_operator_with_tier(app, max_locations=1)
    c = app.test_client()
    _login(c, "admin@smallco.com", "AdminPass123!")

    r = c.post(f"/admin/locations/{loc_id}/rooms/new", data={
        "floor_id": fl_id, "code": "R1", "name": "Room 1", "capacity": 4,
        "hourly_rate": 0, "category_id": 0,
    }, follow_redirects=True)
    assert b"Room created" in r.data

    r = c.post("/admin/locations/new", data={
        "name": "Branch", "code": "BR", "address_line1": "y",
        "city": "c2", "country": "IN", "timezone": "Asia/Kolkata",
    }, follow_redirects=True)
    assert b"plan allows up to 1 location" in r.data


def test_no_tier_configured_fails_open():
    """An operator on a plan_tier string with no matching PricingTier row isn't blocked."""
    app = _app()
    with app.app_context():
        t = Operator(slug="notier", name="No Tier Co", primary_domain="notier.hub1z.com",
                   status=OperatorStatus.ACTIVE, plan_tier="nonexistent")
        db.session.add(t); db.session.flush()
        admin = User(operator_id=t.id, email="admin@notier.com", full_name="Admin",
                    role=UserRole.SUPER_ADMIN, is_active=True)
        admin.set_password("AdminPass123!")
        db.session.add(admin)
        loc = Location(operator_id=t.id, name="HQ", code="HQ", address_line1="x",
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
