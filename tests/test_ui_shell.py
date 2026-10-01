"""The shared look: one typeface, one left menu per role, rupees only, and the formatting helpers."""
import os

os.environ.setdefault("FLASK_ENV", "testing")

from decimal import Decimal

from app import create_app
from app.extensions import db
from app.services.formatting import format_inr, format_inr_compact, initials
from tests.test_role_paths import APEX, DEMO, OWNER_PASSWORD, _login, _seeded_app
from app.cli import PERSONA_PASSWORD


def _page(client, host, path):
    r = client.get(path, headers={"Host": host})
    assert r.status_code == 200, (path, r.status_code)
    return r.data


def test_signed_out_pages_use_the_new_styles_and_a_single_typeface():
    app, _ = _seeded_app()
    html = _page(app.test_client(), DEMO, "/auth/login")
    assert b"hub1z-ui.css" in html and b"hub1z-bootstrap.css" in html
    assert b"family=Inter:" in html and b"Inter+Tight" not in html and b"Cormorant" not in html
    assert b"h-public" in html and b'<aside class="h-side"' not in html


def test_each_role_gets_its_own_left_menu():
    app, _ = _seeded_app()
    cases = [
        (APEX, "admin@hub1z.com", OWNER_PASSWORD, "/platform/", [b"Operator billing", b"Pricing tiers"], [b"Locations &amp; seats"]),
        (DEMO, "owner@demospace.com", PERSONA_PASSWORD, "/admin/", [b"Locations &amp; seats", b"Billing settings", b"Reception"], [b"Operator billing", b"My space"]),
        (DEMO, "admin@acmeco.com", PERSONA_PASSWORD, "/company/", [b"Plans &amp; subscriptions", b"Check-in QR", b">Book<", b">Community<"], [b"Pricing plans", b"Reception", b"Book &amp; community"]),
        (DEMO, "employee@acmeco.com", PERSONA_PASSWORD, "/me/", [b"My space", b"Announcements"], [b"Pricing plans", b"Billing &amp; finance"]),
        (DEMO, "individual@demospace.com", PERSONA_PASSWORD, "/me/", [b"My space"], [b"Pricing plans"]),
    ]
    for host, email, password, path, present, absent in cases:
        client = app.test_client()
        _login(client, host, email, password)
        html = _page(client, host, path)
        assert b'<aside class="h-side"' in html, email
        for text in present:
            assert text in html, (email, text)
        for text in absent:
            assert text not in html, (email, text)


def test_no_dollar_signs_anywhere_people_look():
    app, _ = _seeded_app()
    anon = app.test_client()
    pages = [(anon, APEX, "/pricing"), (anon, DEMO, "/auth/login")]
    owner = app.test_client()
    _login(owner, DEMO, "owner@demospace.com", PERSONA_PASSWORD)
    pages += [(owner, DEMO, p) for p in ("/admin/", "/admin/invoices", "/admin/billing/settings", "/admin/companies",
                                         "/admin/plans", "/admin/reports")]
    for client, host, path in pages:
        html = _page(client, host, path)
        assert b"$" not in html, path
        assert b"USD" not in html, path


def test_pricing_is_rupees_even_if_another_currency_is_requested():
    app, _ = _seeded_app()
    html = _page(app.test_client(), APEX, "/pricing?currency=USD")
    assert b"USD" not in html and b"$" not in html


def test_styles_are_served():
    app, _ = _seeded_app()
    client = app.test_client()
    css = client.get("/static/css/hub1z-ui.css")
    assert css.status_code == 200 and b"--h-brand" in css.data
    assert client.get("/static/css/hub1z-bootstrap.css").status_code == 200
    assert client.get("/static/js/hub1z-ui.js").status_code == 200


def test_rupee_formatting():
    assert format_inr(125000) == "₹1,25,000"
    assert format_inr(Decimal("75000.60")) == "₹75,001"
    assert format_inr(-4200) == "-₹4,200"
    assert format_inr_compact(1865000) == "₹18.65L"
    assert format_inr_compact(17355000) == "₹1.74Cr"
    assert format_inr_compact(75000) == "₹75,000"
    assert format_inr_compact(2000000) == "₹20L"


def test_initials():
    assert initials("Priya Nair") == "PN" and initials("Acme") == "A" and initials("dr. anita desai") == "DA"
    assert initials("") == "?" and initials(None) == "?"


def test_design_preview_is_development_only():
    plain = create_app({"SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:", "STORAGE_BACKEND": "local",
                        "LOCAL_STORAGE_DIR": "./var/test-uploads"})
    with plain.app_context():
        db.create_all()
    assert plain.test_client().get("/ui-preview/").status_code == 404
    dev = create_app({"SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:", "STORAGE_BACKEND": "local",
                      "LOCAL_STORAGE_DIR": "./var/test-uploads", "DEBUG": True})
    with dev.app_context():
        db.create_all()
    client = dev.test_client()
    for path in ("platform-dashboard", "companies", "leads?persona=operator", "leads?persona=platform"):
        assert client.get(f"/ui-preview/{path}").status_code == 200, path
