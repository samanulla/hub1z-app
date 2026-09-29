"""Phase 4: community features MVP."""
import os
os.environ.setdefault("FLASK_ENV", "testing")

from datetime import date, datetime, timedelta
from app import create_app
from app.extensions import db
from app.models import (
    User, UserRole, Operator, OperatorStatus, Location,
    GuestPass, Visitor, VisitorStatus,
    Announcement, SupportTicket, TicketStatus,
    Locker, LockerStatus, Referral, PrintingLedger, CommunityProfile,
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
                   primary_domain="coworkhub.io", status=OperatorStatus.ACTIVE)
        db.session.add(t); db.session.commit()
    return app


def _seed_admin_and_loc(app):
    with app.app_context():
        t = Operator.query.first()
        admin = User(operator_id=t.id, email="a@coworkhub.io", full_name="Admin",
                     role=UserRole.SUPER_ADMIN, is_active=True)
        admin.set_password("pw12345678")
        loc = Location(operator_id=t.id, name="Main", code="MAIN",
                       address_line1="a", city="Bengaluru", country="IN",
                       postal_code="1", timezone="Asia/Kolkata")
        db.session.add_all([admin, loc]); db.session.commit()
        return t.id, admin.id, loc.id


def test_guest_pass_create():
    app = _app()
    tid, aid, lid = _seed_admin_and_loc(app)
    c = app.test_client()
    c.post("/auth/login", data={"email": "a@coworkhub.io", "password": "pw12345678"})
    r = c.post("/hub/guest-passes", data={
        "guest_name": "John Doe", "guest_email": "john@example.com",
        "location_id": lid, "visit_date": date.today().isoformat(),
    }, follow_redirects=False)
    assert r.status_code == 302
    with app.app_context():
        gp = GuestPass.query.execution_options(skip_operator_filter=True).first()
        assert gp.guest_name == "John Doe"
        assert gp.code


def test_visitor_check_in_out():
    app = _app()
    tid, aid, lid = _seed_admin_and_loc(app)
    with app.app_context():
        v = Visitor(operator_id=tid, host_user_id=aid, location_id=lid,
                    name="Alice", expected_at=datetime.utcnow(),
                    status=VisitorStatus.PENDING)
        db.session.add(v); db.session.commit()
        vid = v.id
    c = app.test_client()
    c.post("/auth/login", data={"email": "a@coworkhub.io", "password": "pw12345678"})
    r = c.post(f"/hub/visitors/{vid}/check-in", follow_redirects=False)
    assert r.status_code == 302
    with app.app_context():
        v = db.session.get(Visitor, vid)
        assert v.status == VisitorStatus.CHECKED_IN
    r = c.post(f"/hub/visitors/{vid}/check-out", follow_redirects=False)
    with app.app_context():
        v = db.session.get(Visitor, vid)
        assert v.status == VisitorStatus.CHECKED_OUT


def test_announcement_new():
    app = _app()
    tid, aid, lid = _seed_admin_and_loc(app)
    c = app.test_client()
    c.post("/auth/login", data={"email": "a@coworkhub.io", "password": "pw12345678"})
    r = c.post("/hub/announcements/new", data={
        "title": "Wi-Fi upgrade tonight",
        "body": "Between 10pm and midnight.",
    }, follow_redirects=False)
    assert r.status_code == 302
    with app.app_context():
        a = Announcement.query.execution_options(skip_operator_filter=True).first()
        assert a.title == "Wi-Fi upgrade tonight"


def test_support_ticket_and_resolve():
    app = _app()
    tid, aid, lid = _seed_admin_and_loc(app)
    c = app.test_client()
    c.post("/auth/login", data={"email": "a@coworkhub.io", "password": "pw12345678"})
    r = c.post("/hub/tickets", data={
        "subject": "AC not cold", "body": "Room 4B",
        "priority": "high", "location_id": lid,
    }, follow_redirects=False)
    assert r.status_code == 302
    with app.app_context():
        t = SupportTicket.query.execution_options(skip_operator_filter=True).first()
        tid_ = t.id
    r = c.post(f"/hub/tickets/{tid_}/resolve", follow_redirects=False)
    with app.app_context():
        t = db.session.get(SupportTicket, tid_)
        assert t.status == TicketStatus.RESOLVED


def test_locker_assign_release():
    app = _app()
    tid, aid, lid = _seed_admin_and_loc(app)
    with app.app_context():
        lk = Locker(operator_id=tid, location_id=lid, code="L001",
                    monthly_rate=500, status=LockerStatus.AVAILABLE)
        db.session.add(lk); db.session.commit()
        lk_id = lk.id
    c = app.test_client()
    c.post("/auth/login", data={"email": "a@coworkhub.io", "password": "pw12345678"})
    r = c.post(f"/hub/lockers/{lk_id}/assign", data={"user_id": aid},
               follow_redirects=False)
    assert r.status_code == 302
    with app.app_context():
        lk = db.session.get(Locker, lk_id)
        assert lk.status == LockerStatus.ASSIGNED
    c.post(f"/hub/lockers/{lk_id}/release", follow_redirects=False)
    with app.app_context():
        lk = db.session.get(Locker, lk_id)
        assert lk.status == LockerStatus.AVAILABLE


def test_referral_create():
    app = _app()
    tid, aid, lid = _seed_admin_and_loc(app)
    c = app.test_client()
    c.post("/auth/login", data={"email": "a@coworkhub.io", "password": "pw12345678"})
    r = c.post("/hub/referrals", data={
        "referred_email": "friend@example.com", "reward_credits": 10,
    }, follow_redirects=False)
    assert r.status_code == 302
    with app.app_context():
        r0 = Referral.query.execution_options(skip_operator_filter=True).first()
        assert r0.referred_email == "friend@example.com"
        assert r0.code and r0.reward_credits == 10
