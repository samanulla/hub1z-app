"""Tests for the reversible entitlement foundation and shadow resolver."""
import os
import importlib.util
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
os.environ.setdefault("FLASK_ENV", "testing")

from app import create_app
from app.extensions import db
from app.models import (EntitlementDefinition, EntitlementOfferGrant, EntitlementOfferVersion, EntitlementUsageBucket,
                        Operator, OperatorStatus, TenantEntitlementGrant, TenantPlanBinding)
from app.services.catalog import (ENTITLEMENT_DEFINITIONS, EntitlementValueType,
                                  ensure_catalog, ensure_entitlement_definitions)
from app.services.entitlement_resolver import (check_entitlement, reserve_usage,
                                               settle_usage_reservation)
from app.services.entitlements import has_feature


def _app():
    app = create_app({"SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:", "WTF_CSRF_ENABLED": False,
                      "ENTITLEMENTS_ENFORCEMENT_ENABLED": False, "MAIL_SUPPRESS_SEND": True})
    with app.app_context():
        db.create_all()
        ensure_catalog()
        ensure_entitlement_definitions()
        operator = Operator(slug="entitlements", name="Entitlements", status=OperatorStatus.TRIAL)
        db.session.add(operator)
        db.session.commit()
    return app


def _version(operator, now):
    version = EntitlementOfferVersion(offer_key="configurable-plan", version=1, kind="base_plan",
                                      status="draft", name="Configured plan", effective_from=now - timedelta(days=1))
    db.session.add(version)
    db.session.flush()
    db.session.add_all([
        EntitlementOfferGrant(offer_version_id=version.id, entitlement_key="payroll", scope_key="*",
                              boolean_value=True, combine_rule="enable"),
        EntitlementOfferGrant(offer_version_id=version.id, entitlement_key="open_manual_leads", scope_key="*",
                              numeric_value=Decimal("10"), combine_rule="add"),
        EntitlementOfferGrant(offer_version_id=version.id, entitlement_key="pan_verification", scope_key="*",
                              numeric_value=Decimal("5"), period_seconds=2592000, combine_rule="add"),
    ])
    db.session.flush()
    version.status = "published"
    db.session.add(TenantPlanBinding(operator_id=operator.id, offer_version_id=version.id,
                                     effective_from=now - timedelta(days=1), state="active"))
    db.session.flush()
    return version


def test_registry_is_typed_and_future_capabilities_stay_unusable():
    app = _app()
    with app.app_context():
        assert ENTITLEMENT_DEFINITIONS["payroll"].value_type == EntitlementValueType.BOOLEAN
        assert ENTITLEMENT_DEFINITIONS["open_manual_leads"].value_type == EntitlementValueType.ALLOWANCE
        assert ENTITLEMENT_DEFINITIONS["pan_verification"].value_type == EntitlementValueType.USAGE
        assert ENTITLEMENT_DEFINITIONS["native_apps"].built is False
        assert ensure_entitlement_definitions() == 0
        assert not has_feature(Operator.query.first(), "native_apps")


def test_shadow_resolver_uses_versioned_grants_but_returns_legacy_decision():
    app = _app()
    with app.app_context():
        operator = Operator.query.first()
        operator.status = OperatorStatus.ACTIVE
        operator.plan_tier = "starter"
        now = datetime.utcnow()
        _version(operator, now)
        db.session.commit()

        decision = check_entitlement(operator.id, "payroll", now=now)
        assert decision.allowed is False
        assert decision.requested_allowed is True
        assert decision.shadow_match is False
        from app.services.entitlements import has_feature
        app.config["ENTITLEMENTS_SHADOW_ENABLED"] = True
        assert has_feature(operator, "payroll") is False
        quota = check_entitlement(operator.id, "open_manual_leads", action="create", quantity=11, now=now)
        assert quota.allowed is True
        assert quota.requested_allowed is False
        assert quota.shadow_match is False
        assert check_entitlement(operator.id, "existing_bookings", action="checkin", now=now).allowed is True
        assert check_entitlement(operator.id, "native_apps", now=now).requested_allowed is False


def test_protected_actions_remain_allowed_without_a_new_plan_binding():
    app = _app()
    with app.app_context():
        operator = Operator.query.first()
        decision = check_entitlement(operator.id, "existing_bookings", action="checkin")
        assert decision.allowed is True and decision.source == "protected_action"


def test_usage_reservation_is_idempotent_and_settlement_does_not_double_count():
    app = _app()
    with app.app_context():
        operator = Operator.query.first()
        now = datetime.utcnow()
        _version(operator, now)
        db.session.add(EntitlementDefinition(key="sample_usage", name="Sample usage",
                            value_type="usage", measurement="period", built=True))
        db.session.commit()
        start, end = now.replace(hour=0, minute=0, second=0, microsecond=0), now + timedelta(days=30)
        reservation_id = reserve_usage(operator.id, "sample_usage", 3, "*", start, end, 5, "operation-1", now)
        assert reserve_usage(operator.id, "sample_usage", 3, "*", start, end, 5, "operation-1", now) == reservation_id
        db.session.commit()

        settle_usage_reservation(operator.id, reservation_id, commit=True)
        db.session.commit()
        bucket = EntitlementUsageBucket.query.one()
        assert bucket.committed == Decimal("3") and bucket.reserved == Decimal("0")

        try:
            reserve_usage(operator.id, "sample_usage", 3, "*", start, end, 5, "operation-2", now)
        except ValueError as error:
            assert "exhausted" in str(error)
        else:
            raise AssertionError("quota reservation exceeded the allowance")


def test_published_offer_terms_cannot_be_mutated():
    app = _app()
    with app.app_context():
        operator = Operator.query.first()
        version = _version(operator, datetime.utcnow())
        db.session.commit()
        version.name = "Changed after publication"
        try:
            db.session.flush()
        except ValueError as error:
            assert "immutable" in str(error)
        else:
            raise AssertionError("published offer version was mutated")
        db.session.rollback()
        version = EntitlementOfferVersion.query.one()
        version.status = "retired"
        db.session.commit()
        assert version.status == "retired"


def test_explicit_override_wins_over_base_and_addon_grants():
    app = _app()
    with app.app_context():
        operator = Operator.query.first()
        now = datetime.utcnow()
        version = _version(operator, now)
        db.session.add(TenantEntitlementGrant(
            operator_id=operator.id, entitlement_key="payroll", source="override", grant_mode="deny",
            scope_key="*", boolean_value=False, priority=10, effective_from=now - timedelta(days=1),
            reason="approved test override"))
        db.session.flush()
        db.session.commit()
        decision = check_entitlement(operator.id, "payroll", now=now)
        assert decision.requested_allowed is False and decision.source.endswith("override")
        numeric_deny = TenantEntitlementGrant(
            operator_id=operator.id, entitlement_key="open_manual_leads", source="override", grant_mode="deny",
            scope_key="*", priority=10, effective_from=now - timedelta(days=1), reason="approved numeric deny")
        db.session.add(numeric_deny)
        db.session.commit()
        assert not check_entitlement(operator.id, "open_manual_leads", quantity=0, now=now).requested_allowed


def test_entitlement_migration_upgrade_and_downgrade():
    metadata = sa.MetaData()
    sa.Table("operators", metadata, sa.Column("id", sa.Integer(), primary_key=True))
    sa.Table("users", metadata, sa.Column("id", sa.Integer(), primary_key=True))
    engine = sa.create_engine("sqlite:///:memory:")
    metadata.create_all(engine)
    migration_path = (Path(__file__).resolve().parents[1] /
                      "migrations/versions/fc72b8d19a04_entitlement_foundation.py")
    spec = importlib.util.spec_from_file_location("entitlement_migration", migration_path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with engine.begin() as connection:
        from unittest.mock import patch
        with patch.object(migration, "op", Operations(MigrationContext.configure(connection))):
            migration.upgrade()
            assert "entitlement_usage_events" in sa.inspect(connection).get_table_names()
            migration.downgrade()
            assert "entitlement_usage_events" not in sa.inspect(connection).get_table_names()
