"""Operator data isolation — the platform's highest-priority guarantee.

Two operators share one database; nothing owned by one may ever be visible to,
or writable by, the other. These tests are black-box: operator A's data carries a
marker, then every GET page is requested as each kind of operator B user (and
anonymously) and must never contain it.
"""
import os
from datetime import date, datetime, timedelta
from decimal import Decimal

os.environ.setdefault("FLASK_ENV", "testing")

from flask import g

from app import create_app
from app.extensions import db
from app.models import (
    BillingCycle, BillingUnit, Company, CompanyStatus, ConferenceRoom, Floor, LocationScope,
    Location, Operator, OperatorStatus, PlanScope, PlanStatus, PlanType, PricingPlan,
    Subscription, SubscriptionStatus, User, UserRole,
)
from app.models.finance import Refund
from app.models.invoice import Invoice, InvoiceLineItem, InvoiceStatus, Payment
from app.models.operator import OperatorScoped
from app.models.settings import SystemSettings

HA, HB, APEX = "zza.hub1z.com", "zzb.hub1z.com", "hub1z.com"
PW = "ProbePass123!"
MARKERS = [b"ZZA", b"98765.43", b"98,765.43", b"4321.09", b"4,321.09"]

# Tables that legitimately have no operator_id / are platform-level.
NO_OPERATOR_COLUMN = {"operators", "location_amenities", "room_amenity_link", "pricing_plan_locations",
                      "pricing_tiers", "platform_modules", "platform_expenses", "tier_modules"}
PLATFORM_LEVEL = {"operator_subscriptions", "operator_usage_snapshots", "platform_credit_notes",
                  "platform_invoices", "platform_refunds"}
NULLABLE_OPERATOR_ID = {"users", "audit_logs", "documents", "system_settings",
                        "leads", "lead_activities", "attendance_records"}  # the last three also hold Platform rows


def _app():
    app = create_app({"SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:", "WTF_CSRF_ENABLED": False,
                      "MAIL_SUPPRESS_SEND": True, "STORAGE_BACKEND": "local",
                      "LOCAL_STORAGE_DIR": "./var/test-uploads"})
    with app.app_context():
        db.create_all()
    return app


def _user(op, email, name, role, company=None):
    u = User(operator_id=op.id, email=email, full_name=name, role=role,
             company_id=company.id if company else None, is_active=True)
    u.set_password(PW)
    db.session.add(u)
    return u


def _plan(operator_id, name):
    return PricingPlan(operator_id=operator_id, name=name, scope=PlanScope.INDIVIDUAL,
                       plan_type=PlanType.HOT_DESK, billing_unit=BillingUnit.PER_SEAT,
                       billing_cycle=BillingCycle.MONTHLY, base_price=Decimal("1000"),
                       location_scope=LocationScope.ALL, status=PlanStatus.ACTIVE, is_active=True)


def _seed(app):
    with app.app_context():
        a = Operator(slug="zza", name="ZZA Operator", primary_domain=HA, status=OperatorStatus.ACTIVE)
        b = Operator(slug="zzb", name="Other Operator", primary_domain=HB, status=OperatorStatus.ACTIVE)
        db.session.add_all([a, b]); db.session.flush()
        loc = Location(operator_id=a.id, name="ZZA-Location", code="ZZA1", address_line1="ZZA Street",
                       city="Chennai", country="IN", timezone="Asia/Kolkata")
        db.session.add(loc); db.session.flush()
        fl = Floor(operator_id=a.id, location_id=loc.id, level=1, name="ZZA-Floor")
        db.session.add(fl); db.session.flush()
        db.session.add(ConferenceRoom(operator_id=a.id, location_id=loc.id, floor_id=fl.id,
                                      name="ZZA-Room", code="ZR1", capacity=6, hourly_rate=300))
        ca = Company(operator_id=a.id, name="ZZA-Company", billing_email="zza@x.com",
                     status=CompanyStatus.ACTIVE)
        db.session.add(ca); db.session.flush()
        _user(a, "zza-admin@x.com", "ZZA Admin", UserRole.SUPER_ADMIN)
        _user(a, "zza-emp@x.com", "ZZA Employee", UserRole.EMPLOYEE, ca)
        plan_a = _plan(a.id, "ZZA-Plan")
        db.session.add(plan_a); db.session.flush()
        db.session.add(Subscription(operator_id=a.id, plan_id=plan_a.id, company_id=ca.id, quantity=1,
                                    unit_price=1000, start_date=date.today(),
                                    status=SubscriptionStatus.ACTIVE))
        inv = Invoice(operator_id=a.id, number="ZZA-INV-1", company_id=ca.id, period_start=date.today(),
                      period_end=date.today(), due_date=date.today() + timedelta(days=15), subtotal=98765,
                      tax_amount=0, total_amount=98765, status=InvoiceStatus.ISSUED, currency="INR")
        db.session.add(inv); db.session.flush()
        db.session.add(InvoiceLineItem(operator_id=a.id, invoice_id=inv.id, description="ZZA-line",
                                       quantity=1, unit_price=98765, amount=98765))
        pay = Payment(operator_id=a.id, invoice_id=inv.id, amount=Decimal("98765.43"),
                      paid_at=datetime.utcnow())
        db.session.add(pay); db.session.flush()
        db.session.add(Refund(operator_id=a.id, payment_id=pay.id, amount=Decimal("4321.09"),
                              reason="ZZA-refund"))
        cb = Company(operator_id=b.id, name="B-Company", billing_email="b@x.com",
                     status=CompanyStatus.ACTIVE)
        db.session.add(cb); db.session.flush()
        _user(b, "b-admin@x.com", "B Admin", UserRole.SUPER_ADMIN)
        _user(b, "b-cadmin@x.com", "B Company Admin", UserRole.COMPANY_ADMIN, cb)
        _user(b, "b-ind@x.com", "B Individual", UserRole.INDIVIDUAL)
        owner = User(email="owner@hub1z.com", full_name="Platform Owner", role=UserRole.PLATFORM_OWNER,
                     is_active=True)
        owner.set_password(PW)
        db.session.add(owner)
        db.session.commit()
        return {"a": a.id, "b": b.id, "plan_a": plan_a.id, "pay_a": pay.id, "company_a": ca.id}


def _login(client, email, host):
    return client.post("/auth/login", data={"email": email, "password": PW}, headers={"Host": host})


def _get_urls(app, host):
    adapter = app.url_map.bind(host)
    for rule in app.url_map.iter_rules():
        if ("GET" not in rule.methods or rule.endpoint.startswith("static")
                or rule.endpoint in ("auth.logout",) or rule.endpoint.startswith("platform.")):
            continue
        args = sorted(rule.arguments)
        if not args:
            yield rule.endpoint, adapter.build(rule.endpoint)
        elif all(type(rule._converters[x]).__name__ == "IntegerConverter" for x in args):
            for i in range(1, 5):
                yield rule.endpoint, adapter.build(rule.endpoint, {x: i for x in args})


def _leaks(app, email):
    client = app.test_client()
    if email:
        _login(client, email, HB)
    found = []
    for endpoint, url in _get_urls(app, HB):
        r = client.get(url, headers={"Host": HB})
        if r.status_code == 200 and any(m in r.data for m in MARKERS):
            found.append(url)
    return found


def test_operator_b_never_sees_operator_a_data_on_any_page():
    app = _app()
    _seed(app)
    for email in (None, "b-admin@x.com", "b-cadmin@x.com", "b-ind@x.com"):
        assert _leaks(app, email) == [], f"operator A data visible to {email or 'anonymous'}"


def test_operator_b_cannot_touch_operator_a_records_by_id():
    app = _app()
    ids = _seed(app)
    client = app.test_client()
    _login(client, "b-admin@x.com", HB)
    paths = [
        (f"/admin/payments/{ids['pay_a']}/refund", {"amount": "1", "reason": "x", "method": "manual"}),
        (f"/admin/plans/{ids['plan_a']}/edit", {"name": "hijacked"}),
        (f"/admin/companies/{ids['company_a']}/edit", {"name": "hijacked"}),
    ]
    for path, data in paths:
        assert client.get(path, headers={"Host": HB}).status_code == 404, path
        assert client.post(path, data=data, headers={"Host": HB}).status_code == 404, path
    with app.app_context():
        assert Refund.query.count() == 1
        assert db.session.get(PricingPlan, ids["plan_a"]).name == "ZZA-Plan"
        assert db.session.get(Company, ids["company_a"]).name == "ZZA-Company"


def test_session_from_one_operator_host_is_useless_on_another():
    app = _app()
    _seed(app)
    client = app.test_client()
    _login(client, "zza-admin@x.com", HA)
    assert b"ZZA" in client.get("/admin/", headers={"Host": HA}).data
    r = client.get("/admin/", headers={"Host": HB})
    assert r.status_code != 200 and b"ZZA" not in r.data


def test_operator_areas_do_not_run_without_an_operator():
    """On the platform apex no operator filter applies, so operator areas must refuse to run."""
    app = _app()
    _seed(app)
    client = app.test_client()
    _login(client, "owner@hub1z.com", APEX)
    assert client.get("/platform/", headers={"Host": APEX}).status_code == 200
    for path in ("/admin/", "/admin/refunds", "/admin/reports/financials", "/company/", "/me/"):
        assert client.get(path, headers={"Host": APEX}).status_code == 404, path


def test_new_rows_are_stamped_with_the_request_operator():
    app = _app()
    ids = _seed(app)
    with app.test_request_context("/", headers={"Host": HA}):
        app.preprocess_request()
        plan = _plan(None, "Stamped Plan")
        db.session.add(plan); db.session.commit()
        assert plan.operator_id == ids["a"]


def test_settings_are_per_operator():
    app = _app()
    ids = _seed(app)
    with app.test_request_context("/"):
        g.operator_id = ids["a"]
        s = SystemSettings.get(); s.invoice_prefix = "AAA"; db.session.commit()
    with app.test_request_context("/"):
        g.operator_id = ids["b"]
        assert SystemSettings.get().invoice_prefix == "INV"


def test_two_operators_can_use_the_same_names_and_numbers():
    app = _app()
    ids = _seed(app)
    with app.app_context():
        for oid in (ids["a"], ids["b"]):
            db.session.add(Location(operator_id=oid, name="HQ", code="HQ", address_line1="x", city="c",
                                    country="IN", timezone="Asia/Kolkata"))
            db.session.add(Company(operator_id=oid, name="Acme", billing_email="acme@x.com",
                                   status=CompanyStatus.ACTIVE))
            db.session.add(Invoice(operator_id=oid, number="INV-202601-00001", period_start=date.today(),
                                   period_end=date.today(), due_date=date.today(), user_id=None,
                                   company_id=None))
        db.session.commit()  # would raise IntegrityError if any of these were unique globally


def test_every_table_is_operator_scoped_or_explicitly_platform_level():
    """Guard against future drift: a new table must opt in to isolation or be listed here."""
    app = _app()
    with app.app_context():
        by_table = {m.local_table.name: m.class_ for m in db.Model.registry.mappers}
        for name, table in db.metadata.tables.items():
            cls = by_table.get(name)
            scoped = bool(cls and issubclass(cls, OperatorScoped))
            if "operator_id" not in table.c:
                assert name in NO_OPERATOR_COLUMN, f"{name}: operator-owned data needs operator_id"
            elif name in PLATFORM_LEVEL:
                assert not scoped
            else:
                assert scoped, f"{name} has operator_id but is not OperatorScoped"
                assert table.c.operator_id.nullable == (name in NULLABLE_OPERATOR_ID), \
                    f"{name}: operator_id nullability changed"
