"""Left menus for platform staff, company admins, employees and individuals."""
import os

os.environ.setdefault("FLASK_ENV", "testing")

from tests.test_release_upi_parcels_alerts import DEMO, _client, _get, _seeded_app
from tests.test_role_paths import APEX, OWNER_PASSWORD


def _sidebar(html: bytes) -> bytes:
    return html.split(b'<aside class="h-side"', 1)[1].split(b"</aside>", 1)[0]


def test_employees_and_individuals_can_reach_everything_they_may_use_from_the_menu():
    app, _ = _seeded_app()
    for email in ("employee@acmeco.com", "individual@demospace.com"):
        side = _sidebar(_get(_client(app, DEMO, email), DEMO, "/me/").data)
        for label in (b">Book<", b">My bookings<", b">My parcels<", b">Announcements<", b">Member directory<",
                      b">Guest passes<", b">Visitors<", b">Printing credits<", b">Refer &amp; earn<"):
            assert label in side, (email, label)
        assert b">Calendar<" not in side and b">Support" not in side and b">Day pass<" not in side, email
    assert b">Invoices &amp; payments<" in _sidebar(_get(_client(app, DEMO, "individual@demospace.com"), DEMO, "/me/").data)
    assert b">Invoices &amp; payments<" not in _sidebar(_get(_client(app, DEMO, "employee@acmeco.com"), DEMO, "/me/").data)


def test_member_community_group_opens_on_its_own_pages():
    app, _ = _seeded_app()
    client = _client(app, DEMO, "employee@acmeco.com")
    for path in ("/hub/printing", "/hub/referrals", "/hub/visitors", "/hub/community", "/me/bookings"):
        page = _get(client, DEMO, path)
        assert page.status_code == 200, path
        side = _sidebar(page.data)
        assert b'h-nav-link active' in side, path
    assert b'data-group="m-community" open' in _sidebar(_get(client, DEMO, "/hub/printing").data)


def test_platform_menu_has_one_platform_group_instead_of_three_single_link_groups():
    app, _ = _seeded_app()
    owner = _client(app, APEX, "admin@hub1z.com", OWNER_PASSWORD)
    side = _sidebar(_get(owner, APEX, "/platform/").data)
    for old in (b'h-nav-label">Reports<', b'h-nav-label">Owner only<'):
        assert old not in side
    group = side.split(b'data-group="p-platform"', 1)[1]
    assert group.index(b">Reports<") < group.index(b">Documents<") < group.index(b">Platform team<")
    manager = _client(app, APEX, "manager@hub1z.com", "DemoPass123!")
    manager_side = _sidebar(_get(manager, APEX, "/platform/").data)
    assert b">Platform team<" not in manager_side


def test_company_admin_pages_with_a_single_tab_show_no_tab_bar():
    app, _ = _seeded_app()
    client = _client(app, DEMO, "admin@acmeco.com")
    people = _get(client, DEMO, "/company/employees").data
    assert b'aria-label="Section navigation"' not in people
    invoices = _get(client, DEMO, "/company/invoices").data
    assert b'aria-label="Section navigation"' in invoices and b">Plans &amp; subscriptions<" in invoices
    assert b">Support" not in _sidebar(invoices)
