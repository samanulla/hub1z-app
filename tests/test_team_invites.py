"""Tenant Super Admin invites Manager/Location Manager logins — the missing
piece: previously there was no UI at all to create these, only the platform
CLI (which only supports --platform-owner/--tenant-super-admin)."""
import os
os.environ.setdefault("FLASK_ENV", "testing")

from app import create_app
from app.extensions import db
from app.models import User, UserRole, Tenant, TenantStatus, Location
from app.services import mail_service


def _app():
    app = create_app({"SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
                      "WTF_CSRF_ENABLED": False,
                      "MAIL_SUPPRESS_SEND": True,
                      "STORAGE_BACKEND": "local",
                      "LOCAL_STORAGE_DIR": "./var/test-uploads"})
    with app.app_context():
        db.create_all()
    return app


def _seed_tenant_with_two_locations(app):
    with app.app_context():
        t = Tenant(slug="multiloc", name="Multi Loc Co", primary_domain="multiloc.hub1z.com",
                   status=TenantStatus.ACTIVE)
        db.session.add(t); db.session.flush()
        admin = User(tenant_id=t.id, email="admin@multiloc.com", full_name="Admin",
                    role=UserRole.SUPER_ADMIN, is_active=True)
        admin.set_password("AdminPass123!")
        db.session.add(admin)
        loc1 = Location(tenant_id=t.id, name="HQ", code="HQ", address_line1="x",
                        city="c", country="IN", timezone="Asia/Kolkata")
        loc2 = Location(tenant_id=t.id, name="Branch", code="BR", address_line1="y",
                        city="c2", country="IN", timezone="Asia/Kolkata")
        db.session.add_all([loc1, loc2]); db.session.commit()
        return loc1.id, loc2.id


def _login(client, email, password):
    return client.post("/auth/login", data={"email": email, "password": password})


def test_invite_location_manager_requires_a_location():
    app = _app()
    _seed_tenant_with_two_locations(app)
    c = app.test_client()
    _login(c, "admin@multiloc.com", "AdminPass123!")

    r = c.post("/admin/invites/team/new", data={
        "full_name": "Lee Mgr", "email": "lee@multiloc.com",
        "role": "location_manager", "location_id": 0,
    }, follow_redirects=True)
    assert b"Pick a location" in r.data
    with app.app_context():
        assert User.query.filter_by(email="lee@multiloc.com").first() is None


def test_invite_and_accept_location_manager():
    app = _app()
    loc1_id, loc2_id = _seed_tenant_with_two_locations(app)
    c = app.test_client()
    _login(c, "admin@multiloc.com", "AdminPass123!")

    r = c.post("/admin/invites/team/new", data={
        "full_name": "Lee Mgr", "email": "lee@multiloc.com",
        "role": "location_manager", "location_id": loc2_id,
    }, follow_redirects=False)
    assert r.status_code == 302

    with app.app_context():
        u = User.query.filter_by(email="lee@multiloc.com") \
                      .execution_options(skip_tenant_filter=True).first()
        assert u.role == UserRole.LOCATION_MANAGER
        assert u.managed_location_id == loc2_id
        assert u.is_active is False
        token = mail_service.make_token(u.id, "tenant-team-invite")

    client2 = app.test_client()
    r = client2.post(f"/admin/invites/accept-team/{token}",
                     data={"password": "LeePass123!", "confirm": "LeePass123!"},
                     follow_redirects=False)
    assert r.status_code == 302
    with app.app_context():
        u = User.query.filter_by(email="lee@multiloc.com") \
                      .execution_options(skip_tenant_filter=True).first()
        assert u.is_active is True


def test_invite_tenant_wide_manager_has_no_managed_location():
    app = _app()
    _seed_tenant_with_two_locations(app)
    c = app.test_client()
    _login(c, "admin@multiloc.com", "AdminPass123!")

    r = c.post("/admin/invites/team/new", data={
        "full_name": "Mo Manager", "email": "mo@multiloc.com",
        "role": "manager", "location_id": 0,
    }, follow_redirects=False)
    assert r.status_code == 302
    with app.app_context():
        u = User.query.filter_by(email="mo@multiloc.com") \
                      .execution_options(skip_tenant_filter=True).first()
        assert u.role == UserRole.MANAGER
        assert u.managed_location_id is None


def test_manager_cannot_invite_team_members():
    """Sending a team invite is Super-Admin-only, same privilege-escalation
    guard as Platform Manager creation — an existing tenant Manager can't
    grow the team themselves."""
    app = _app()
    with app.app_context():
        t = Tenant(slug="multiloc", name="Multi Loc Co", primary_domain="multiloc.hub1z.com",
                   status=TenantStatus.ACTIVE)
        db.session.add(t); db.session.flush()
        mgr = User(tenant_id=t.id, email="mgr@multiloc.com", full_name="Mgr",
                  role=UserRole.MANAGER, is_active=True)
        mgr.set_password("MgrPass123!")
        db.session.add(mgr); db.session.commit()

    c = app.test_client()
    _login(c, "mgr@multiloc.com", "MgrPass123!")
    assert c.get("/admin/invites/team/new").status_code == 403


def test_team_invite_appears_in_invites_list_and_can_be_revoked():
    app = _app()
    _seed_tenant_with_two_locations(app)
    c = app.test_client()
    _login(c, "admin@multiloc.com", "AdminPass123!")
    c.post("/admin/invites/team/new", data={
        "full_name": "Lee Mgr", "email": "lee@multiloc.com",
        "role": "location_manager", "location_id": 1,
    })
    r = c.get("/admin/invites")
    assert r.status_code == 200
    assert b"lee@multiloc.com" in r.data

    with app.app_context():
        uid = User.query.filter_by(email="lee@multiloc.com").first().id
    r = c.post(f"/admin/invites/team/{uid}/revoke", follow_redirects=False)
    assert r.status_code == 302
    with app.app_context():
        assert db.session.get(User, uid) is None
