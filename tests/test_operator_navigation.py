"""Operator navigation: grouped menu, role-based Money/Setup, quick-create menu, subscriptions list, company hub."""
import os

os.environ.setdefault("FLASK_ENV", "testing")

from app.extensions import db
from app.models import Company, Invoice, InvoiceStatus, Operator, User, UserRole
from tests.test_release_upi_parcels_alerts import DEMO, PERSONA_PASSWORD, _client, _get, _seeded_app

LABEL = 'h-nav-label">%s<'


def test_owner_sees_grouped_menu_with_money_setup_and_marketplace_last():
    app, _ = _seeded_app()
    owner = _client(app, DEMO, "owner@demospace.com")
    html = _get(owner, DEMO, "/admin/").get_data(as_text=True)
    for group in ("Today", "Customers", "Space Setup", "Team", "Finance"):
        assert LABEL % group in html, group
    for item in (">Front desk<", ">Companies<", ">Members<", ">Subscriptions<", ">Inventory<",
                 ">Invoices<", ">Plans<", ">Settings<", ">Community<"):
        assert item in html, item
    assert html.index(LABEL % "Today") < html.index(LABEL % "Customers") < html.index(LABEL % "Finance") \
        < html.index(">Settings<")
    assert ">Services<" not in html
    assert 'data-quick-create' in html and ">Subscription<" in html and ">Invoice<" in html


def test_location_manager_does_not_see_money_or_setup():
    app, _ = _seeded_app()
    with app.app_context():
        operator = Operator.query.filter_by(primary_domain=DEMO).one()
        user = User(operator_id=operator.id, email="loc@demospace.com", full_name="Loc",
                    role=UserRole.LOCATION_MANAGER, is_active=True)
        user.set_password(PERSONA_PASSWORD)
        db.session.add(user)
        db.session.commit()
    client = _client(app, DEMO, "loc@demospace.com", PERSONA_PASSWORD)
    html = _get(client, DEMO, "/admin/").get_data(as_text=True)
    assert LABEL % "Customers" in html and LABEL % "Space Setup" in html
    assert LABEL % "Finance" not in html and ">Settings<" not in html


def test_subscriptions_list_and_picker():
    app, _ = _seeded_app()
    owner = _client(app, DEMO, "owner@demospace.com")
    page = _get(owner, DEMO, "/admin/subscriptions")
    assert page.status_code == 200 and b"New subscription" in page.data
    with app.app_context():
        company_id = Company.query.execution_options(skip_operator_filter=True).filter_by(name="Acme Co").first().id
    pick = _get(owner, DEMO, f"/admin/subscriptions/new?company_id={company_id}")
    assert pick.status_code == 302 and pick.headers["Location"].endswith(f"/admin/companies/{company_id}/subscriptions/new")
    assert _get(owner, DEMO, "/admin/subscriptions/new").status_code == 302


def test_company_page_is_a_hub_with_sections():
    app, _ = _seeded_app()
    owner = _client(app, DEMO, "owner@demospace.com")
    with app.app_context():
        company_id = Company.query.execution_options(skip_operator_filter=True).filter_by(name="Acme Co").first().id
    html = _get(owner, DEMO, f"/admin/companies/{company_id}").get_data(as_text=True)
    for anchor in ('href="#subscriptions"', 'href="#spaces"', 'href="#invoices"', 'id="spaces"', 'id="invoices"'):
        assert anchor in html, anchor
    assert "Spaces &amp; people" in html and "Recent invoices" in html


def test_drafts_badge_counts_subscription_invoices_waiting_to_be_sent():
    from app.services.nav import nav_badges  # noqa: F401  (the badge is rendered through the sidebar)
    app, _ = _seeded_app()
    owner = _client(app, DEMO, "owner@demospace.com")
    with app.app_context():
        operator = Operator.query.filter_by(primary_domain=DEMO).one()
        company = Company.query.execution_options(skip_operator_filter=True).filter_by(name="Acme Co").first()
        sub = company.subscriptions[0] if company.subscriptions else None
        if sub is None:
            return
        from datetime import date
        db.session.add(Invoice(operator_id=operator.id, number="DRAFT-TEST-1", company_id=company.id,
                               subscription_id=sub.id, period_start=date(2026, 3, 1), period_end=date(2026, 3, 31),
                               due_date=date(2026, 3, 5), status=InvoiceStatus.DRAFT))
        db.session.commit()
    html = _get(owner, DEMO, "/admin/").get_data(as_text=True)
    assert 'h-nav-badge">1<' in html


def test_menu_groups_collapse_and_the_current_page_keeps_its_group_open():
    app, _ = _seeded_app()
    owner = _client(app, DEMO, "owner@demospace.com")
    html = _get(owner, DEMO, "/admin/companies").get_data(as_text=True)
    side = html.split('<aside class="h-side"', 1)[1].split("</aside>", 1)[0]
    assert '<details class="h-nav-group" data-group="customers" open data-active="1">' in side
    for closed in ("space", "team", "finance"):
        assert f'<details class="h-nav-group" data-group="{closed}">' in side, closed
    assert LABEL % "Today" in side and "h-nav-group\" data-group=\"today\"" not in side   # daily pages never collapse
    assert 'class="h-nav-label">Settings<' not in side and ">Settings<" in side            # one link, no caption
    inventory = _get(owner, DEMO, "/admin/locations").get_data(as_text=True).split('<aside class="h-side"', 1)[1]
    assert 'data-group="space" open data-active="1"' in inventory and 'data-group="customers">' in inventory
