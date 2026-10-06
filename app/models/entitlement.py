"""Versioned tenant entitlements and idempotent usage accounting."""
from datetime import datetime

from sqlalchemy import (Boolean, Column, DateTime, ForeignKey, Index, Integer, JSON, Numeric,
                        String, Text, event, inspect, select)

from ..extensions import db
from ._mixins import PkMixin, TimestampMixin


class EntitlementDefinition(db.Model, PkMixin, TimestampMixin):
    __tablename__ = "entitlement_definitions"

    key = Column(String(80), unique=True, nullable=False, index=True)
    name = Column(String(160), nullable=False)
    value_type = Column(String(20), nullable=False)
    unit = Column(String(40))
    measurement = Column(String(20), nullable=False, default="capability")
    built = Column(Boolean, nullable=False, default=True)
    revision = Column(Integer, nullable=False, default=1)
    protected_actions = Column(JSON, nullable=False, default=list)


class EntitlementOfferVersion(db.Model, PkMixin, TimestampMixin):
    __tablename__ = "entitlement_offer_versions"
    __table_args__ = (db.UniqueConstraint("offer_key", "version", name="uq_entitlement_offer_version"),)

    offer_key = Column(String(80), nullable=False, index=True)
    version = Column(Integer, nullable=False)
    kind = Column(String(20), nullable=False)
    status = Column(String(20), nullable=False, default="draft")
    name = Column(String(120), nullable=False)
    currency = Column(String(3), nullable=False, default="INR")
    billing_period = Column(String(20))
    base_price = Column(Numeric(12, 2))
    effective_from = Column(DateTime)
    effective_to = Column(DateTime)
    publicly_listed = Column(Boolean, nullable=False, default=False)
    terms_snapshot = Column(JSON, nullable=False, default=dict)


class EntitlementOfferGrant(db.Model, PkMixin, TimestampMixin):
    __tablename__ = "entitlement_offer_grants"
    __table_args__ = (db.UniqueConstraint("offer_version_id", "entitlement_key", "scope_key",
                                          name="uq_offer_entitlement_scope"),)

    offer_version_id = Column(Integer, ForeignKey("entitlement_offer_versions.id", ondelete="CASCADE"),
                              nullable=False, index=True)
    entitlement_key = Column(String(80), ForeignKey("entitlement_definitions.key", ondelete="RESTRICT"),
                             nullable=False, index=True)
    scope_key = Column(String(120), nullable=False, default="*")
    boolean_value = Column(Boolean)
    numeric_value = Column(Numeric(18, 6))
    unlimited = Column(Boolean, nullable=False, default=False)
    combine_rule = Column(String(12), nullable=False, default="add")
    period_seconds = Column(Integer)


class TenantPlanBinding(db.Model, PkMixin, TimestampMixin):
    __tablename__ = "tenant_plan_bindings"
    __table_args__ = (Index("ix_tenant_binding_effective", "operator_id", "effective_from", "effective_to"),)

    operator_id = Column(Integer, ForeignKey("operators.id", ondelete="CASCADE"), nullable=False, index=True)
    offer_version_id = Column(Integer, ForeignKey("entitlement_offer_versions.id", ondelete="RESTRICT"),
                              nullable=False, index=True)
    effective_from = Column(DateTime, nullable=False)
    effective_to = Column(DateTime)
    state = Column(String(20), nullable=False, default="active")
    provenance = Column(String(30), nullable=False, default="new")
    legacy_snapshot = Column(JSON)
    contract_reference = Column(String(160))


class TenantEntitlementGrant(db.Model, PkMixin, TimestampMixin):
    __tablename__ = "tenant_entitlement_grants"

    operator_id = Column(Integer, ForeignKey("operators.id", ondelete="CASCADE"), nullable=False, index=True)
    entitlement_key = Column(String(80), ForeignKey("entitlement_definitions.key", ondelete="RESTRICT"),
                             nullable=False, index=True)
    source = Column(String(20), nullable=False)
    grant_mode = Column(String(12), nullable=False)
    scope_key = Column(String(120), nullable=False, default="*")
    boolean_value = Column(Boolean)
    numeric_value = Column(Numeric(18, 6))
    unlimited = Column(Boolean, nullable=False, default=False)
    priority = Column(Integer, nullable=False, default=0)
    effective_from = Column(DateTime, nullable=False)
    effective_to = Column(DateTime)
    reason = Column(Text)
    source_reference = Column(String(160))
    approved_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"))


class EntitlementUsageBucket(db.Model, PkMixin, TimestampMixin):
    __tablename__ = "entitlement_usage_buckets"
    __table_args__ = (db.UniqueConstraint("operator_id", "entitlement_key", "scope_key", "period_start",
                                          name="uq_entitlement_usage_bucket"),)

    operator_id = Column(Integer, ForeignKey("operators.id", ondelete="CASCADE"), nullable=False, index=True)
    entitlement_key = Column(String(80), ForeignKey("entitlement_definitions.key", ondelete="RESTRICT"),
                             nullable=False, index=True)
    scope_key = Column(String(120), nullable=False, default="*")
    period_start = Column(DateTime, nullable=False)
    period_end = Column(DateTime, nullable=False)
    committed = Column(Numeric(18, 6), nullable=False, default=0)
    reserved = Column(Numeric(18, 6), nullable=False, default=0)
    revision = Column(Integer, nullable=False, default=1)


class EntitlementUsageEvent(db.Model, PkMixin, TimestampMixin):
    __tablename__ = "entitlement_usage_events"
    __table_args__ = (db.UniqueConstraint("operator_id", "entitlement_key", "idempotency_key",
                                          name="uq_entitlement_usage_idempotency"),)

    operator_id = Column(Integer, ForeignKey("operators.id", ondelete="CASCADE"), nullable=False, index=True)
    entitlement_key = Column(String(80), ForeignKey("entitlement_definitions.key", ondelete="RESTRICT"),
                             nullable=False, index=True)
    scope_key = Column(String(120), nullable=False, default="*")
    operation_id = Column(String(120))
    idempotency_key = Column(String(160), nullable=False)
    event_kind = Column(String(20), nullable=False, default="usage")
    status = Column(String(12), nullable=False, default="committed")
    quantity = Column(Numeric(18, 6), nullable=False)
    meter_revision = Column(Integer, nullable=False, default=1)
    period_start = Column(DateTime, nullable=False)
    period_end = Column(DateTime, nullable=False)
    occurred_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    reservation_expires_at = Column(DateTime)
    provider_event_id = Column(String(160))
    provider_cost = Column(Numeric(12, 4))
    provider_currency = Column(String(3))


def _published_offer(connection, offer_id):
    return connection.execute(select(EntitlementOfferVersion.status).where(
        EntitlementOfferVersion.id == offer_id)).scalar_one_or_none() in ("published", "retired")


@event.listens_for(EntitlementOfferVersion, "before_delete")
def _protect_published_offer(mapper, connection, target):
    if _published_offer(connection, target.id):
        raise ValueError("Published entitlement offer versions are immutable.")


@event.listens_for(EntitlementOfferVersion, "before_update")
def _protect_published_offer_update(mapper, connection, target):
    if not _published_offer(connection, target.id):
        return
    changed = {name for name, attribute in inspect(target).attrs.items() if attribute.history.has_changes()}
    if target.status == "retired" and changed <= {"status", "updated_at"}:
        return
    raise ValueError("Published entitlement offer versions are immutable.")


@event.listens_for(EntitlementOfferGrant, "before_insert")
@event.listens_for(EntitlementOfferGrant, "before_update")
@event.listens_for(EntitlementOfferGrant, "before_delete")
def _protect_published_offer_grant(mapper, connection, target):
    if _published_offer(connection, target.offer_version_id):
        raise ValueError("Grants on published entitlement offer versions are immutable.")