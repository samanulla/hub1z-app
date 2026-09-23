"""Platform Manager role: Owner-created logins with admin-granted feature permissions."""
import os
os.environ.setdefault("FLASK_ENV", "testing")

from app import create_app
from app.extensions import db
from app.models import User, UserRole, Tenant, TenantStatus


def _app():
    app = create_app({"SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
                      "WTF_CSRF_ENABLED": False,
                      "MAIL_SUPPRESS_SEND": True,
                      "STORAGE_BACKEND": "local",
                      "LOCAL_STORAGE_DIR": "./var/test-uploads"})
    with app.app_context():
        db.create_all()
        t = Tenant(slug="adyarspace", name="Adyar Space",
                   primary_domain="adyarspace.coworkhub.io", status=TenantStatus.ACTIVE)
        db.session.add(t); db.session.commit()
    return app


def _seed_owner(app, email="platform@coworkhub.io", password="OwnerPass123!"):
    with app.app_context():
        u = User(email=email, full_name="Owner", role=UserRole.PLATFORM_OWNER, is_active=True)
        u.set_password(password)
        db.session.add(u); db.session.commit()


def _login(client, email, password):
    return client.post("/auth/login", data={"email": email, "password": password})


def test_owner_pages_render():
    app = _app()
    _seed_owner(app)
    c = app.test_client()
    _login(c, "platform@coworkhub.io", "OwnerPass123!")
    for path in ("/platform/", "/platform/team", "/platform/team/new",
                "/platform/reports", "/platform/billing", "/platform/tenants"):
        r = c.get(path)
        assert r.status_code == 200, f"{path} -> {r.status_code}: {r.data[:500]}"


def test_owner_can_create_manager_with_partial_permissions():
    app = _app()
    _seed_owner(app)
    c = app.test_client()
    _login(c, "platform@coworkhub.io", "OwnerPass123!")

    r = c.post("/platform/team/new", data={
        "full_name": "Ravi Manager", "email": "ravi@coworkhub.io",
        "password": "ManagerPass123!", "is_active": "y",
        "perm_reports": "y",  # only reports — tenants/billing left unchecked
    }, follow_redirects=False)
    assert r.status_code == 302

    with app.app_context():
        mgr = User.query.filter_by(email="ravi@coworkhub.io").execution_options(skip_tenant_filter=True).first()
        assert mgr is not None
        assert mgr.role == UserRole.PLATFORM_MANAGER
        assert mgr.get_platform_permissions() == ["reports"]
        assert mgr.has_platform_permission("reports") is True
        assert mgr.has_platform_permission("tenants") is False


def test_manager_without_tenants_permission_is_forbidden():
    app = _app()
    _seed_owner(app)
    with app.app_context():
        mgr = User(email="mgr@coworkhub.io", full_name="Mgr", role=UserRole.PLATFORM_MANAGER, is_active=True)
        mgr.set_password("ManagerPass123!")
        mgr.set_platform_permissions(["reports"])
        db.session.add(mgr); db.session.commit()

    c = app.test_client()
    _login(c, "mgr@coworkhub.io", "ManagerPass123!")

    # Dashboard (staff-only, not feature-gated) is reachable.
    r = c.get("/platform/")
    assert r.status_code == 200

    # Reports is granted.
    r = c.get("/platform/reports")
    assert r.status_code == 200

    # Tenants is not granted.
    r = c.get("/platform/tenants")
    assert r.status_code == 403

    # Managing the platform team is always Owner-only, regardless of grants.
    r = c.get("/platform/team")
    assert r.status_code == 403
    r = c.get("/platform/team/new")
    assert r.status_code == 403


def test_manager_with_tenants_permission_can_manage_tenants():
    app = _app()
    _seed_owner(app)
    with app.app_context():
        mgr = User(email="mgr2@coworkhub.io", full_name="Mgr2", role=UserRole.PLATFORM_MANAGER, is_active=True)
        mgr.set_password("ManagerPass123!")
        mgr.set_platform_permissions(["tenants"])
        db.session.add(mgr); db.session.commit()

    c = app.test_client()
    _login(c, "mgr2@coworkhub.io", "ManagerPass123!")
    r = c.get("/platform/tenants")
    assert r.status_code == 200
    assert b"Adyar Space" in r.data


def test_deactivated_manager_cannot_log_in():
    app = _app()
    _seed_owner(app)
    with app.app_context():
        mgr = User(email="gone@coworkhub.io", full_name="Gone", role=UserRole.PLATFORM_MANAGER, is_active=False)
        mgr.set_password("ManagerPass123!")
        mgr.set_platform_permissions(["tenants", "billing", "reports"])
        db.session.add(mgr); db.session.commit()

    c = app.test_client()
    r = _login(c, "gone@coworkhub.io", "ManagerPass123!")
    r2 = c.get("/platform/")
    # Login silently fails for inactive users (existing app behaviour); the
    # dashboard should redirect to login rather than render.
    assert r2.status_code in (302, 401, 403)


def test_manager_edit_page_prefills_permission_checkboxes():
    app = _app()
    _seed_owner(app)
    with app.app_context():
        mgr = User(email="mgr3@coworkhub.io", full_name="Mgr3", role=UserRole.PLATFORM_MANAGER, is_active=True)
        mgr.set_password("ManagerPass123!")
        mgr.set_platform_permissions(["tenants"])
        db.session.add(mgr); db.session.commit()
        mgr_id = mgr.id

    c = app.test_client()
    _login(c, "platform@coworkhub.io", "OwnerPass123!")
    r = c.get(f"/platform/team/{mgr_id}/edit")
    assert r.status_code == 200
    html = r.data.decode()
    assert 'checked' in html.split('id="perm_tenants"')[0][-40:]
    assert 'checked' not in html.split('id="perm_billing"')[0][-40:]
