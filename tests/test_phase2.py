"""Phase 2 tests: employee invitations, day-pass QR, operator-form auto-fill."""
import os
os.environ.setdefault("FLASK_ENV", "testing")

from datetime import date, datetime
from app import create_app
from app.extensions import db
from app.models import (
    User, UserRole, Company, CompanyStatus,
    Operator, OperatorStatus, Location, DayPass, DayPassStatus,
)
from app.services import mail_service


def _app():
    app = create_app({"SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
                      "WTF_CSRF_ENABLED": False,
                      "MAIL_SUPPRESS_SEND": True,
                      "STORAGE_BACKEND": "local",
                      "LOCAL_STORAGE_DIR": "./var/test-uploads"})
    with app.app_context():
        db.create_all()
        t = Operator(slug="coworkhub", name="CoWorkHub",
                   primary_domain="coworkhub.io", status=OperatorStatus.ACTIVE)
        db.session.add(t); db.session.commit()
    return app


def _seed_company_admin(app):
    with app.app_context():
        t = Operator.query.first()
        c = Company(operator_id=t.id, name="Acme", billing_email="b@acme.example",
                    status=CompanyStatus.ACTIVE, max_employees=10)
        db.session.add(c); db.session.flush()
        u = User(operator_id=t.id, email="admin@acme.example",
                 full_name="Ada", role=UserRole.COMPANY_ADMIN,
                 company_id=c.id, is_active=True)
        u.set_password("pw12345678")
        db.session.add(u); db.session.commit()
        return c.id, u.id


def test_employee_invite_creates_inactive_user_and_emails_token():
    app = _app()
    cid, uid = _seed_company_admin(app)
    c = app.test_client()
    c.post("/auth/login", data={"email": "admin@acme.example", "password": "pw12345678"})
    r = c.post("/company/employees/new", data={
        "full_name": "New Hire", "email": "hire@acme.example", "phone": "",
    }, follow_redirects=False)
    assert r.status_code == 302
    with app.app_context():
        u = User.query.filter_by(email="hire@acme.example") \
                       .execution_options(skip_operator_filter=True).first()
        assert u is not None
        assert u.is_active is False


def test_accept_invite_activates_and_logs_in():
    app = _app()
    _seed_company_admin(app)
    with app.app_context():
        t = Operator.query.first()
        c = Company.query.first()
        emp = User(operator_id=t.id, email="pending@acme.example",
                   full_name="Pending", role=UserRole.EMPLOYEE,
                   company_id=c.id, is_active=False)
        emp.set_password("placeholder1234")
        db.session.add(emp); db.session.commit()
        token = mail_service.make_token(emp.id, "employee-invite")
        emp_id = emp.id

    client = app.test_client()
    r = client.get(f"/company/invite/{token}")
    assert r.status_code == 200
    r = client.post(f"/company/invite/{token}",
                    data={"password": "NewPass456!", "confirm": "NewPass456!"},
                    follow_redirects=False)
    assert r.status_code == 302
    with app.app_context():
        u = db.session.get(User, emp_id)
        assert u.is_active is True
        assert u.check_password("NewPass456!")


def test_accept_invite_bad_token():
    app = _app()
    r = app.test_client().get("/company/invite/garbage.token.here",
                              follow_redirects=False)
    assert r.status_code == 302
    assert "/auth/login" in r.headers.get("Location", "")


def test_day_pass_qr_endpoint_returns_png():
    app = _app()
    with app.app_context():
        t = Operator.query.first()
        u = User(operator_id=t.id, email="alex@example.com", full_name="Alex",
                 role=UserRole.INDIVIDUAL, is_active=True)
        u.set_password("pw12345678")
        db.session.add(u)
        loc = Location(operator_id=t.id, name="Loc 1", code="L1",
                       address_line1="a", city="Bengaluru", country="IN",
                       postal_code="1", timezone="Asia/Kolkata")
        db.session.add(loc); db.session.commit()
        dp = DayPass(operator_id=t.id, user_id=u.id, location_id=loc.id,
                     pass_date=date.today(), code=DayPass.new_code(),
                     status=DayPassStatus.ISSUED)
        db.session.add(dp); db.session.commit()
        pid = dp.id

    c = app.test_client()
    c.post("/auth/login", data={"email": "alex@example.com", "password": "pw12345678"})
    r = c.get(f"/me/day-passes/{pid}/qr.png")
    assert r.status_code == 200
    assert r.mimetype == "image/png"
    assert r.data[:8] == b"\x89PNG\r\n\x1a\n"


def test_reception_check_in_changes_status():
    app = _app()
    with app.app_context():
        t = Operator.query.first()
        admin = User(operator_id=t.id, email="a@coworkhub.io", full_name="Admin",
                     role=UserRole.SUPER_ADMIN, is_active=True)
        admin.set_password("pw12345678")
        u = User(operator_id=t.id, email="g@example.com", full_name="Guest",
                 role=UserRole.INDIVIDUAL, is_active=True)
        u.set_password("pw12345678")
        loc = Location(operator_id=t.id, name="L", code="LC",
                       address_line1="a", city="Bengaluru", country="IN",
                       postal_code="1", timezone="Asia/Kolkata")
        db.session.add_all([admin, u, loc]); db.session.commit()
        dp = DayPass(operator_id=t.id, user_id=u.id, location_id=loc.id,
                     pass_date=date.today(), code="ABC123",
                     status=DayPassStatus.ISSUED)
        db.session.add(dp); db.session.commit()

    c = app.test_client()
    c.post("/auth/login", data={"email": "a@coworkhub.io", "password": "pw12345678"})
    r = c.post("/admin/reception", data={"code": "ABC123"})
    assert r.status_code == 200
    with app.app_context():
        dp = DayPass.query.filter_by(code="ABC123").first()
        assert dp.status == DayPassStatus.CHECKED_IN
        assert dp.checked_in_at is not None


def test_reception_rejects_unknown_code():
    app = _app()
    with app.app_context():
        t = Operator.query.first()
        admin = User(operator_id=t.id, email="a2@coworkhub.io", full_name="A",
                     role=UserRole.SUPER_ADMIN, is_active=True)
        admin.set_password("pw12345678")
        db.session.add(admin); db.session.commit()
    c = app.test_client()
    c.post("/auth/login", data={"email": "a2@coworkhub.io", "password": "pw12345678"})
    r = c.post("/admin/reception", data={"code": "NOPE"})
    assert r.status_code == 200
    assert b"Unknown code" in r.data
