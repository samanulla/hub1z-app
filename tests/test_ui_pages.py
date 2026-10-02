"""The Platform Owner dashboard and the operator's Companies page show real numbers."""
import os

os.environ.setdefault("FLASK_ENV", "testing")

from datetime import date, datetime, timedelta
from decimal import Decimal

from app.cli import PERSONA_PASSWORD
from app.extensions import db
from app.models import (
    Company, Operator, OperatorStatus, PlatformInvoice, PlatformInvoiceStatus,
)
from app.services import company_overview, platform_dashboard
from tests.test_role_paths import APEX, DEMO, OWNER_PASSWORD, _login, _seeded_app


def _month(offset: int) -> date:
    today = date.today()
    index = today.year * 12 + today.month - 1 + offset
    return date(index // 12, index % 12 + 1, 1)


def test_platform_dashboard_numbers():
    app, _ = _seeded_app()
    with app.app_context():
        demo = Operator.query.filter_by(slug="demo").one()
        db.session.add_all([
            PlatformInvoice(operator_id=demo.id, number="PI-1", period_start=_month(0), period_end=_month(0),
                            due_date=_month(0), amount=Decimal("100000"), status=PlatformInvoiceStatus.PAID),
            PlatformInvoice(operator_id=demo.id, number="PI-2", period_start=_month(-1), period_end=_month(-1),
                            due_date=_month(-1), amount=Decimal("50000"), status=PlatformInvoiceStatus.ISSUED),
            PlatformInvoice(operator_id=demo.id, number="PI-3", period_start=_month(-1), period_end=_month(-1),
                            due_date=_month(-1), amount=Decimal("9999"), status=PlatformInvoiceStatus.VOID),
            Operator(slug="newco", name="Newco Workspace", primary_domain="newco.localhost",
                     status=OperatorStatus.TRIAL, trial_ends_at=datetime.utcnow() + timedelta(days=3)),
        ])
        db.session.commit()
        d = platform_dashboard.build()
        # Seeded operators start on the configurable trial, so only Newco ends within seven days.
        assert d["operators_total"] == 3 and d["active"] == 0 and d["trials"] == 3 and d["trials_ending_7"] == 1
        assert d["collected_this_month"] == Decimal("100000") and d["billed_this_month"] == Decimal("100000")
        assert d["chart"]["billed"][-2:] == [50000.0, 100000.0] and d["chart"]["collected"][-2:] == [0.0, 100000.0]
        assert len(d["chart"]["labels"]) == 12
        assert d["attention"][0]["operator"].slug == "newco" and d["attention"][0]["days"] in (2, 3)
        assert sum(n for _, n in d["plans"]) == 3
        assert [i.number for i in d["recent_invoices"]][0] in {"PI-1", "PI-2", "PI-3"}


def test_platform_dashboard_page():
    app, _ = _seeded_app()
    client = app.test_client()
    _login(client, APEX, "admin@hub1z.com", OWNER_PASSWORD)
    r = client.get("/platform/", headers={"Host": APEX})
    assert r.status_code == 200
    for text in (b"Welcome back", b"Collected this month", b"Operators by plan", b"Needs attention", b"Provision operator"):
        assert text in r.data, text
    assert b"$" not in r.data


def test_company_overview_numbers():
    app, _ = _seeded_app()
    with app.app_context():
        demo = Operator.query.filter_by(slug="demo").one()
        other = Operator.query.filter_by(slug="other").one()
        view = company_overview.build(demo.id)
        cards = {c["company"].name: c for c in view["cards"]}
        assert set(cards) == {"Acme Co", "Zenith Traders"}
        acme, zenith = cards["Acme Co"], cards["Zenith Traders"]
        assert (acme["seats"], acme["monthly"], acme["plan"]) == (5, Decimal("75000"), "Dedicated Desk")
        assert acme["due"] > 0 and acme["key"] == "overdue" and acme["contact_name"] == "Acme Admin"
        assert (zenith["seats"], zenith["monthly"]) == (2, Decimal("30000")) and zenith["state"] == "Maharashtra"
        assert view["total"] == 2 and view["seats_in_use"] == 7
        assert view["outstanding"] >= acme["due"] and view["ending_soon"] == 0
        assert set(c["company"].name for c in company_overview.build(other.id)["cards"]) == {"Other Co"}


def test_companies_page_shows_the_cards_and_keeps_operators_apart():
    app, _ = _seeded_app()
    client = app.test_client()
    _login(client, DEMO, "owner@demospace.com", PERSONA_PASSWORD)
    page = client.get("/admin/companies", headers={"Host": DEMO}).data
    for text in (b"Acme Co", b"Zenith Traders", b"Payment due", b"Outstanding dues", b"\xe2\x82\xb975,000", b"Cards", b"List"):
        assert text in page, text
    assert b"Other Co" not in page and b"$" not in page
