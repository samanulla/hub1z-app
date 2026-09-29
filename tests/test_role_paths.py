"""Every role has its own sign-in path, and only that path: platform owner (apex),
operator owner, company admin, employee (added by a company admin) and individual
(added by the operator) on the operator's host. Seeded by `flask seed-personas`."""
import os

os.environ.setdefault("FLASK_ENV", "testing")

from app import create_app
from app.cli import PERSONA_PASSWORD, seed_personas_cmd
from app.extensions import db

APEX, DEMO, OTHER = "localhost", "demo.localhost", "other.localhost"
OWNER_PASSWORD = "ChangeMe123!"

# (label, host, email, password, landing path, page that must load)
PERSONAS = [
    ("platform owner", APEX, "admin@hub1z.com", OWNER_PASSWORD, "/platform/", "/platform/"),
    ("operator owner", DEMO, "owner@demospace.com", PERSONA_PASSWORD, "/admin/", "/admin/"),
    ("company admin", DEMO, "admin@acmeco.com", PERSONA_PASSWORD, "/company/", "/company/"),
    ("employee", DEMO, "employee@acmeco.com", PERSONA_PASSWORD, "/me/", "/me/"),
    ("individual", DEMO, "individual@demospace.com", PERSONA_PASSWORD, "/me/", "/me/"),
]


def _seeded_app():
    app = create_app({"SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:", "WTF_CSRF_ENABLED": False,
                      "MAIL_SUPPRESS_SEND": True, "STORAGE_BACKEND": "local",
                      "LOCAL_STORAGE_DIR": "./var/test-uploads", "PLATFORM_BASE_DOMAIN": "localhost",
                      "RATELIMIT_ENABLED": False})
    with app.app_context():
        db.create_all()
    result = app.test_cli_runner().invoke(seed_personas_cmd)
    assert result.exit_code == 0, result.output
    return app, result.output


def _login(client, host, email, password):
    return client.post("/auth/login", data={"email": email, "password": password}, headers={"Host": host})


def test_seeder_lists_every_persona_with_its_own_address():
    _, out = _seeded_app()
    for _, host, email, _, _, _ in PERSONAS:
        assert email in out and f"http://{host}:8000/auth/login" in out


def test_each_persona_lands_on_its_own_area():
    for label, host, email, password, landing, page in PERSONAS:
        app, _ = _seeded_app()
        c = app.test_client()
        assert _login(c, host, email, password).status_code == 302, label
        r = c.get("/auth/post-login", headers={"Host": host})
        assert r.headers["Location"].endswith(landing), f"{label} -> {r.headers['Location']}"
        assert c.get(page, headers={"Host": host}).status_code == 200, label


def test_personas_cannot_sign_in_on_the_wrong_host():
    app, _ = _seeded_app()
    wrong = [
        ("admin@hub1z.com", OWNER_PASSWORD, DEMO),       # platform owner is apex-only
        ("owner@demospace.com", PERSONA_PASSWORD, APEX),  # operator users never sign in on the apex
        ("owner@demospace.com", PERSONA_PASSWORD, OTHER),  # nor on another operator's host
        ("employee@acmeco.com", PERSONA_PASSWORD, OTHER),
    ]
    for email, password, host in wrong:
        c = app.test_client()
        r = _login(c, host, email, password)
        assert r.status_code == 200 and b"Invalid email or password" in r.data, (email, host)
        assert c.get("/auth/post-login", headers={"Host": host}).status_code == 302  # bounced to sign-in


def test_roles_stay_inside_their_own_area():
    app, _ = _seeded_app()
    forbidden = [
        ("employee@acmeco.com", "/admin/"), ("employee@acmeco.com", "/company/"),
        ("individual@demospace.com", "/admin/"), ("individual@demospace.com", "/company/"),
        ("admin@acmeco.com", "/admin/"),
    ]
    for email, path in forbidden:
        c = app.test_client()
        _login(c, DEMO, email, PERSONA_PASSWORD)
        assert c.get(path, headers={"Host": DEMO}).status_code == 403, (email, path)


def test_demo_operator_never_sees_the_other_operators_data():
    app, _ = _seeded_app()
    c = app.test_client()
    _login(c, DEMO, "owner@demospace.com", PERSONA_PASSWORD)
    page = c.get("/admin/companies", headers={"Host": DEMO})
    assert b"Acme Co" in page.data
    assert b"Other Co" not in page.data and b"Other Space" not in page.data
