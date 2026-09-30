"""Basic smoke tests. Run with: pytest -q"""
import os

os.environ.setdefault("FLASK_ENV", "testing")

from app import create_app
from app.extensions import db
from app.models import Operator, OperatorStatus


def _app():
    app = create_app({"SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
                      "WTF_CSRF_ENABLED": False,
                      "STORAGE_BACKEND": "local",
                      "LOCAL_STORAGE_DIR": "./var/test-uploads"})
    with app.app_context():
        db.create_all()
        db.session.add(Operator(slug="smoke", name="Smoke Space", primary_domain="smoke.hub1z.com",
                                status=OperatorStatus.ACTIVE))
        db.session.commit()
    return app


def test_healthz_ok():
    app = _app()
    client = app.test_client()
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json["status"] == "ok"


def test_landing_page():
    app = _app()
    client = app.test_client()
    r = client.get("/")
    assert r.status_code == 200
    assert b"CoWorkHub" in r.data or b"workspace" in r.data


def test_register_individual_and_login():
    app = _app()
    client = app.test_client()
    r = client.post("/auth/register", data={
        "full_name": "Test User",
        "email": "tu@example.com",
        "phone": "",
        "password": "Password123!",
        "confirm": "Password123!",
    }, follow_redirects=True)
    assert r.status_code == 200
    # After registration we're logged in and land on member dashboard
    assert b"Hi Test" in r.data or b"Dashboard" in r.data
