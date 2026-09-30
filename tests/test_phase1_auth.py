"""Phase 1: password reset, change password, operator picker."""
import os
os.environ.setdefault("FLASK_ENV", "testing")

from app import create_app
from app.extensions import db
from app.models import User, UserRole, Operator, OperatorStatus
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
        db.session.add(t)
        db.session.commit()
    return app


def _make_user(app, email="user@example.com", password="OldPass123!"):
    with app.app_context():
        t = Operator.query.filter_by(slug="coworkhub").first()
        u = User(operator_id=t.id, email=email, full_name="User One",
                 role=UserRole.INDIVIDUAL, is_active=True)
        u.set_password(password)
        db.session.add(u); db.session.commit()
        return u.id


def test_forgot_password_page_renders():
    app = _app()
    r = app.test_client().get("/auth/forgot-password")
    assert r.status_code == 200
    assert b"Forgot" in r.data


def test_forgot_password_generic_response_even_for_unknown_email():
    app = _app()
    r = app.test_client().post("/auth/forgot-password",
                                data={"email": "nobody@example.com"},
                                follow_redirects=False)
    assert r.status_code == 302


def test_reset_token_roundtrip_and_password_change():
    app = _app()
    uid = _make_user(app, "reset@example.com", "OldPass123!")
    with app.app_context():
        token = mail_service.make_token(uid, "password-reset")
        assert mail_service.read_token(token, "password-reset", 60) == uid
        assert mail_service.read_token(token, "wrong-purpose", 60) is None

    c = app.test_client()
    r = c.get(f"/auth/reset-password/{token}")
    assert r.status_code == 200
    r = c.post(f"/auth/reset-password/{token}",
               data={"password": "NewPass456!", "confirm": "NewPass456!"},
               follow_redirects=False)
    assert r.status_code == 302

    with app.app_context():
        u = db.session.get(User, uid)
        assert u.check_password("NewPass456!")


def test_reset_with_invalid_token_redirects():
    app = _app()
    r = app.test_client().get("/auth/reset-password/tampered.garbage.token",
                              follow_redirects=False)
    assert r.status_code == 302
    assert "/auth/forgot-password" in r.headers.get("Location", "")


def test_change_password_requires_login():
    app = _app()
    r = app.test_client().get("/auth/change-password", follow_redirects=False)
    assert r.status_code == 302
    assert "/auth/login" in r.headers.get("Location", "")


def test_change_password_flow():
    app = _app()
    _make_user(app, "chg@example.com", "OldPass123!")
    c = app.test_client()
    r = c.post("/auth/login", data={"email": "chg@example.com", "password": "OldPass123!"})
    assert r.status_code == 302
    r = c.post("/auth/change-password", data={
        "current_password": "OldPass123!",
        "password": "NewPass456!",
        "confirm": "NewPass456!",
    }, follow_redirects=False)
    assert r.status_code == 302
    with app.app_context():
        u = User.query.filter_by(email="chg@example.com") \
                       .execution_options(skip_operator_filter=True).first()
        assert u.check_password("NewPass456!")


def test_change_password_wrong_current():
    app = _app()
    _make_user(app, "wrong@example.com", "OldPass123!")
    c = app.test_client()
    c.post("/auth/login", data={"email": "wrong@example.com", "password": "OldPass123!"})
    r = c.post("/auth/change-password", data={
        "current_password": "WRONG",
        "password": "NewPass456!",
        "confirm": "NewPass456!",
    })
    assert r.status_code == 200
    assert b"Current password is incorrect" in r.data


def test_pick_workspace_redirects_to_operator_domain():
    app = _app()
    with app.app_context():
        db.session.add(Operator(slug="adyar", name="Adyar Space",
                              primary_domain="adyar.coworkhub.io",
                              status=OperatorStatus.ACTIVE))
        db.session.commit()
    r = app.test_client().post("/auth/pick-workspace",
                                data={"workspace": "adyar"},
                                follow_redirects=False)
    assert r.status_code == 302
    assert "adyar.coworkhub.io" in r.headers.get("Location", "")


def test_pick_workspace_unknown_slug():
    app = _app()
    r = app.test_client().post("/auth/pick-workspace",
                                data={"workspace": "does-not-exist"})
    assert r.status_code == 200
    assert b"No workspace found" in r.data
