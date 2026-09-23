"""'No of seats = no of people, always' — a tenant on a lower tier can't
sidestep the seat cap by just piling on employee/individual/company-admin
accounts instead of buying more desks. Enforced across every place a new
person gets attached to a tenant: self-serve signup, tenant-initiated
invites, and a company adding its own employees."""
import os
os.environ.setdefault("FLASK_ENV", "testing")

from app import create_app
from app.extensions import db
from app.models import User, UserRole, Tenant, TenantStatus, PricingTier, Company, CompanyStatus


def _app():
    app = create_app({"SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
                      "WTF_CSRF_ENABLED": False,
                      "MAIL_SUPPRESS_SEND": True,
                      "STORAGE_BACKEND": "local",
                      "LOCAL_STORAGE_DIR": "./var/test-uploads"})
    with app.app_context():
        db.create_all()
    return app


def _seed_tenant_at_cap(app, max_seats, existing_people=0):
    """Tenant on a tier capped at `max_seats` people, with `existing_people`
    individuals already burning through that cap."""
    with app.app_context():
        t = Tenant(slug="tiny", name="Tiny Co", primary_domain="tiny.hub1z.com",
                  status=TenantStatus.ACTIVE, plan_tier="starter")
        db.session.add(t); db.session.flush()
        db.session.add(PricingTier(key="starter", name="Starter", is_active=True, max_seats=max_seats))
        admin = User(tenant_id=t.id, email="admin@tiny.com", full_name="Admin",
                    role=UserRole.SUPER_ADMIN, is_active=True)
        admin.set_password("AdminPass123!")
        db.session.add(admin)
        for i in range(existing_people):
            u = User(tenant_id=t.id, email=f"person{i}@tiny.com", full_name=f"Person {i}",
                    role=UserRole.INDIVIDUAL, is_active=True)
            u.set_password("PersonPass123!")
            db.session.add(u)
        db.session.commit()


def _login(client, email, password):
    return client.post("/auth/login", data={"email": email, "password": password})


def test_self_serve_individual_blocked_at_person_cap():
    app = _app()
    _seed_tenant_at_cap(app, max_seats=1, existing_people=1)
    c = app.test_client()
    r = c.post("/auth/register", data={
        "full_name": "One Too Many", "email": "overflow@tiny.com",
        "phone": "", "password": "OverPass123!", "confirm": "OverPass123!",
    }, follow_redirects=True)
    assert b"plan allows up to 1" in r.data
    with app.app_context():
        assert User.query.filter_by(email="overflow@tiny.com").first() is None


def test_self_serve_individual_allowed_under_person_cap():
    app = _app()
    _seed_tenant_at_cap(app, max_seats=5, existing_people=1)
    c = app.test_client()
    r = c.post("/auth/register", data={
        "full_name": "Fits Fine", "email": "fits@tiny.com",
        "phone": "", "password": "FitsPass123!", "confirm": "FitsPass123!",
    }, follow_redirects=True)
    with app.app_context():
        assert User.query.filter_by(email="fits@tiny.com").first() is not None


def test_self_serve_company_signup_blocked_at_person_cap():
    app = _app()
    _seed_tenant_at_cap(app, max_seats=1, existing_people=1)
    c = app.test_client()
    r = c.post("/auth/register/company", data={
        "company_name": "New Co", "billing_email": "b@newco.example",
        "admin_full_name": "New Admin", "admin_email": "newadmin@newco.example",
        "password": "NewPass123!", "confirm": "NewPass123!",
    }, follow_redirects=True)
    assert b"plan allows up to 1" in r.data
    with app.app_context():
        assert Company.query.filter_by(name="New Co").first() is None


def test_tenant_invite_individual_blocked_at_person_cap():
    app = _app()
    _seed_tenant_at_cap(app, max_seats=1, existing_people=1)
    c = app.test_client()
    _login(c, "admin@tiny.com", "AdminPass123!")
    r = c.post("/admin/invites/individual/new", data={
        "full_name": "Overflow", "email": "overflow2@tiny.com",
    }, follow_redirects=True)
    assert b"plan allows up to 1" in r.data
    with app.app_context():
        assert User.query.filter_by(email="overflow2@tiny.com").first() is None


def test_company_admin_employee_add_blocked_at_person_cap():
    """The explicitly-named scenario: a company signs up under a tenant and
    tries to add employees past the tenant's approved tier."""
    app = _app()
    with app.app_context():
        t = Tenant(slug="tiny", name="Tiny Co", primary_domain="tiny.hub1z.com",
                  status=TenantStatus.ACTIVE, plan_tier="starter")
        db.session.add(t); db.session.flush()
        db.session.add(PricingTier(key="starter", name="Starter", is_active=True, max_seats=1))
        company = Company(tenant_id=t.id, name="Acme", billing_email="b@acme.example",
                          status=CompanyStatus.ACTIVE, max_employees=99)  # company's own cap is generous
        db.session.add(company); db.session.flush()
        ca = User(tenant_id=t.id, email="jane@acme.example", full_name="Jane",
                 role=UserRole.COMPANY_ADMIN, company_id=company.id, is_active=True)
        ca.set_password("JanePass123!")
        db.session.add(ca); db.session.commit()

    c = app.test_client()
    _login(c, "jane@acme.example", "JanePass123!")
    # Jane (company_admin) already occupies the tenant's only "seat".
    r = c.post("/company/employees/new", data={
        "full_name": "New Hire", "email": "hire@acme.example", "phone": "",
    }, follow_redirects=True)
    assert b"plan allows up to 1" in r.data
    with app.app_context():
        assert User.query.filter_by(email="hire@acme.example").first() is None


def test_no_tier_configured_fails_open_for_people_too():
    app = _app()
    with app.app_context():
        t = Tenant(slug="notier", name="No Tier Co", primary_domain="notier.hub1z.com",
                  status=TenantStatus.ACTIVE, plan_tier="nonexistent")
        db.session.add(t); db.session.commit()
    c = app.test_client()
    r = c.post("/auth/register", data={
        "full_name": "Fine", "email": "fine@notier.com",
        "phone": "", "password": "FinePass123!", "confirm": "FinePass123!",
    }, follow_redirects=True)
    with app.app_context():
        assert User.query.filter_by(email="fine@notier.com").first() is not None
