"""refine Hub1 tier contracts

Revision ID: fb0e1f2a3b4c
Revises: fae1f2a3b4c5
"""
from alembic import op
import sqlalchemy as sa


revision = "fb0e1f2a3b4c"
down_revision = "fae1f2a3b4c5"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    policy = sa.Enum("ALLOW_AND_CHARGE", "BLOCK_ADDITIONAL_USAGE", "REQUIRE_PLAN_UPGRADE", "CUSTOM_APPROVAL", name="overagepolicy")
    policy.create(bind, checkfirst=True)
    with op.batch_alter_table("pricing_tiers") as batch_op:
        batch_op.add_column(sa.Column("seat_overage_policy", policy, nullable=False, server_default="ALLOW_AND_CHARGE"))
        batch_op.add_column(sa.Column("location_overage_policy", policy, nullable=False, server_default="REQUIRE_PLAN_UPGRADE"))
        batch_op.add_column(sa.Column("effective_from", sa.Date(), nullable=True))
        batch_op.add_column(sa.Column("effective_to", sa.Date(), nullable=True))
    with op.batch_alter_table("operator_subscriptions") as batch_op:
        batch_op.add_column(sa.Column("pricing_snapshot", sa.Text(), nullable=True))
    op.create_table(
        "platform_modules",
        sa.Column("id", sa.Integer(), nullable=False), sa.Column("code", sa.String(50), nullable=False),
        sa.Column("name", sa.String(120), nullable=False), sa.Column("monthly_price", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False), sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("code"),
    )
    op.create_table(
        "tier_modules", sa.Column("tier_id", sa.Integer(), nullable=False), sa.Column("module_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["tier_id"], ["pricing_tiers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["module_id"], ["platform_modules.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("tier_id", "module_id"),
    )
    op.create_table(
        "operator_usage_snapshots",
        sa.Column("id", sa.Integer(), nullable=False), sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("recorded_on", sa.Date(), nullable=False), sa.Column("active_contracted_seats", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False), sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"), sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_operator_usage_snapshots_tenant_id", "operator_usage_snapshots", ["tenant_id"])
    op.create_index("ix_operator_usage_snapshots_recorded_on", "operator_usage_snapshots", ["recorded_on"])


def downgrade():
    op.drop_table("operator_usage_snapshots")
    op.drop_table("tier_modules")
    op.drop_table("platform_modules")
    with op.batch_alter_table("operator_subscriptions") as batch_op:
        batch_op.drop_column("pricing_snapshot")
    with op.batch_alter_table("pricing_tiers") as batch_op:
        batch_op.drop_column("effective_to")
        batch_op.drop_column("effective_from")
        batch_op.drop_column("location_overage_policy")
        batch_op.drop_column("seat_overage_policy")