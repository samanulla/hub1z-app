"""Public pricing and the platform catalog share a single set of data."""
import os
import importlib.util
import re
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

os.environ.setdefault("FLASK_ENV", "testing")

from app import create_app
from app.extensions import db
from app.models import (
    PlatformProfile, PricingTier, TierStatus, PlatformModule, User, UserRole, Operator, OperatorStatus,
)
from app.services.catalog import ensure_catalog
from app.services.pricing_page import public_plans

APEX = {"Host": "hub1z.com"}


def _app():
    app = create_app({"SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:", "WTF_CSRF_ENABLED": False,
                      "MAIL_SUPPRESS_SEND": True, "STORAGE_BACKEND": "local",
                      "LOCAL_STORAGE_DIR": "./var/test-uploads"})
    with app.app_context():
        db.create_all()
        ensure_catalog()
        profile = PlatformProfile.get()
        profile.pricing_page_public = True
        profile.trial_days = 14
        owner = User(email="platform@hub1z.com", full_name="Owner", role=UserRole.PLATFORM_OWNER, is_active=True)
        owner.set_password("OwnerPass123!")
        tier = PricingTier(key="growth", name="Growth", monthly_price=Decimal("1000"), annual_discount=10,
                           annual_price=Decimal("10800"), description="Run more than one space.",
                           status=TierStatus.ACTIVE, is_public=True, max_locations=3,
                           included_active_contracted_seats=100, max_staff_users=8, storage_mb=2048,
                           is_highlighted=True)
        tier.module_catalog = PlatformModule.query.filter(PlatformModule.code.in_(["payroll", "lead_export"])).all()
        db.session.add_all([owner, tier])
        db.session.commit()
    return app


def _owner_client(app):
    c = app.test_client()
    c.post("/auth/login", data={"email": "platform@hub1z.com", "password": "OwnerPass123!"}, headers=APEX)
    return c


def test_catalog_is_idempotent_and_keeps_admin_edits():
    app = _app()
    with app.app_context():
        m = PlatformModule.query.filter_by(code="extra_storage").one()
        m.monthly_price = Decimal("299")
        m.name = "Storage pack"
        count = PlatformModule.query.count()
        assert ensure_catalog() == 0
        db.session.commit()
        assert PlatformModule.query.count() == count
        assert m.monthly_price == Decimal("299") and m.name == "Storage pack"


def test_annual_price_and_features_come_from_the_tier():
    app = _app()
    with app.app_context():
        plans = public_plans("annual")
        assert len(plans) == 1
        assert plans[0]["price"] == Decimal("900")
        assert plans[0]["annual"] == Decimal("10800")
        assert plans[0]["features"] == ["Lead export", "Payroll"]  # catalog order, not alphabetical
        assert "2 GB document storage" in plans[0]["limits"]

    page = app.test_client().get("/pricing?billing=annual", headers=APEX).data.decode()
    assert "₹900" in page and "₹10,800 billed annually" in page and "save up to 10%" in page
    assert "Lead export" in page and "Payroll" in page and "GST invoices" in page
    assert "Accounting Sync" in page and "Coming soon" in page
    assert "save 2 months" not in page and "Scale" not in page


def test_tier_settings_control_public_page_and_trial():
    app = _app()
    c = _owner_client(app)
    page = c.get("/platform/tiers", headers=APEX)
    assert len(re.findall(r'<label[^>]*for="pricing_page_public"', page.data.decode())) == 1
    response = c.post("/platform/tiers/settings", data={"trial_days": "21", "trial_tier_key": "growth",
                                                       "renewal_notice_days": "10"}, headers=APEX)
    assert response.status_code == 302
    with app.app_context():
        p = PlatformProfile.get()
        assert p.pricing_page_public is False and p.trial_days == 21 and p.renewal_notice_days == 10
    page = c.get("/pricing", headers=APEX).data.decode()
    assert "Pricing is being prepared" in page and "₹1,000" not in page
    response = c.post("/platform/tiers/settings", data={"trial_days": "21", "trial_tier_key": "growth",
                                                       "renewal_notice_days": "10", "pricing_page_public": "y"}, headers=APEX)
    assert response.status_code == 302
    assert "₹1,000" in c.get("/pricing", headers=APEX).data.decode()


def test_self_serve_signup_uses_the_configured_trial_days():
    app = _app()
    with app.app_context():
        PlatformProfile.get().trial_days = 21
        db.session.commit()
    c = app.test_client()
    assert b"21 days" in c.get("/auth/register/operator", headers=APEX).data
    before = datetime.utcnow()
    result = c.post("/auth/register/operator", data={
        "business_name": "New Space", "slug": "new-space", "admin_full_name": "Jane Owner",
        "admin_email": "jane@newspace.example", "password": "JanePass123!", "confirm": "JanePass123!",
        "country_code": "IN"}, headers=APEX)
    assert result.status_code == 302
    with app.app_context():
        op = Operator.query.execution_options(skip_operator_filter=True).filter_by(slug="new-space").one()
        assert before + timedelta(days=21) <= op.trial_ends_at <= datetime.utcnow() + timedelta(days=21)


def test_manager_with_suspension_permission_can_reactivate_but_not_edit():
    app = _app()
    with app.app_context():
        mgr = User(email="manager@hub1z.com", full_name="Mgr", role=UserRole.PLATFORM_MANAGER, is_active=True)
        mgr.set_password("ManagerPass123!")
        mgr.set_platform_permissions(["operator_suspension"])
        op = Operator(slug="space", name="Space", primary_domain="space.hub1z.com", status=OperatorStatus.ACTIVE)
        db.session.add_all([mgr, op]); db.session.commit()
        op_id = op.id
    c = app.test_client()
    c.post("/auth/login", data={"email": "manager@hub1z.com", "password": "ManagerPass123!"}, headers=APEX)
    page = c.get("/platform/operators", headers=APEX)
    assert page.status_code == 200
    html = page.data.decode()
    assert f"/platform/operators/{op_id}/suspend" in html
    assert f"/platform/operators/{op_id}/edit" not in html
    assert "/platform/operators/new" not in html and "/platform/operators/invite" not in html
    assert c.post(f"/platform/operators/{op_id}/suspend", headers=APEX).status_code == 302
    with app.app_context():
        assert db.session.get(Operator, op_id).status == OperatorStatus.SUSPENDED
    assert c.post(f"/platform/operators/{op_id}/activate", headers=APEX).status_code == 302
    with app.app_context():
        assert db.session.get(Operator, op_id).status == OperatorStatus.ACTIVE
    assert c.get(f"/platform/operators/{op_id}/edit", headers=APEX).status_code == 403
    assert c.get("/platform/team", headers=APEX).status_code == 403


def test_payment_setup_gst_fields_round_trip():
    app = _app()
    c = _owner_client(app)
    assert c.get("/platform/payment-details/qr.png", headers=APEX).status_code == 404
    response = c.post("/platform/payment-details", data={"legal_name": "Hub1z", "upi_id": "hub1z@icici",
                                                        "gst_state": "29", "default_gst_rate": "18",
                                                        "invoice_prefix": "hub", "sac_code": "998314",
                                                        "payment_terms_days": "0"}, headers=APEX)
    assert response.status_code == 302
    with app.app_context():
        p = PlatformProfile.get()
        assert p.gst_state == "29" and p.default_gst_rate == Decimal("18") and p.invoice_prefix == "HUB"
        assert p.sac_code == "998314" and p.payment_terms_days == 0
    qr = c.get("/platform/payment-details/qr.png", headers=APEX)
    assert qr.status_code == 200 and qr.mimetype == "image/png" and qr.data.startswith(b"\x89PNG")


def test_operator_management_cannot_bypass_suspension_permission():
    app = _app()
    with app.app_context():
        manager = User(email="ops@hub1z.com", full_name="Operations", role=UserRole.PLATFORM_MANAGER,
                       is_active=True)
        manager.set_password("ManagerPass123!")
        manager.set_platform_permissions(["operators"])
        operator = Operator(slug="space", name="Space", status=OperatorStatus.ACTIVE)
        db.session.add_all([manager, operator])
        db.session.commit()
        operator_id = operator.id
    client = app.test_client()
    client.post("/auth/login", data={"email": "ops@hub1z.com", "password": "ManagerPass123!"}, headers=APEX)
    assert client.post("/platform/operators/new", data={"status": "suspended"}, headers=APEX).status_code == 403
    assert client.post(f"/platform/operators/{operator_id}/edit", data={"status": "suspended"},
                       headers=APEX).status_code == 403
    with app.app_context():
        operator = db.session.get(Operator, operator_id)
        assert operator.status == OperatorStatus.ACTIVE
        operator.status = OperatorStatus.SUSPENDED
        db.session.commit()
    html = client.get(f"/platform/operators/{operator_id}/edit", headers=APEX).data.decode()
    assert re.search(r'<option(?=[^>]*value="suspended")(?=[^>]*selected)[^>]*>', html)
    assert client.post(f"/platform/operators/{operator_id}/edit", data={"status": "active"},
                       headers=APEX).status_code == 403
    with app.app_context():
        assert db.session.get(Operator, operator_id).status == OperatorStatus.SUSPENDED


def test_public_pricing_excludes_retired_future_and_unavailable_items():
    app = _app()
    with app.app_context():
        tier = PricingTier.query.filter_by(key="growth").one()
        payroll = PlatformModule.query.filter_by(code="payroll").one()
        payroll.availability = "hidden"
        export = PlatformModule.query.filter_by(code="lead_export").one()
        export.availability = "coming_soon"
        db.session.add(PricingTier(key="scale", name="Scale", status=TierStatus.ACTIVE, is_public=True))
        db.session.add(PricingTier(key="future", name="Future", status=TierStatus.ACTIVE, is_public=True,
                                  effective_from=date.today() + timedelta(days=1)))
        db.session.add(PricingTier(key="expired", name="Expired", status=TierStatus.ACTIVE, is_public=True,
                                  effective_to=date.today() - timedelta(days=1)))
        db.session.add(PricingTier(key="disabled", name="Disabled", status=TierStatus.ACTIVE,
                                  is_active=False, is_public=True))
        db.session.commit()
        plans = public_plans()
        assert [plan["tier"].key for plan in plans] == ["growth"]
        assert plans[0]["features"] == []
        tier.all_features = True
        db.session.commit()
        assert "Payroll" not in public_plans()[0]["features"]
        assert "Lead export" not in public_plans()[0]["features"]


@pytest.mark.parametrize("populated", [False, True])
def test_catalog_migration_preserves_existing_data_and_rolls_back(monkeypatch, populated):
    new_columns = {
        "pricing_tiers": {"description", "sort_order", "is_public", "is_highlighted", "contact_sales",
                          "all_features", "max_staff_users", "max_open_leads", "storage_mb"},
        "platform_modules": {"description", "unit_price", "unit_label", "availability", "sort_order"},
        "platform_profile": {"gst_state", "default_gst_rate", "sac_code", "invoice_prefix", "payment_terms_days",
                             "trial_days", "trial_tier_key", "renewal_notice_days", "pricing_page_public"},
        "tier_modules": set(),
    }
    metadata = sa.MetaData()
    for name, excluded in new_columns.items():
        sa.Table(name, metadata, *[
            sa.Column(column.name, column.type, primary_key=column.primary_key, nullable=column.nullable,
                      default=column.default)
            for column in db.metadata.tables[name].columns if column.name not in excluded
        ])
    tiers = metadata.tables["pricing_tiers"]
    for name in ("max_seats", "max_private_offices", "max_rooms"):
        tiers.append_column(sa.Column(name, sa.Integer()))
    for name in ("included_features", "premium_modules"):
        tiers.append_column(sa.Column(name, sa.Text()))
    tiers.append_column(sa.Column("trial_period_days", sa.Integer(), nullable=False))
    engine = sa.create_engine("sqlite:///:memory:")
    metadata.create_all(engine)
    migration_path = Path(__file__).resolve().parents[1] / "migrations/versions/b8d3f6a2c914_pricing_catalog_and_tiers.py"
    spec = importlib.util.spec_from_file_location("pricing_migration", migration_path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with engine.begin() as connection:
        if populated:
            for tier_id, key in enumerate(("starter", "growth", "enterprise", "scale"), start=1):
                connection.execute(tiers.insert().values(
                    id=tier_id, key=key, name=key.title(), monthly_price=1500, annual_price=16200,
                    annual_discount=10, status=TierStatus.ACTIVE, max_locations=5,
                    included_active_contracted_seats=150, additional_seat_rate=70, pricing_version=3,
                    max_seats=44, max_rooms=7, max_private_offices=3, trial_period_days=9,
                    included_features="legacy features", premium_modules="legacy modules"))
            connection.execute(metadata.tables["platform_modules"].insert().values(
                id=1, code="payroll", name="Custom payroll", monthly_price=99, kind="module"))
            connection.execute(metadata.tables["tier_modules"].insert().values(tier_id=2, module_id=1))
            connection.execute(metadata.tables["platform_profile"].insert().values(legal_name="Existing entity"))
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
        migration.upgrade()
        assert connection.execute(sa.text("SELECT COUNT(*) FROM pricing_tiers WHERE key IN "
                                          "('starter', 'growth', 'enterprise')")).scalar() == 3
        assert connection.execute(sa.text("SELECT COUNT(*) FROM tier_modules WHERE tier_id = "
                                          "(SELECT id FROM pricing_tiers WHERE key = 'growth')")).scalar() == 10
        assert connection.execute(sa.text("SELECT all_features FROM pricing_tiers WHERE key = 'enterprise'")).scalar()
        if populated:
            assert connection.execute(sa.text("SELECT is_public FROM pricing_tiers WHERE key = 'scale'")).scalar() == 0
            assert connection.execute(sa.text("SELECT pricing_page_public FROM platform_profile")).scalar() == 0
            row = connection.execute(sa.text("SELECT monthly_price, max_locations, max_seats, trial_period_days, "
                                             "pricing_version FROM pricing_tiers WHERE key = 'growth'")).one()
            assert tuple(row) == (1500, 5, 44, 9, 3)
            row = connection.execute(sa.text("SELECT name, monthly_price, kind FROM platform_modules "
                                             "WHERE code = 'payroll'")).one()
            assert tuple(row) == ("Custom payroll", 99, "feature")
        else:
            assert connection.execute(sa.text("SELECT monthly_price FROM pricing_tiers WHERE key = 'starter'")).scalar() is None
            assert connection.execute(sa.text("SELECT status FROM pricing_tiers WHERE key = 'starter'")).scalar() == "DRAFT"
        connection.execute(PricingTier.__table__.insert().values(key="additional", name="Additional"))
        module_count = connection.execute(sa.text("SELECT COUNT(*) FROM platform_modules")).scalar()
        migration.downgrade()
        assert connection.execute(sa.text("SELECT COUNT(*) FROM platform_modules")).scalar() == module_count
        if populated:
            row = connection.execute(sa.text("SELECT max_seats, max_rooms, max_private_offices, trial_period_days, "
                                             "included_features, premium_modules FROM pricing_tiers "
                                             "WHERE key = 'growth'")).one()
            assert tuple(row) == (44, 7, 3, 9, "legacy features", "legacy modules")
        migration.upgrade()
        assert connection.execute(sa.text("SELECT COUNT(*) FROM platform_modules")).scalar() == module_count
