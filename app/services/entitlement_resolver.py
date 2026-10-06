"""Central entitlement resolution, shadow comparison, and usage reservations."""
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
import logging

from sqlalchemy import select

from ..extensions import db
from ..models import (EntitlementDefinition, EntitlementOfferGrant, EntitlementOfferVersion,
                      EntitlementUsageBucket, EntitlementUsageEvent, Operator, PlatformModule,
                      OperatorSubscription, TenantEntitlementGrant, TenantPlanBinding)
from .catalog import AVAILABLE, BETA, BY_CODE

logger = logging.getLogger(__name__)

LEGACY_ALLOWANCE_KEYS = {
    "location_count": "included_locations",
    "contracted_seats": "included_active_contracted_seats",
    "staff_accounts": "max_staff_users",
    "open_manual_leads": "max_open_leads",
    "document_storage_bytes": "storage_mb",
}


@dataclass(frozen=True)
class EntitlementDecision:
    allowed: bool
    requested_allowed: bool
    key: str
    action: str
    source: str
    reason: str
    limit: Decimal | None = None
    binding_id: int | None = None
    offer_version: int | None = None
    shadow_match: bool | None = None
    reservation_id: int | None = None


class EntitlementConfigurationError(ValueError):
    pass


def _as_decimal(value):
    return Decimal(str(value)) if value is not None else None


def _legacy_decision(operator, key, action, quantity=Decimal(0)):
    from .entitlements import legacy_has_feature, plan_terms

    entry = BY_CODE.get(key)
    if entry and entry.value_type.value == "boolean":
        return legacy_has_feature(operator, key), None
    terms = plan_terms(operator)
    term_key = LEGACY_ALLOWANCE_KEYS.get(key)
    if term_key is None:
        return False, None
    value = terms.get(term_key)
    if key == "document_storage_bytes":
        from .entitlements import storage_limit_mb
        value = storage_limit_mb(operator)
        value = int(value) * 1024 * 1024 if value is not None else None
    else:
        subscription = OperatorSubscription.query.filter_by(operator_id=operator.id).first()
        if subscription and subscription.scheduled_terms and subscription.scheduled_terms.get(term_key) is not None:
            pending = subscription.scheduled_terms[term_key]
            value = min(value, pending) if value is not None else pending
    if terms.get("all_features") and key != "document_storage_bytes":
        value = None
    limit = _as_decimal(value)
    return limit is None or Decimal(str(quantity or 0)) <= limit, limit


def _active_binding(operator_id, now):
    bindings = (TenantPlanBinding.query.filter_by(operator_id=operator_id, state="active")
                .filter(TenantPlanBinding.effective_from <= now)
                .filter((TenantPlanBinding.effective_to.is_(None)) | (TenantPlanBinding.effective_to > now))
                .order_by(TenantPlanBinding.effective_from.desc(), TenantPlanBinding.id.desc()).all())
    if len(bindings) > 1:
        raise EntitlementConfigurationError("More than one base entitlement binding is effective.")
    return bindings[0] if bindings else None


def _new_decision(operator_id, key, action, scope, now, binding):
    definition = EntitlementDefinition.query.filter_by(key=key).first()
    if definition is None:
        return False, None, "unregistered"
    if action in (definition.protected_actions or []):
        return True, None, "protected_action"
    if not definition.built:
        return False, None, "not_built"
    module = PlatformModule.query.filter_by(code=key).first()
    if module and (not module.is_active or module.availability not in (AVAILABLE, BETA)):
        return False, None, "unavailable"

    offer = db.session.get(EntitlementOfferVersion, binding.offer_version_id)
    if offer is None or offer.status not in ("published", "retired"):
        return False, None, "invalid_offer"

    offer_grants = EntitlementOfferGrant.query.filter_by(
        offer_version_id=offer.id, entitlement_key=key).filter(
            EntitlementOfferGrant.scope_key.in_(("*", scope))).all()
    tenant_grants = TenantEntitlementGrant.query.filter_by(
        operator_id=operator_id, entitlement_key=key).filter(
            TenantEntitlementGrant.scope_key.in_(("*", scope)),
            TenantEntitlementGrant.effective_from <= now).filter(
                (TenantEntitlementGrant.effective_to.is_(None)) |
                (TenantEntitlementGrant.effective_to > now)).all()

    is_boolean = definition.value_type == "boolean"
    enabled = False
    numeric_values = []
    unlimited = False
    sources = []
    for grant in offer_grants:
        if is_boolean:
            enabled = enabled or grant.boolean_value is True
        elif grant.unlimited:
            unlimited = True
        elif grant.numeric_value is not None:
            numeric_values.append((_as_decimal(grant.numeric_value), grant.combine_rule))
        sources.append("offer")

    overrides = [grant for grant in tenant_grants if grant.grant_mode in ("set", "deny")]
    if overrides:
        highest = max(grant.priority for grant in overrides)
        winners = [grant for grant in overrides if grant.priority == highest]
        signatures = {(grant.grant_mode, grant.boolean_value, grant.numeric_value, grant.unlimited)
                      for grant in winners}
        if len(signatures) > 1:
            raise EntitlementConfigurationError("Conflicting effective entitlement overrides.")
        override = winners[0]
        if override.grant_mode == "deny":
            return False, Decimal(0), "override"
        elif is_boolean:
            enabled = override.boolean_value is True
        else:
            unlimited = override.unlimited
            numeric_values = [] if unlimited else [(_as_decimal(override.numeric_value), "set")]
        sources.append("override")

    if not overrides:
        for grant in tenant_grants:
            if grant.grant_mode in ("set", "deny"):
                continue
            if is_boolean:
                enabled = enabled or (grant.grant_mode == "enable" and grant.boolean_value is True)
            elif grant.unlimited:
                unlimited = True
            elif grant.numeric_value is not None:
                rule = "add" if grant.grant_mode == "add" else "max"
                numeric_values.append((_as_decimal(grant.numeric_value), rule))
            sources.append(grant.source)

    if is_boolean:
        return enabled, None, "+".join(dict.fromkeys(sources)) or "ungranted"
    if unlimited:
        return True, None, "+".join(dict.fromkeys(sources)) or "unlimited"
    additive = sum((value for value, rule in numeric_values if rule in ("add", "set")), Decimal(0))
    maximum = max((value for value, rule in numeric_values if rule == "max"), default=Decimal(0))
    limit = additive + maximum
    return True, limit, "+".join(dict.fromkeys(sources)) or "ungranted"


def check_entitlement(operator_id, key, action="use", quantity=Decimal(0), scope="*", now=None,
                      reserve=False, idempotency_key=None, period_start=None, period_end=None):
    """Resolve a decision; shadow mode returns legacy access until explicitly enabled."""
    now = now or datetime.utcnow()
    operator = (operator_id if isinstance(operator_id, Operator) else
                Operator.query.execution_options(skip_operator_filter=True).filter_by(id=operator_id).first())
    if operator is None:
        return EntitlementDecision(False, False, key, action, "missing_tenant", "unknown_tenant")

    definition = EntitlementDefinition.query.filter_by(key=key).first()
    protected = bool(definition and action in (definition.protected_actions or []))
    if protected:
        return EntitlementDecision(True, True, key, action, "protected_action", "protected_action")
    legacy_allowed, legacy_limit = _legacy_decision(operator, key, action, quantity)
    binding = _active_binding(operator.id, now)
    if binding is None:
        return EntitlementDecision(legacy_allowed, legacy_allowed, key, action, "legacy",
                                   "legacy_compatibility", legacy_limit)

    proposed, limit, source = _new_decision(operator.id, key, action, scope, now, binding)
    if limit is not None and quantity:
        proposed = proposed and Decimal(str(quantity)) <= limit
    match = proposed == legacy_allowed
    if not match:
        logger.warning("entitlement_shadow_mismatch operator_id=%s key=%s action=%s legacy=%s proposed=%s",
                       operator.id, key, action, legacy_allowed, proposed)

    from flask import current_app, has_app_context
    enforcing = has_app_context() and current_app.config.get("ENTITLEMENTS_ENFORCEMENT_ENABLED", False)
    allowed = proposed if enforcing else legacy_allowed
    reservation_id = None
    if reserve and not enforcing:
        raise ValueError("Usage reservations are disabled while entitlement enforcement is in shadow mode.")
    if reserve and allowed:
        if limit is None and definition and definition.value_type != "usage":
            raise ValueError("Reservations require a metered entitlement.")
        if not idempotency_key or period_start is None or period_end is None:
            raise ValueError("Reservations require an idempotency key and period boundaries.")
        reservation_id = reserve_usage(operator.id, key, quantity, scope, period_start, period_end,
                                       limit, idempotency_key, now)
    return EntitlementDecision(allowed, proposed, key, action, source,
                               "allowed" if allowed else "not_entitled", limit, binding.id,
                               binding.offer_version_id, match, reservation_id)


def _insert_bucket(operator_id, key, scope, start, end):
    table = EntitlementUsageBucket.__table__
    values = {"operator_id": operator_id, "entitlement_key": key, "scope_key": scope,
              "period_start": start, "period_end": end, "committed": 0, "reserved": 0, "revision": 1}
    dialect = db.session.get_bind().dialect.name
    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
        statement = insert(table).values(**values).on_conflict_do_nothing(
            constraint="uq_entitlement_usage_bucket")
        db.session.execute(statement)
    elif dialect == "sqlite":
        from sqlalchemy.dialects.sqlite import insert
        statement = insert(table).values(**values).on_conflict_do_nothing(
            index_elements=["operator_id", "entitlement_key", "scope_key", "period_start"])
        db.session.execute(statement)
    else:
        existing = EntitlementUsageBucket.query.filter_by(
            operator_id=operator_id, entitlement_key=key, scope_key=scope, period_start=start).first()
        if existing is None:
            db.session.add(EntitlementUsageBucket(**values))
            db.session.flush()


def _reuse_reservation(existing, quantity, scope, period_start, period_end):
    if existing.status == "released":
        raise ValueError("A released reservation cannot be reused.")
    if (existing.scope_key != scope or Decimal(existing.quantity) != quantity or
            existing.period_start != period_start or existing.period_end != period_end):
        raise ValueError("Idempotency key was already used for a different operation.")
    return existing.id


def reserve_usage(operator_id, key, quantity, scope, period_start, period_end, limit,
                  idempotency_key, now=None):
    """Atomically reserve against a tenant/metric/scope/period bucket."""
    quantity = Decimal(str(quantity))
    if quantity <= 0:
        raise ValueError("Reservation quantity must be positive.")
    definition = EntitlementDefinition.query.filter_by(key=key).first()
    if definition is None or not definition.built or definition.value_type not in ("allowance", "usage"):
        raise ValueError("Only built numeric entitlements can reserve usage.")
    existing = EntitlementUsageEvent.query.filter_by(
        operator_id=operator_id, entitlement_key=key, idempotency_key=idempotency_key).first()
    if existing:
        return _reuse_reservation(existing, quantity, scope, period_start, period_end)

    _insert_bucket(operator_id, key, scope, period_start, period_end)
    bucket = (EntitlementUsageBucket.query.filter_by(
        operator_id=operator_id, entitlement_key=key, scope_key=scope, period_start=period_start)
        .with_for_update().one())
    existing = EntitlementUsageEvent.query.filter_by(
        operator_id=operator_id, entitlement_key=key, idempotency_key=idempotency_key).first()
    if existing:
        return _reuse_reservation(existing, quantity, scope, period_start, period_end)
    used = Decimal(bucket.committed) + Decimal(bucket.reserved)
    if limit is not None and used + quantity > Decimal(str(limit)):
        raise ValueError("Usage allowance exhausted.")
    bucket.reserved = used - Decimal(bucket.committed) + quantity
    event = EntitlementUsageEvent(
        operator_id=operator_id, entitlement_key=key, scope_key=scope,
        operation_id=idempotency_key, idempotency_key=idempotency_key,
        event_kind="reservation", status="reserved", quantity=quantity, meter_revision=definition.revision,
        period_start=period_start, period_end=period_end,
        reservation_expires_at=None, occurred_at=now or datetime.utcnow())
    db.session.add(event)
    db.session.flush()
    return event.id


def settle_usage_reservation(operator_id, event_id, commit=True):
    event = (EntitlementUsageEvent.query.filter_by(
        id=event_id, operator_id=operator_id, status="reserved").with_for_update().first())
    if event is None:
        existing = EntitlementUsageEvent.query.filter_by(id=event_id, operator_id=operator_id).first()
        target = "committed" if commit else "released"
        if existing and existing.status == target:
            return existing
        if existing is None:
            raise ValueError("Unknown usage reservation for this tenant.")
        raise ValueError("Usage reservation is no longer pending.")
    bucket = (EntitlementUsageBucket.query.filter_by(
        operator_id=operator_id, entitlement_key=event.entitlement_key, scope_key=event.scope_key,
        period_start=event.period_start).with_for_update().one())
    quantity = Decimal(event.quantity)
    bucket.reserved = max(Decimal(bucket.reserved) - quantity, Decimal(0))
    if commit:
        bucket.committed = Decimal(bucket.committed) + quantity
        event.status = "committed"
    else:
        event.status = "released"
    db.session.flush()
    return event