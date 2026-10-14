"""Sign-in lifetime and the password show/hide eye."""
import os
from datetime import timedelta

os.environ.setdefault("FLASK_ENV", "testing")

from app.cli import PERSONA_PASSWORD
from tests.test_release_upi_parcels_alerts import DEMO, _get, _seeded_app


def _login(app, remember):
    client = app.test_client()
    data = {"email": "owner@demospace.com", "password": PERSONA_PASSWORD}
    if remember:
        data["remember"] = "y"
    response = client.post("/auth/login", data=data, headers={"Host": DEMO})
    assert response.status_code == 302
    return client, response


def test_sign_ins_expire_by_default_and_remember_me_is_bounded():
    app, _ = _seeded_app()
    assert app.config["PERMANENT_SESSION_LIFETIME"] == timedelta(hours=12)
    assert app.config["REMEMBER_COOKIE_DURATION"] == timedelta(days=14)

    plain, response = _login(app, remember=False)
    assert not any(c.startswith("remember_token") for c in response.headers.getlist("Set-Cookie"))
    page = _get(plain, DEMO, "/admin/")
    assert page.status_code == 200
    # A permanent session carries an expiry that is pushed out on every request, so idle sign-ins end by themselves.
    assert any(c.startswith("session=") and "Expires=" in c for c in page.headers.getlist("Set-Cookie"))

    _, remembered = _login(app, remember=True)
    cookie = next(c for c in remembered.headers.getlist("Set-Cookie") if c.startswith("remember_token"))
    assert "Expires=" in cookie or "Max-Age=" in cookie            # a bounded cookie, not a session one
    if "Max-Age=" in cookie:
        assert int(cookie.split("Max-Age=")[1].split(";")[0]) == 14 * 24 * 3600


def test_every_page_with_a_password_field_loads_the_eye_script():
    app, _ = _seeded_app()
    public = app.test_client()
    for path in ("/auth/login", "/auth/forgot-password", "/auth/register/operator"):
        page = _get(public, DEMO, path).get_data(as_text=True)
        assert "js/password-toggle.js" in page, path
    login = _get(public, DEMO, "/auth/login").get_data(as_text=True)
    assert 'type="password"' in login and "Keep me signed in on this device" in login
    assert "14 days" in login and "12 hours" in login


def test_static_files_are_addressed_by_version_so_a_deploy_is_never_hidden_by_a_stale_cache():
    import re
    app, _ = _seeded_app()
    page = _get(app.test_client(), DEMO, "/auth/login").get_data(as_text=True)
    for asset in ("css/hub1z-ui.css", "js/password-toggle.js"):
        assert re.search(re.escape(asset) + r"\?v=\d+", page), asset


def test_sign_in_limits_are_set_in_the_environment_files_only():
    import pathlib
    root = pathlib.Path(__file__).resolve().parent.parent
    compose = (root / "docker-compose.yml").read_text()
    assert "SESSION_IDLE_HOURS: ${SESSION_IDLE_HOURS:-12}" in compose and "REMEMBER_ME_DAYS: ${REMEMBER_ME_DAYS:-14}" in compose
    example = (root / ".env.example").read_text()
    assert "SESSION_IDLE_HOURS=12" in example and "REMEMBER_ME_DAYS=14" in example
