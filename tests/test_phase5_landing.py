"""Phase 5: modernized landing page renders with 3-role sign-in and features."""
import os
os.environ.setdefault("FLASK_ENV", "testing")

from app import create_app
from app.extensions import db
from app.models import Operator, OperatorStatus


def _app():
    app = create_app({"SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
                      "WTF_CSRF_ENABLED": False,
                      "MAIL_SUPPRESS_SEND": True,
                      "STORAGE_BACKEND": "local",
                      "LOCAL_STORAGE_DIR": "./var/test-uploads"})
    with app.app_context():
        db.create_all()
        db.session.add(Operator(slug="coworkhub", name="CoWorkHub",
                              primary_domain="coworkhub.io",
                              status=OperatorStatus.ACTIVE))
        db.session.commit()
    return app


def test_landing_shows_three_role_cards():
    r = _app().test_client().get("/")
    assert r.status_code == 200
    body = r.get_data(as_text=True).lower()
    assert "individual" in body
    assert "company" in body
    assert "operator" in body


def test_landing_shows_feature_highlights():
    r = _app().test_client().get("/")
    body = r.get_data(as_text=True).lower()
    for phrase in ["instant availability", "qr check-in", "india-first",
                    "member directory", "enterprise-grade", "community"]:
        assert phrase in body, f"landing page missing highlight: {phrase!r}"


def test_landing_links_all_three_auth_paths():
    r = _app().test_client().get("/")
    body = r.get_data(as_text=True)
    assert "/auth/login" in body
    assert "/auth/register" in body
    assert "/auth/register/company" in body
    assert "/auth/pick-workspace" in body
