"""Phase 3: 2FA, audit CSV, heatmap, PDF invoice, waitlist."""
import os
os.environ.setdefault("FLASK_ENV", "testing")

import pyotp
from datetime import datetime, date
from app import create_app
from app.extensions import db
from app.models import (
    User, UserRole, Operator, OperatorStatus, AuditLog, Invoice, InvoiceStatus,
    Location, ConferenceRoom, RoomWaitlist, WaitlistStatus,
)


def _app():
    app = create_app({"SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
                      "WTF_CSRF_ENABLED": False,
                      "MAIL_SUPPRESS_SEND": True,
                      "STORAGE_BACKEND": "local",
                      "LOCAL_STORAGE_DIR": "./var/test-uploads"})
    with app.app_context():
        db.create_all()
        t = Operator(slug="coworkhub", name="CoWorkHub",
                   primary_domain="coworkhub.io", status=OperatorStatus.TRIAL)  # trial plan includes the audit export and heatmap
        db.session.add(t); db.session.commit()
    return app


def _login(app, email="u@example.com", role=UserRole.SUPER_ADMIN, tfa=False):
    with app.app_context():
        t = Operator.query.first()
        u = User(operator_id=t.id, email=email, full_name="Ada",
                 role=role, is_active=True,
                 two_factor_enabled=tfa,
                 two_factor_secret=pyotp.random_base32() if tfa else None)
        u.set_password("pw12345678")
        db.session.add(u); db.session.commit()
        uid = u.id
        secret = u.two_factor_secret
    c = app.test_client()
    c.post("/auth/login", data={"email": email, "password": "pw12345678"})
    return c, uid, secret


def test_2fa_enable_and_login_flow():
    app = _app()
    c, uid, _ = _login(app, "twofa@example.com", tfa=False)
    r = c.get("/auth/2fa/setup")
    assert r.status_code == 200
    with app.app_context():
        u = db.session.get(User, uid)
        secret = u.two_factor_secret
    code = pyotp.TOTP(secret).now()
    r = c.post("/auth/2fa/setup", data={"code": code}, follow_redirects=False)
    assert r.status_code == 302
    with app.app_context():
        u = db.session.get(User, uid)
        assert u.two_factor_enabled is True
    # Log out and log back in — should now redirect to 2fa/login
    c.get("/auth/logout")
    r = c.post("/auth/login", data={"email": "twofa@example.com",
                                     "password": "pw12345678"},
               follow_redirects=False)
    assert r.status_code == 302
    assert "/auth/2fa/login" in r.headers.get("Location", "")
    code = pyotp.TOTP(secret).now()
    r = c.post("/auth/2fa/login", data={"code": code}, follow_redirects=False)
    assert r.status_code == 302


def test_2fa_wrong_code_denied():
    app = _app()
    c, uid, secret = _login(app, "bad@example.com", tfa=True)
    c.get("/auth/logout")
    c.post("/auth/login", data={"email": "bad@example.com",
                                  "password": "pw12345678"})
    r = c.post("/auth/2fa/login", data={"code": "000000"})
    assert r.status_code == 200
    assert b"Invalid code" in r.data


def test_audit_csv_endpoint():
    app = _app()
    with app.app_context():
        t = Operator.query.first()
        u = User(operator_id=t.id, email="sa@example.com", full_name="SA",
                 role=UserRole.SUPER_ADMIN, is_active=True)
        u.set_password("pw12345678")
        db.session.add(u); db.session.commit()
        db.session.add(AuditLog(operator_id=t.id, actor_id=u.id,
                                action="invoice.void", entity_type="invoice",
                                entity_id=1, ip_address="127.0.0.1"))
        db.session.commit()
    c = app.test_client()
    c.post("/auth/login", data={"email": "sa@example.com", "password": "pw12345678"})
    r = c.get("/admin/audit-log.csv")
    assert r.status_code == 200
    assert r.mimetype == "text/csv"
    body = r.get_data(as_text=True)
    assert "created_at" in body
    assert "invoice.void" in body


def test_invoice_pdf_returns_pdf():
    app = _app()
    with app.app_context():
        t = Operator.query.first()
        u = User(operator_id=t.id, email="a3@example.com", full_name="A",
                 role=UserRole.SUPER_ADMIN, is_active=True)
        u.set_password("pw12345678")
        db.session.add(u); db.session.flush()
        today = date.today()
        inv = Invoice(operator_id=t.id, user_id=u.id, number="INV-TEST-1",
                      status=InvoiceStatus.ISSUED, issued_at=datetime.utcnow(),
                      period_start=today, period_end=today, due_date=today,
                      subtotal=1000, tax_amount=180, total_amount=1180)
        db.session.add(inv); db.session.commit()
        inv_id = inv.id
    c = app.test_client()
    c.post("/auth/login", data={"email": "a3@example.com", "password": "pw12345678"})
    r = c.get(f"/admin/invoices/{inv_id}/pdf")
    assert r.status_code == 200
    assert r.mimetype == "application/pdf"
    assert r.data[:4] == b"%PDF"


def test_heatmap_page_renders():
    app = _app()
    c, _, _ = _login(app, "h@example.com", role=UserRole.SUPER_ADMIN)
    r = c.get("/admin/reports/heatmap")
    assert r.status_code == 200
    assert b"heatmap" in r.data.lower()


def test_waitlist_join():
    app = _app()
    with app.app_context():
        from app.models import Floor
        t = Operator.query.first()
        u = User(operator_id=t.id, email="wl@example.com", full_name="W",
                 role=UserRole.INDIVIDUAL, is_active=True)
        u.set_password("pw12345678")
        loc = Location(operator_id=t.id, name="L", code="LWL",
                       address_line1="a", city="Bengaluru", country="IN",
                       postal_code="1", timezone="Asia/Kolkata")
        db.session.add_all([u, loc]); db.session.flush()
        fl = Floor(operator_id=t.id, location_id=loc.id, level=1, name="Ground")
        db.session.add(fl); db.session.flush()
        room = ConferenceRoom(operator_id=t.id, location_id=loc.id, floor_id=fl.id,
                              code="R1", name="Room 1", capacity=6)
        db.session.add(room); db.session.commit()
        room_id = room.id
    c = app.test_client()
    c.post("/auth/login", data={"email": "wl@example.com", "password": "pw12345678"})
    r = c.post(f"/book/rooms/{room_id}/waitlist",
               data={"start": "2026-10-01T10:00", "end": "2026-10-01T11:00"},
               follow_redirects=False)
    assert r.status_code == 302
    with app.app_context():
        entries = RoomWaitlist.query.execution_options(skip_operator_filter=True).all()
        assert len(entries) == 1
        assert entries[0].status == WaitlistStatus.WAITING
