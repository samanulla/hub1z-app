"""Add typed, versioned entitlement records and usage reservations.

Revision ID: fc72b8d19a04
Revises: f9b3c7d1a620
"""
from alembic import op
import sqlalchemy as sa


revision = "fc72b8d19a04"
down_revision = "f9b3c7d1a620"
branch_labels = None
depends_on = None


def _timestamps():
    return (sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False))


def upgrade():
    op.create_table(
        "entitlement_definitions",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("key", sa.String(80), nullable=False),
        sa.Column("name", sa.String(160), nullable=False), sa.Column("value_type", sa.String(20), nullable=False),
        sa.Column("unit", sa.String(40)), sa.Column("measurement", sa.String(20), nullable=False),
        sa.Column("built", sa.Boolean(), nullable=False), sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("protected_actions", sa.JSON(), nullable=False), *_timestamps())
    op.create_index("ix_entitlement_definitions_key", "entitlement_definitions", ["key"], unique=True)

    op.create_table(
        "entitlement_offer_versions",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("offer_key", sa.String(80), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False), sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False), sa.Column("name", sa.String(120), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False), sa.Column("billing_period", sa.String(20)),
        sa.Column("base_price", sa.Numeric(12, 2)), sa.Column("effective_from", sa.DateTime()),
        sa.Column("effective_to", sa.DateTime()), sa.Column("publicly_listed", sa.Boolean(), nullable=False),
        sa.Column("terms_snapshot", sa.JSON(), nullable=False), *_timestamps(),
        sa.UniqueConstraint("offer_key", "version", name="uq_entitlement_offer_version"))
    op.create_index("ix_entitlement_offer_versions_offer_key", "entitlement_offer_versions", ["offer_key"])

    op.create_table(
        "entitlement_offer_grants",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("offer_version_id", sa.Integer(), sa.ForeignKey("entitlement_offer_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("entitlement_key", sa.String(80), sa.ForeignKey("entitlement_definitions.key", ondelete="RESTRICT"), nullable=False),
        sa.Column("scope_key", sa.String(120), nullable=False), sa.Column("boolean_value", sa.Boolean()),
        sa.Column("numeric_value", sa.Numeric(18, 6)), sa.Column("unlimited", sa.Boolean(), nullable=False),
        sa.Column("combine_rule", sa.String(12), nullable=False), sa.Column("period_seconds", sa.Integer()), *_timestamps(),
        sa.UniqueConstraint("offer_version_id", "entitlement_key", "scope_key", name="uq_offer_entitlement_scope"))
    op.create_index("ix_entitlement_offer_grants_offer_version_id", "entitlement_offer_grants", ["offer_version_id"])
    op.create_index("ix_entitlement_offer_grants_entitlement_key", "entitlement_offer_grants", ["entitlement_key"])

    op.create_table(
        "tenant_plan_bindings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("operator_id", sa.Integer(), sa.ForeignKey("operators.id", ondelete="CASCADE"), nullable=False),
        sa.Column("offer_version_id", sa.Integer(), sa.ForeignKey("entitlement_offer_versions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("effective_from", sa.DateTime(), nullable=False), sa.Column("effective_to", sa.DateTime()),
        sa.Column("state", sa.String(20), nullable=False), sa.Column("provenance", sa.String(30), nullable=False),
        sa.Column("legacy_snapshot", sa.JSON()), sa.Column("contract_reference", sa.String(160)), *_timestamps())
    op.create_index("ix_tenant_plan_bindings_operator_id", "tenant_plan_bindings", ["operator_id"])
    op.create_index("ix_tenant_plan_bindings_offer_version_id", "tenant_plan_bindings", ["offer_version_id"])
    op.create_index("ix_tenant_binding_effective", "tenant_plan_bindings", ["operator_id", "effective_from", "effective_to"])

    op.create_table(
        "tenant_entitlement_grants",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("operator_id", sa.Integer(), sa.ForeignKey("operators.id", ondelete="CASCADE"), nullable=False),
        sa.Column("entitlement_key", sa.String(80), sa.ForeignKey("entitlement_definitions.key", ondelete="RESTRICT"), nullable=False),
        sa.Column("source", sa.String(20), nullable=False), sa.Column("grant_mode", sa.String(12), nullable=False),
        sa.Column("scope_key", sa.String(120), nullable=False), sa.Column("boolean_value", sa.Boolean()),
        sa.Column("numeric_value", sa.Numeric(18, 6)), sa.Column("unlimited", sa.Boolean(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False), sa.Column("effective_from", sa.DateTime(), nullable=False),
        sa.Column("effective_to", sa.DateTime()), sa.Column("reason", sa.Text()),
        sa.Column("source_reference", sa.String(160)),
        sa.Column("approved_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")), *_timestamps())
    op.create_index("ix_tenant_entitlement_grants_operator_id", "tenant_entitlement_grants", ["operator_id"])
    op.create_index("ix_tenant_entitlement_grants_entitlement_key", "tenant_entitlement_grants", ["entitlement_key"])

    op.create_table(
        "entitlement_usage_buckets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("operator_id", sa.Integer(), sa.ForeignKey("operators.id", ondelete="CASCADE"), nullable=False),
        sa.Column("entitlement_key", sa.String(80), sa.ForeignKey("entitlement_definitions.key", ondelete="RESTRICT"), nullable=False),
        sa.Column("scope_key", sa.String(120), nullable=False), sa.Column("period_start", sa.DateTime(), nullable=False),
        sa.Column("period_end", sa.DateTime(), nullable=False), sa.Column("committed", sa.Numeric(18, 6), nullable=False),
        sa.Column("reserved", sa.Numeric(18, 6), nullable=False), sa.Column("revision", sa.Integer(), nullable=False), *_timestamps(),
        sa.UniqueConstraint("operator_id", "entitlement_key", "scope_key", "period_start",
                            name="uq_entitlement_usage_bucket"))
    op.create_index("ix_entitlement_usage_buckets_operator_id", "entitlement_usage_buckets", ["operator_id"])
    op.create_index("ix_entitlement_usage_buckets_entitlement_key", "entitlement_usage_buckets", ["entitlement_key"])

    op.create_table(
        "entitlement_usage_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("operator_id", sa.Integer(), sa.ForeignKey("operators.id", ondelete="CASCADE"), nullable=False),
        sa.Column("entitlement_key", sa.String(80), sa.ForeignKey("entitlement_definitions.key", ondelete="RESTRICT"), nullable=False),
        sa.Column("scope_key", sa.String(120), nullable=False), sa.Column("operation_id", sa.String(120)),
        sa.Column("idempotency_key", sa.String(160), nullable=False), sa.Column("event_kind", sa.String(20), nullable=False),
        sa.Column("status", sa.String(12), nullable=False), sa.Column("quantity", sa.Numeric(18, 6), nullable=False),
        sa.Column("meter_revision", sa.Integer(), nullable=False),
        sa.Column("period_start", sa.DateTime(), nullable=False), sa.Column("period_end", sa.DateTime(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(), nullable=False), sa.Column("reservation_expires_at", sa.DateTime()),
        sa.Column("provider_event_id", sa.String(160)), sa.Column("provider_cost", sa.Numeric(12, 4)),
        sa.Column("provider_currency", sa.String(3)), *_timestamps(),
        sa.UniqueConstraint("operator_id", "entitlement_key", "idempotency_key",
                            name="uq_entitlement_usage_idempotency"))
    op.create_index("ix_entitlement_usage_events_operator_id", "entitlement_usage_events", ["operator_id"])
    op.create_index("ix_entitlement_usage_events_entitlement_key", "entitlement_usage_events", ["entitlement_key"])


def downgrade():
    for table in ("entitlement_usage_events", "entitlement_usage_buckets", "tenant_entitlement_grants",
                  "tenant_plan_bindings", "entitlement_offer_grants", "entitlement_offer_versions",
                  "entitlement_definitions"):
        op.drop_table(table)
