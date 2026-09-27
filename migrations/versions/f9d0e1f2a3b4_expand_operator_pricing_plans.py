"""expand operator pricing plans

Revision ID: f9d0e1f2a3b4
Revises: f8c9d0e1f2a3
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "f9d0e1f2a3b4"
down_revision = "f8c9d0e1f2a3"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    plan_scope = sa.Enum("INDIVIDUAL", "COMPANY", name="planscope")
    billing_unit = sa.Enum("PER_PERSON", "PER_SEAT", "PER_OFFICE", "PER_DAY", "FLAT_FEE", name="billingunit")
    location_scope = sa.Enum("ONE", "MULTIPLE", "ALL", name="locationscope")
    plan_status = sa.Enum("DRAFT", "ACTIVE", "INACTIVE", name="planstatus")
    plan_scope.create(bind, checkfirst=True)
    billing_unit.create(bind, checkfirst=True)
    location_scope.create(bind, checkfirst=True)
    plan_status.create(bind, checkfirst=True)
    if bind.dialect.name == "postgresql":
        op.execute("ALTER TYPE plantype ADD VALUE IF NOT EXISTS 'MANAGED_OFFICE'")
        op.execute("ALTER TYPE billingcycle ADD VALUE IF NOT EXISTS 'WEEKLY'")
    with op.batch_alter_table("pricing_plans") as batch_op:
        batch_op.add_column(sa.Column("scope", sa.Enum("INDIVIDUAL", "COMPANY", name="planscope"), nullable=False, server_default="INDIVIDUAL"))
        batch_op.add_column(sa.Column("billing_unit", sa.Enum("PER_PERSON", "PER_SEAT", "PER_OFFICE", "PER_DAY", "FLAT_FEE", name="billingunit"), nullable=False, server_default="PER_PERSON"))
        batch_op.add_column(sa.Column("included_seat_quantity", sa.Integer(), nullable=False, server_default="1"))
        batch_op.add_column(sa.Column("additional_seat_rate", sa.Numeric(10, 2), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("meeting_room_overage_rate", sa.Numeric(10, 2), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("location_scope", sa.Enum("ONE", "MULTIPLE", "ALL", name="locationscope"), nullable=False, server_default="ALL"))
        batch_op.add_column(sa.Column("minimum_contract_months", sa.Integer(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("refundable_deposit", sa.Numeric(10, 2), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("tax_applicable", sa.Boolean(), nullable=False, server_default=sa.true()))
        batch_op.add_column(sa.Column("status", sa.Enum("DRAFT", "ACTIVE", "INACTIVE", name="planstatus"), nullable=False, server_default="ACTIVE"))
        batch_op.add_column(sa.Column("office_capacity", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("company_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key("fk_pricing_plans_company_id", "companies", ["company_id"], ["id"], ondelete="CASCADE")
        batch_op.create_index("ix_pricing_plans_company_id", ["company_id"])
    op.create_table(
        "pricing_plan_locations",
        sa.Column("plan_id", sa.Integer(), nullable=False),
        sa.Column("location_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["plan_id"], ["pricing_plans.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["location_id"], ["locations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("plan_id", "location_id"),
    )
    op.create_table(
        "plan_addons",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("plan_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("price", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column("billing_cycle", postgresql.ENUM("DAILY", "WEEKLY", "MONTHLY", "QUARTERLY", "ANNUAL", name="billingcycle", create_type=False), nullable=False, server_default="MONTHLY"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["plan_id"], ["pricing_plans.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_plan_addons_plan_id", "plan_addons", ["plan_id"])


def downgrade():
    op.drop_table("plan_addons")
    op.drop_table("pricing_plan_locations")
    with op.batch_alter_table("pricing_plans") as batch_op:
        batch_op.drop_index("ix_pricing_plans_company_id")
        batch_op.drop_constraint("fk_pricing_plans_company_id", type_="foreignkey")
        batch_op.drop_column("company_id")
        batch_op.drop_column("office_capacity")
        batch_op.drop_column("status")
        batch_op.drop_column("tax_applicable")
        batch_op.drop_column("refundable_deposit")
        batch_op.drop_column("minimum_contract_months")
        batch_op.drop_column("location_scope")
        batch_op.drop_column("meeting_room_overage_rate")
        batch_op.drop_column("additional_seat_rate")
        batch_op.drop_column("included_seat_quantity")
        batch_op.drop_column("billing_unit")
        batch_op.drop_column("scope")