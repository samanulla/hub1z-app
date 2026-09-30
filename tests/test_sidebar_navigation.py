"""Sidebar navigation renders without BuildErrors and is gated per role,
matching each linked route's actual decorator (see grep audit in review)."""
import os
os.environ.setdefault("FLASK_ENV", "testing")

from app import create_app
from app.extensions import db
from app.models import Operator, OperatorStatus, User, UserRole, Location, Floor, Company, CompanyStatus


def _app():
    app = create_app({"SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
                      "WTF_CSRF_ENABLED": False,
                      "MAIL_SUPPRESS_SEND": True,
                      "STORAGE_BACKEND": "local",
                      "LOCAL_STORAGE_DIR": "./var/test-uploads"})
    with app.app_context():
        db.create_all()
    return app


def _login(client, email, password, host=None):
    headers = {"Host": host} if host else None
    return client.post("/auth/login", data={"email": email, "password": password}, headers=headers)


def test_super_admin_sees_full_admin_sidebar():
    app = _app()
    with app.app_context():
        t = Operator(slug="side1", name="Side One", primary_domain="side1.hub1z.com",
                  status=OperatorStatus.ACTIVE)
        db.session.add(t); db.session.flush()
        u = User(operator_id=t.id, email="super@side1.com", full_name="Super",
                role=UserRole.SUPER_ADMIN, is_active=True)
        u.set_password("SuperPass123!")
        db.session.add(u); db.session.commit()

    c = app.test_client()
    _login(c, "super@side1.com", "SuperPass123!")
    r = c.get("/admin/")
    assert r.status_code == 200
    assert b"System settings" in r.data
    assert b"Audit log" in r.data
    assert b"Invites" in r.data


def test_location_manager_sees_restricted_admin_sidebar():
    app = _app()
    with app.app_context():
        t = Operator(slug="side2", name="Side Two", primary_domain="side2.hub1z.com",
                  status=OperatorStatus.ACTIVE)
        db.session.add(t); db.session.flush()
        loc = Location(operator_id=t.id, name="HQ", code="HQ", address_line1="x",
                       city="c", country="IN", timezone="Asia/Kolkata")
        db.session.add(loc); db.session.flush()
        u = User(operator_id=t.id, email="loc@side2.com", full_name="Loc Mgr",
                role=UserRole.LOCATION_MANAGER, managed_location_id=loc.id, is_active=True)
        u.set_password("LocPass123!")
        db.session.add(u); db.session.commit()

    c = app.test_client()
    _login(c, "loc@side2.com", "LocPass123!")
    r = c.get("/admin/")
    assert r.status_code == 200
    assert b"System settings" not in r.data
    assert b"Audit log" not in r.data
    assert b"Invites" not in r.data
    assert b"Locations &amp; seats" in r.data or b"Locations" in r.data


def test_platform_owner_sees_full_platform_sidebar():
    app = _app()
    with app.app_context():
        u = User(email="owner3@hub1z.com", full_name="Owner", role=UserRole.PLATFORM_OWNER, is_active=True)
        u.set_password("OwnerPass123!")
        db.session.add(u); db.session.commit()

    c = app.test_client()
    _login(c, "owner3@hub1z.com", "OwnerPass123!", host="hub1z.com")
    r = c.get("/platform/", headers={"Host": "hub1z.com"})
    assert r.status_code == 200
    assert b"Pricing tiers" in r.data
    assert b"Platform team" in r.data
    assert b"Invite operator" in r.data


def test_platform_manager_with_reports_only_sees_restricted_sidebar():
    app = _app()
    with app.app_context():
        mgr = User(email="repmgr@hub1z.com", full_name="Report Mgr",
                  role=UserRole.PLATFORM_MANAGER, is_active=True)
        mgr.set_password("MgrPass123!")
        mgr.set_platform_permissions(["reports"])
        db.session.add(mgr); db.session.commit()

    c = app.test_client()
    _login(c, "repmgr@hub1z.com", "MgrPass123!", host="hub1z.com")
    r = c.get("/platform/", headers={"Host": "hub1z.com"})
    assert r.status_code == 200
    assert b"Reports" in r.data
    assert b"Invite operator" not in r.data
    assert b"Pricing tiers" not in r.data
    assert b"Platform team" not in r.data


def test_company_admin_sees_company_sidebar():
    app = _app()
    with app.app_context():
        t = Operator(slug="side4", name="Side Four", primary_domain="side4.hub1z.com",
                  status=OperatorStatus.ACTIVE)
        db.session.add(t); db.session.flush()
        company = Company(operator_id=t.id, name="Sidebar Co", billing_email="c@side4.com",
                          status=CompanyStatus.ACTIVE)
        db.session.add(company); db.session.flush()
        u = User(operator_id=t.id, email="ca@side4.com", full_name="Company Admin",
                role=UserRole.COMPANY_ADMIN, company_id=company.id, is_active=True)
        u.set_password("CaPass123!")
        db.session.add(u); db.session.commit()

    c = app.test_client()
    _login(c, "ca@side4.com", "CaPass123!")
    r = c.get("/company/")
    assert r.status_code == 200
    assert b'<aside class="h-side"' in r.data
    assert b"Plans &amp; subscriptions" in r.data
    assert b"Seat allocations" in r.data


def test_company_and_member_pages_unaffected_by_sidebar():
    app = _app()
    with app.app_context():
        t = Operator(slug="side3", name="Side Three", primary_domain="side3.hub1z.com",
                  status=OperatorStatus.ACTIVE)
        db.session.add(t); db.session.flush()
        u = User(operator_id=t.id, email="ind@side3.com", full_name="Ind",
                role=UserRole.INDIVIDUAL, is_active=True)
        u.set_password("IndPass123!")
        db.session.add(u); db.session.commit()

    c = app.test_client()
    _login(c, "ind@side3.com", "IndPass123!")
    r = c.get("/me/")
    assert r.status_code == 200
    assert b'<aside class="h-side"' in r.data
    assert b"My space" in r.data and b"Announcements" in r.data
    assert b"Billing &amp; finance" not in r.data and b"Pricing plans" not in r.data
