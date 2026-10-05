"""Self-serve operator sign-up: lands as a time-boxed TRIAL, no platform staff
involved to get started; login and trial features continue after the deadline."""
import os
from datetime import datetime, timedelta
from urllib.parse import urlsplit

os.environ.setdefault("FLASK_ENV", "testing")

from app import create_app
from app.extensions import db
from app.models import User, UserRole, Operator, OperatorStatus


def _app(trial_days=14):
    app = create_app({"SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
                      "WTF_CSRF_ENABLED": False,
                      "MAIL_SUPPRESS_SEND": True,
                      "STORAGE_BACKEND": "local",
                      "LOCAL_STORAGE_DIR": "./var/test-uploads",
                      "OPERATOR_TRIAL_DAYS": trial_days})
    with app.app_context():
        db.create_all()
    return app


def test_self_serve_signup_creates_trial_and_redirects_to_workspace():
    app = _app(trial_days=14)
    c = app.test_client()
    r = c.post("/auth/register/operator", data={
        "business_name": "Trial Biz", "slug": "trialbiz",
        "admin_full_name": "Tara Admin", "admin_email": "tara@trialbiz.com",
        "password": "TaraPass123!", "confirm": "TaraPass123!", "country_code": "IN",
    }, follow_redirects=False)
    assert r.status_code == 302
    assert urlsplit(r.headers["Location"]).hostname == "trialbiz.hub1z.com"
    assert r.headers["Location"].endswith("/auth/login")

    with app.app_context():
        t = Operator.query.filter_by(slug="trialbiz").first()
        assert t.status == OperatorStatus.TRIAL
        assert t.trial_ends_at is not None
        delta = t.trial_ends_at - datetime.utcnow()
        assert timedelta(days=13) < delta <= timedelta(days=14)

        admin = User.query.filter_by(email="tara@trialbiz.com") \
                          .execution_options(skip_operator_filter=True).first()
        assert admin.role == UserRole.SUPER_ADMIN
        assert admin.is_active is True  # self-serve: sets own password immediately, no invite loop
    workspace = "trialbiz.hub1z.com"
    response = c.post("/auth/login", data={"email": "tara@trialbiz.com", "password": "TaraPass123!"}, headers={"Host": workspace})
    assert response.status_code == 302
    assert c.get("/admin/", headers={"Host": workspace}).status_code == 200


def test_duplicate_slug_and_email_rejected():
    app = _app()
    with app.app_context():
        db.session.add(Operator(slug="taken", name="Taken", primary_domain="taken.hub1z.com",
                              status=OperatorStatus.ACTIVE))
        db.session.commit()

    c = app.test_client()
    r = c.post("/auth/register/operator", data={
        "business_name": "Dup", "slug": "taken",
        "admin_full_name": "X", "admin_email": "x@dup.com",
        "password": "XPass1234!", "confirm": "XPass1234!", "country_code": "IN",
    }, follow_redirects=True)
    assert b"already taken" in r.data


def test_login_continues_after_trial_expires():
    app = _app()
    with app.app_context():
        t = Operator(slug="expired", name="Expired Co", primary_domain="expired.hub1z.com",
                   status=OperatorStatus.TRIAL, trial_ends_at=datetime.utcnow() - timedelta(days=1))
        db.session.add(t); db.session.flush()
        u = User(operator_id=t.id, email="admin@expired.com", full_name="Admin",
                role=UserRole.SUPER_ADMIN, is_active=True)
        u.set_password("AdminPass123!")
        db.session.add(u); db.session.commit()

    c = app.test_client()
    r = c.post("/auth/login", data={"email": "admin@expired.com", "password": "AdminPass123!"},
              headers={"Host": "expired.hub1z.com"}, follow_redirects=True)
    assert b"trial ended" not in r.data
    assert b"Sign out" in r.data  # expiry keeps access until a plan is paid


def test_login_allowed_while_trial_still_active():
    app = _app()
    with app.app_context():
        t = Operator(slug="active-trial", name="Active Trial Co", primary_domain="activetrial.hub1z.com",
                   status=OperatorStatus.TRIAL, trial_ends_at=datetime.utcnow() + timedelta(days=5))
        db.session.add(t); db.session.flush()
        u = User(operator_id=t.id, email="admin@activetrial.com", full_name="Admin",
                role=UserRole.SUPER_ADMIN, is_active=True)
        u.set_password("AdminPass123!")
        db.session.add(u); db.session.commit()

    c = app.test_client()
    r = c.post("/auth/login", data={"email": "admin@activetrial.com", "password": "AdminPass123!"},
              headers={"Host": "activetrial.hub1z.com"}, follow_redirects=True)
    assert b"trial ended" not in r.data
    assert b"Sign out" in r.data


def test_active_operator_with_previous_trial_deadline_can_sign_in():
    """For ACTIVE operators, an old trial_ends_at in the past must not matter —
    is_trial_expired only applies while status is still TRIAL."""
    app = _app()
    with app.app_context():
        t = Operator(slug="approved", name="Approved Co", primary_domain="approved.hub1z.com",
                   status=OperatorStatus.ACTIVE, trial_ends_at=datetime.utcnow() - timedelta(days=30))
        db.session.add(t); db.session.flush()
        u = User(operator_id=t.id, email="admin@approved.com", full_name="Admin",
                role=UserRole.SUPER_ADMIN, is_active=True)
        u.set_password("AdminPass123!")
        db.session.add(u); db.session.commit()

    c = app.test_client()
    r = c.post("/auth/login", data={"email": "admin@approved.com", "password": "AdminPass123!"},
              headers={"Host": "approved.hub1z.com"}, follow_redirects=True)
    assert b"trial ended" not in r.data
    assert b"Sign out" in r.data
