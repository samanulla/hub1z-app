"""Self-serve tenant sign-up: lands as a time-boxed TRIAL, no platform staff
involved to get started; login is blocked once the trial deadline passes."""
import os
from datetime import datetime, timedelta

os.environ.setdefault("FLASK_ENV", "testing")

from app import create_app
from app.extensions import db
from app.models import User, UserRole, Tenant, TenantStatus


def _app(trial_days=14):
    app = create_app({"SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
                      "WTF_CSRF_ENABLED": False,
                      "MAIL_SUPPRESS_SEND": True,
                      "STORAGE_BACKEND": "local",
                      "LOCAL_STORAGE_DIR": "./var/test-uploads",
                      "TENANT_TRIAL_DAYS": trial_days})
    with app.app_context():
        db.create_all()
    return app


def test_self_serve_signup_creates_trial_tenant_and_logs_in():
    app = _app(trial_days=14)
    c = app.test_client()
    r = c.post("/auth/register/tenant", data={
        "business_name": "Trial Biz", "slug": "trialbiz",
        "admin_full_name": "Tara Admin", "admin_email": "tara@trialbiz.com",
        "password": "TaraPass123!", "confirm": "TaraPass123!",
    }, follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["Location"].endswith("/admin/")

    with app.app_context():
        t = Tenant.query.filter_by(slug="trialbiz").first()
        assert t.status == TenantStatus.TRIAL
        assert t.trial_ends_at is not None
        delta = t.trial_ends_at - datetime.utcnow()
        assert timedelta(days=13) < delta <= timedelta(days=14)

        admin = User.query.filter_by(email="tara@trialbiz.com") \
                          .execution_options(skip_tenant_filter=True).first()
        assert admin.role == UserRole.SUPER_ADMIN
        assert admin.is_active is True  # self-serve: sets own password immediately, no invite loop


def test_duplicate_slug_and_email_rejected():
    app = _app()
    with app.app_context():
        db.session.add(Tenant(slug="taken", name="Taken", primary_domain="taken.hub1z.com",
                              status=TenantStatus.ACTIVE))
        db.session.commit()

    c = app.test_client()
    r = c.post("/auth/register/tenant", data={
        "business_name": "Dup", "slug": "taken",
        "admin_full_name": "X", "admin_email": "x@dup.com",
        "password": "XPass1234!", "confirm": "XPass1234!",
    }, follow_redirects=True)
    assert b"already taken" in r.data


def test_login_blocked_once_trial_expired():
    app = _app()
    with app.app_context():
        t = Tenant(slug="expired", name="Expired Co", primary_domain="expired.hub1z.com",
                   status=TenantStatus.TRIAL, trial_ends_at=datetime.utcnow() - timedelta(days=1))
        db.session.add(t); db.session.flush()
        u = User(tenant_id=t.id, email="admin@expired.com", full_name="Admin",
                role=UserRole.SUPER_ADMIN, is_active=True)
        u.set_password("AdminPass123!")
        db.session.add(u); db.session.commit()

    c = app.test_client()
    r = c.post("/auth/login", data={"email": "admin@expired.com", "password": "AdminPass123!"},
              follow_redirects=True)
    assert b"trial ended" in r.data
    assert b"Sign out" not in r.data  # never got logged in


def test_login_allowed_while_trial_still_active():
    app = _app()
    with app.app_context():
        t = Tenant(slug="active-trial", name="Active Trial Co", primary_domain="activetrial.hub1z.com",
                   status=TenantStatus.TRIAL, trial_ends_at=datetime.utcnow() + timedelta(days=5))
        db.session.add(t); db.session.flush()
        u = User(tenant_id=t.id, email="admin@activetrial.com", full_name="Admin",
                role=UserRole.SUPER_ADMIN, is_active=True)
        u.set_password("AdminPass123!")
        db.session.add(u); db.session.commit()

    c = app.test_client()
    r = c.post("/auth/login", data={"email": "admin@activetrial.com", "password": "AdminPass123!"},
              follow_redirects=True)
    assert b"trial ended" not in r.data
    assert b"Sign out" in r.data


def test_approving_a_trial_tenant_does_not_retroactively_block_login():
    """Once approved (ACTIVE), an old trial_ends_at in the past must not matter —
    is_trial_expired only applies while status is still TRIAL."""
    app = _app()
    with app.app_context():
        t = Tenant(slug="approved", name="Approved Co", primary_domain="approved.hub1z.com",
                   status=TenantStatus.ACTIVE, trial_ends_at=datetime.utcnow() - timedelta(days=30))
        db.session.add(t); db.session.flush()
        u = User(tenant_id=t.id, email="admin@approved.com", full_name="Admin",
                role=UserRole.SUPER_ADMIN, is_active=True)
        u.set_password("AdminPass123!")
        db.session.add(u); db.session.commit()

    c = app.test_client()
    r = c.post("/auth/login", data={"email": "admin@approved.com", "password": "AdminPass123!"},
              follow_redirects=True)
    assert b"trial ended" not in r.data
    assert b"Sign out" in r.data
