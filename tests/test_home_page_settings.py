"""Operator home page: content set under Settings > Home page, shown on the public site in the portal's palette."""
import os

os.environ.setdefault("FLASK_ENV", "testing")

from app.extensions import db
from app.models import Operator
from tests.test_release_upi_parcels_alerts import DEMO, _client, _get, _post, _seeded_app


def _saved(app):
    with app.app_context():
        operator = Operator.query.filter_by(primary_domain=DEMO).one()
        return dict((operator.profile_details or {}).get("site") or {})


def test_home_page_tab_sits_under_settings_for_the_owner():
    app, _ = _seeded_app()
    owner = _client(app, DEMO, "owner@demospace.com")
    page = _get(owner, DEMO, "/admin/settings/home-page").get_data(as_text=True)
    tabs = page.split('aria-label="Section navigation"', 1)[1].split("</nav>", 1)[0]
    labels = [">Profile<", ">Home page<", ">Billing<", ">Documents<", ">Email templates<", ">Audit log<"]
    assert [tabs.index(label) for label in labels] == sorted(tabs.index(label) for label in labels)
    manager = _client(app, DEMO, "manager@demospace.com")
    assert _get(manager, DEMO, "/admin/settings/home-page").status_code in (302, 403)


def test_saved_content_shows_on_the_public_home_page_and_blank_about_is_hidden():
    app, _ = _seeded_app()
    public = app.test_client()
    before = _get(public, DEMO, "/").get_data(as_text=True)
    assert "A workspace" in before and 'id="about"' not in before and "Est. " not in before

    owner = _client(app, DEMO, "owner@demospace.com")
    data = {"headline": "Work well, together.", "established_year": "2019", "show_stats": "y",
            "hero_image_url": "https://example.com/hero.jpg", "about_title": "Our story",
            "about_text": "We opened in a converted mill."}
    assert _post(owner, DEMO, "/admin/settings/home-page", data).status_code == 302
    assert _saved(app)["headline"] == "Work well, together."
    after = _get(public, DEMO, "/").get_data(as_text=True)
    assert "Work well, together." in after and "Est. 2019" in after
    assert 'id="about"' in after and "We opened in a converted mill." in after
    assert "--hero-image: url('https://example.com/hero.jpg')" in after
    assert "Desks open now" in after


def test_live_numbers_can_be_hidden_and_the_hero_link_cannot_carry_markup():
    app, _ = _seeded_app()
    owner = _client(app, DEMO, "owner@demospace.com")
    bad = _post(owner, DEMO, "/admin/settings/home-page",
                {"hero_image_url": "https://x.com/a.jpg');background:red;--x:url('"})
    assert bad.status_code == 200 and "full https:// link" in bad.get_data(as_text=True)
    assert "hero_image_url" not in _saved(app)
    assert _post(owner, DEMO, "/admin/settings/home-page", {"headline": "Hello"}).status_code == 302  # show_stats unchecked
    assert "Desks open now" not in _get(app.test_client(), DEMO, "/").get_data(as_text=True)


def test_public_site_uses_the_portal_palette_and_owner_can_preview_while_signed_in():
    app, _ = _seeded_app()
    home = _get(app.test_client(), DEMO, "/").get_data(as_text=True)
    assert "--saffron: #5b5bd6" in home and "#f5b642" not in home and "--navy: #11152a" in home
    owner = _client(app, DEMO, "owner@demospace.com")
    assert _get(owner, DEMO, "/").status_code == 302                       # signed in: straight to the dashboard
    preview = _get(owner, DEMO, "/?preview=1")
    assert preview.status_code == 200 and "marketing-nav" in preview.get_data(as_text=True)
    employee = _client(app, DEMO, "employee@acmeco.com")
    assert _get(employee, DEMO, "/?preview=1").status_code == 302          # only operator staff can preview
