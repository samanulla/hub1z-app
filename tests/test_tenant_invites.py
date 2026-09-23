"""Tenant-initiated invites: tenant admin invites an individual or a company."""
import os
os.environ.setdefault("FLASK_ENV", "testing")

from app import create_app
from app.extensions import db
from app.models import User, UserRole, Company, CompanyStatus, Tenant, TenantStatus
from app.services import mail_service


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


def _seed_tenant_admin(app, email="admin@adyarspace.com", password="AdminPass123!"):
    with app.app_context():
        t = Tenant.query.first()
        u = User(tenant_id=t.id, email=email, full_name="Admin",
                 role=UserRole.SUPER_ADMIN, is_active=True)
        u.set_password(password)
        db.session.add(u); db.session.commit()


def _login(client, email, password):
    return client.post("/auth/login", data={"email": email, "password": password})


def test_invites_pages_render():
    app = _app()
    _seed_tenant_admin(app)
    c = app.test_client()
    _login(c, "admin@adyarspace.com", "AdminPass123!")
    for path in ("/admin/invites", "/admin/invites/individual/new", "/admin/invites/company/new"):
        r = c.get(path)
        assert r.status_code == 200, f"{path} -> {r.status_code}: {r.data[:500]}"


def test_invite_individual_creates_inactive_user():
    app = _app()
    _seed_tenant_admin(app)
    c = app.test_client()
    _login(c, "admin@adyarspace.com", "AdminPass123!")

    r = c.post("/admin/invites/individual/new", data={
        "full_name": "Prospective Member", "email": "member@example.com",
    }, follow_redirects=False)
    assert r.status_code == 302

    with app.app_context():
        u = User.query.filter_by(email="member@example.com") \
                       .execution_options(skip_tenant_filter=True).first()
        assert u is not None
        assert u.role == UserRole.INDIVIDUAL
        assert u.is_active is False
        assert u.tenant_id is not None


def test_accept_individual_invite_activates_and_logs_in():
    app = _app()
    _seed_tenant_admin(app)
    with app.app_context():
        t = Tenant.query.first()
        u = User(tenant_id=t.id, email="pending@example.com", full_name="Pending",
                 role=UserRole.INDIVIDUAL, is_active=False)
        u.set_password("placeholder1234")
        db.session.add(u); db.session.commit()
        token = mail_service.make_token(u.id, "tenant-member-invite")

    client = app.test_client()
    r = client.get(f"/admin/invites/accept/{token}")
    assert r.status_code == 200
    r = client.post(f"/admin/invites/accept/{token}",
                    data={"password": "NewPass456!", "confirm": "NewPass456!"},
                    follow_redirects=False)
    assert r.status_code == 302
    with app.app_context():
        u = User.query.filter_by(email="pending@example.com") \
                       .execution_options(skip_tenant_filter=True).first()
        assert u.is_active is True
        assert u.check_password("NewPass456!")


def test_invite_company_creates_prospect_company_and_inactive_admin():
    app = _app()
    _seed_tenant_admin(app)
    c = app.test_client()
    _login(c, "admin@adyarspace.com", "AdminPass123!")

    r = c.post("/admin/invites/company/new", data={
        "company_name": "Acme Robotics", "billing_email": "billing@acme.example",
        "admin_full_name": "Jane Doe", "admin_email": "jane@acme.example",
    }, follow_redirects=False)
    assert r.status_code == 302

    with app.app_context():
        company = Company.query.filter_by(name="Acme Robotics") \
                                .execution_options(skip_tenant_filter=True).first()
        assert company is not None
        assert company.status == CompanyStatus.PROSPECT
        admin = User.query.filter_by(email="jane@acme.example") \
                          .execution_options(skip_tenant_filter=True).first()
        assert admin is not None
        assert admin.role == UserRole.COMPANY_ADMIN
        assert admin.is_active is False
        assert admin.company_id == company.id


def test_accept_company_invite_activates_company_and_admin():
    app = _app()
    _seed_tenant_admin(app)
    with app.app_context():
        t = Tenant.query.first()
        company = Company(tenant_id=t.id, name="Beta Co", billing_email="b@beta.example",
                          status=CompanyStatus.PROSPECT)
        db.session.add(company); db.session.flush()
        admin = User(tenant_id=t.id, email="admin@beta.example", full_name="Beta Admin",
                    role=UserRole.COMPANY_ADMIN, company_id=company.id, is_active=False)
        admin.set_password("placeholder1234")
        db.session.add(admin); db.session.commit()
        token = mail_service.make_token(admin.id, "tenant-company-invite")

    client = app.test_client()
    r = client.post(f"/admin/invites/accept-company/{token}",
                    data={"password": "NewPass456!", "confirm": "NewPass456!"},
                    follow_redirects=False)
    assert r.status_code == 302
    assert "/company/" in r.headers.get("Location", "")
    with app.app_context():
        company = Company.query.filter_by(name="Beta Co").execution_options(skip_tenant_filter=True).first()
        admin = User.query.filter_by(email="admin@beta.example").execution_options(skip_tenant_filter=True).first()
        assert company.status == CompanyStatus.ACTIVE
        assert admin.is_active is True


def test_revoke_pending_individual_invite():
    app = _app()
    _seed_tenant_admin(app)
    with app.app_context():
        t = Tenant.query.first()
        u = User(tenant_id=t.id, email="tobecanceled@example.com", full_name="Cancel",
                 role=UserRole.INDIVIDUAL, is_active=False)
        u.set_password("placeholder1234")
        db.session.add(u); db.session.commit()
        uid = u.id

    c = app.test_client()
    _login(c, "admin@adyarspace.com", "AdminPass123!")
    r = c.post(f"/admin/invites/individual/{uid}/revoke", follow_redirects=False)
    assert r.status_code == 302
    with app.app_context():
        assert db.session.get(User, uid) is None


def test_self_serve_registration_is_tenant_scoped():
    """Existing self-serve routes should already scope new accounts to the
    resolved tenant (Host header / dev fallback), not leave tenant_id null."""
    app = _app()
    c = app.test_client()
    r = c.post("/auth/register", data={
        "full_name": "Self Signup", "email": "selfsignup@example.com",
        "phone": "", "password": "SelfPass123!", "confirm": "SelfPass123!",
    }, follow_redirects=False)
    assert r.status_code == 302
    with app.app_context():
        u = User.query.filter_by(email="selfsignup@example.com") \
                       .execution_options(skip_tenant_filter=True).first()
        assert u is not None
        assert u.tenant_id is not None
