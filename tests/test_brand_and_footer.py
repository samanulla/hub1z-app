"""The Hub1z logo belongs to the Platform only; operator sites keep their own brand and everyone
gets a small "Powered by" H mark that links to the Platform home page."""
import os

os.environ.setdefault("FLASK_ENV", "testing")

from app.cli import PERSONA_PASSWORD
from tests.test_role_paths import APEX, DEMO, OWNER_PASSWORD, _login, _seeded_app

POWERED = b'aria-label="Powered by Hub1z"'


def _get(client, host, path):
    r = client.get(path, headers={"Host": host})
    assert r.status_code == 200, (host, path, r.status_code)
    return r.data


def test_platform_sign_in_page_has_the_logo_and_the_powered_by_mark():
    app, _ = _seeded_app()
    html = _get(app.test_client(), APEX, "/auth/login")
    assert b"img/brand/hub1z-logo.svg" in html
    assert html.count(POWERED) == 1
    assert b'href="http://localhost"' in html  # the Platform home page


def test_operator_sign_in_page_keeps_its_own_name_and_only_adds_the_mark():
    app, _ = _seeded_app()
    html = _get(app.test_client(), DEMO, "/auth/login")
    assert b"img/brand/hub1z-logo.svg" not in html
    assert b"Demo Space" in html
    assert html.count(POWERED) == 1


def test_signed_in_sidebar_logo_is_platform_only_and_footer_mark_is_for_everyone():
    app, _ = _seeded_app()
    platform = app.test_client()
    _login(platform, APEX, "admin@hub1z.com", OWNER_PASSWORD)
    html = _get(platform, APEX, "/platform/")
    assert b"img/brand/hub1z-logo-light.svg" in html and html.count(POWERED) == 1

    operator = app.test_client()
    _login(operator, DEMO, "owner@demospace.com", PERSONA_PASSWORD)
    html = _get(operator, DEMO, "/admin/")
    assert b"img/brand/hub1z-logo-light.svg" not in html
    assert b'<span class="h-brand-mark">D</span>' in html  # the operator's own initial, not the Hub1z H
    assert html.count(POWERED) == 1


def test_operator_public_pages_show_the_mark_once_and_not_the_platform_logo():
    app, _ = _seeded_app()
    client = app.test_client()
    for path in ("/", "/spaces", "/membership", "/availability"):
        html = _get(client, DEMO, path)
        assert html.count(POWERED) == 1, path
        assert b"img/brand/hub1z-logo" not in html, path


def test_platform_site_uses_the_new_design_and_no_powered_by_strip():
    app, _ = _seeded_app()
    client = app.test_client()
    for path in ("/", "/features", "/features/billing", "/pricing", "/legal", "/terms", "/privacy", "/cookies"):
        html = _get(client, APEX, path)
        assert b"hub1z-site.css" in html, path
        assert b"img/brand/hub1z-logo" in html and b"-light.svg" in html, path
        assert POWERED not in html, path
        assert b"$" not in html and b"USD" not in html, path


def test_platform_landing_shows_the_operator_upgrades():
    app, _ = _seeded_app()
    html = _get(app.test_client(), APEX, "/").decode()
    for phrase in ("Run your coworking", "Meeting-room credits", "GST billing", "Agreements", "Start free trial"):
        assert phrase in html, phrase


def test_favicons_and_brand_files_are_served():
    app, _ = _seeded_app()
    client = app.test_client()
    html = _get(client, APEX, "/auth/login")
    assert b'rel="icon"' in html and b"img/brand/hub1z-icon.svg" in html
    for path in ("hub1z-icon.svg", "hub1z-icon-light.svg", "hub1z-logo.svg", "hub1z-logo-light.svg",
                 "hub1z-logo-tagline.svg", "hub1z-logo-stacked.svg", "favicon-32.png", "favicon.ico",
                 "apple-touch-icon.png", "png/hub1z-logo.png", "png/hub1z-logo-stacked-light-small.png"):
        assert client.get(f"/static/img/brand/{path}").status_code == 200, path
