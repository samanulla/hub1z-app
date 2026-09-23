"""Tenant lifecycle: platform invites a tenant -> TRIAL -> Approve -> ACTIVE,
plus Hold (shared) vs Suspend/Deactivate (Platform Super Admin only)."""
import os
os.environ.setdefault("FLASK_ENV", "testing")

from app import create_app
from app.extensions import db
from app.models import User, UserRole, Tenant, TenantStatus
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


def _seed_owner(app, email="platform@hub1z.com", password="OwnerPass123!"):
    with app.app_context():
        u = User(email=email, full_name="Owner", role=UserRole.PLATFORM_OWNER, is_active=True)
        u.set_password(password)
        db.session.add(u); db.session.commit()


def _login(client, email, password):
    return client.post("/auth/login", data={"email": email, "password": password})


def test_platform_owner_post_login_redirects_to_platform():
    app = _app()
    _seed_owner(app)
    c = app.test_client()
    _login(c, "platform@hub1z.com", "OwnerPass123!")
    r = c.get("/auth/post-login", follow_redirects=False)
    assert r.headers["Location"].endswith("/platform/")


def test_platform_manager_post_login_redirects_to_platform():
    app = _app()
    with app.app_context():
        mgr = User(email="mgr@hub1z.com", full_name="Mgr", role=UserRole.PLATFORM_MANAGER, is_active=True)
        mgr.set_password("MgrPass123!")
        mgr.set_platform_permissions(["tenants"])
        db.session.add(mgr); db.session.commit()
    c = app.test_client()
    _login(c, "mgr@hub1z.com", "MgrPass123!")
    r = c.get("/auth/post-login", follow_redirects=False)
    assert r.headers["Location"].endswith("/platform/")


def test_invite_tenant_creates_trial_tenant_and_inactive_admin():
    app = _app()
    _seed_owner(app)
    c = app.test_client()
    _login(c, "platform@hub1z.com", "OwnerPass123!")
    r = c.post("/platform/tenants/invite", data={
        "slug": "newbiz", "name": "New Biz",
        "admin_name": "Nina Admin", "admin_email": "nina@newbiz.com",
    }, follow_redirects=False)
    assert r.status_code == 302
    with app.app_context():
        t = Tenant.query.filter_by(slug="newbiz").first()
        assert t.status == TenantStatus.TRIAL
        admin = User.query.filter_by(email="nina@newbiz.com") \
                          .execution_options(skip_tenant_filter=True).first()
        assert admin.role == UserRole.SUPER_ADMIN
        assert admin.is_active is False
        assert admin.tenant_id == t.id


def test_accept_tenant_invite_activates_admin_but_not_tenant():
    app = _app()
    with app.app_context():
        t = Tenant(slug="newbiz", name="New Biz", primary_domain="newbiz.hub1z.com",
                   status=TenantStatus.TRIAL)
        db.session.add(t); db.session.flush()
        admin = User(tenant_id=t.id, email="nina@newbiz.com", full_name="Nina",
                    role=UserRole.SUPER_ADMIN, is_active=False)
        admin.set_password("placeholder1234")
        db.session.add(admin); db.session.commit()
        token = mail_service.make_token(admin.id, "platform-tenant-invite")

    client = app.test_client()
    r = client.post(f"/platform/tenants/accept/{token}",
                    data={"password": "NinaPass123!", "confirm": "NinaPass123!"},
                    follow_redirects=False)
    assert r.status_code == 302
    with app.app_context():
        admin = User.query.filter_by(email="nina@newbiz.com") \
                          .execution_options(skip_tenant_filter=True).first()
        t = Tenant.query.filter_by(slug="newbiz").first()
        assert admin.is_active is True
        assert admin.check_password("NinaPass123!")
        assert t.status == TenantStatus.TRIAL  # still pending approval


def test_approve_moves_trial_to_active_and_only_from_trial():
    app = _app()
    _seed_owner(app)
    with app.app_context():
        t = Tenant(slug="newbiz", name="New Biz", primary_domain="newbiz.hub1z.com",
                   status=TenantStatus.TRIAL)
        db.session.add(t); db.session.commit()
        tid = t.id

    c = app.test_client()
    _login(c, "platform@hub1z.com", "OwnerPass123!")
    c.post(f"/platform/tenants/{tid}/approve")
    with app.app_context():
        assert db.session.get(Tenant, tid).status == TenantStatus.ACTIVE

    # Approving again (already active, not trial) is a no-op, not an error.
    r = c.post(f"/platform/tenants/{tid}/approve", follow_redirects=False)
    assert r.status_code == 302
    with app.app_context():
        assert db.session.get(Tenant, tid).status == TenantStatus.ACTIVE


def test_manager_with_tenants_permission_can_hold_and_release():
    app = _app()
    _seed_owner(app)
    with app.app_context():
        t = Tenant(slug="adyarspace", name="Adyar Space", primary_domain="adyarspace.hub1z.com",
                   status=TenantStatus.ACTIVE)
        db.session.add(t)
        mgr = User(email="mgr@hub1z.com", full_name="Mgr", role=UserRole.PLATFORM_MANAGER, is_active=True)
        mgr.set_password("MgrPass123!")
        mgr.set_platform_permissions(["tenants"])
        db.session.add(mgr); db.session.commit()
        tid = t.id

    c = app.test_client()
    _login(c, "mgr@hub1z.com", "MgrPass123!")
    r = c.post(f"/platform/tenants/{tid}/hold", follow_redirects=False)
    assert r.status_code == 302
    with app.app_context():
        assert db.session.get(Tenant, tid).status == TenantStatus.HOLD

    r = c.post(f"/platform/tenants/{tid}/release-hold", follow_redirects=False)
    assert r.status_code == 302
    with app.app_context():
        assert db.session.get(Tenant, tid).status == TenantStatus.ACTIVE


def test_manager_cannot_suspend_or_reactivate_even_with_tenants_permission():
    app = _app()
    _seed_owner(app)
    with app.app_context():
        t = Tenant(slug="adyarspace", name="Adyar Space", primary_domain="adyarspace.hub1z.com",
                   status=TenantStatus.ACTIVE)
        db.session.add(t)
        mgr = User(email="mgr@hub1z.com", full_name="Mgr", role=UserRole.PLATFORM_MANAGER, is_active=True)
        mgr.set_password("MgrPass123!")
        mgr.set_platform_permissions(["tenants", "billing", "reports"])  # even with everything
        db.session.add(mgr); db.session.commit()
        tid = t.id

    c = app.test_client()
    _login(c, "mgr@hub1z.com", "MgrPass123!")
    assert c.post(f"/platform/tenants/{tid}/suspend").status_code == 403
    assert c.post(f"/platform/tenants/{tid}/activate").status_code == 403
    with app.app_context():
        assert db.session.get(Tenant, tid).status == TenantStatus.ACTIVE


def test_owner_can_suspend_and_reactivate():
    app = _app()
    _seed_owner(app)
    with app.app_context():
        t = Tenant(slug="adyarspace", name="Adyar Space", primary_domain="adyarspace.hub1z.com",
                   status=TenantStatus.ACTIVE)
        db.session.add(t); db.session.commit()
        tid = t.id

    c = app.test_client()
    _login(c, "platform@hub1z.com", "OwnerPass123!")
    c.post(f"/platform/tenants/{tid}/suspend")
    with app.app_context():
        assert db.session.get(Tenant, tid).status == TenantStatus.SUSPENDED

    c.post(f"/platform/tenants/{tid}/activate")
    with app.app_context():
        assert db.session.get(Tenant, tid).status == TenantStatus.ACTIVE


def test_hold_is_blocked_while_suspended():
    app = _app()
    _seed_owner(app)
    with app.app_context():
        t = Tenant(slug="adyarspace", name="Adyar Space", primary_domain="adyarspace.hub1z.com",
                   status=TenantStatus.SUSPENDED)
        db.session.add(t); db.session.commit()
        tid = t.id

    c = app.test_client()
    _login(c, "platform@hub1z.com", "OwnerPass123!")
    c.post(f"/platform/tenants/{tid}/hold")
    with app.app_context():
        # Owner also has the 'tenants' feature implicitly, but hold shouldn't
        # override a hard suspend.
        assert db.session.get(Tenant, tid).status == TenantStatus.SUSPENDED
