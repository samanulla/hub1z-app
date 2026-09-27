"""expand hub1 SaaS tiers

Revision ID: fae1f2a3b4c5
Revises: f9d0e1f2a3b4
"""
from alembic import op
import sqlalchemy as sa


revision = "fae1f2a3b4c5"
down_revision = "f9d0e1f2a3b4"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    tier_status = sa.Enum("DRAFT", "ACTIVE", "INACTIVE", name="tierstatus")
    tier_status.create(bind, checkfirst=True)
    with op.batch_alter_table("pricing_tiers") as batch_op:
        batch_op.add_column(sa.Column("annual_price", sa.Numeric(10, 2), nullable=True))
        batch_op.add_column(sa.Column("annual_discount", sa.Numeric(10, 2), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("status", tier_status, nullable=False, server_default="ACTIVE"))
        batch_op.add_column(sa.Column("included_active_contracted_seats", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("additional_seat_rate", sa.Numeric(10, 2), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("additional_location_rate", sa.Numeric(10, 2), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("included_features", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("premium_modules", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("trial_period_days", sa.Integer(), nullable=False, server_default="0"))
    op.create_table(
        "operator_subscriptions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("tier_id", sa.Integer(), nullable=True),
        sa.Column("billing_cycle", sa.String(length=10), nullable=False, server_default="monthly"),
        sa.Column("negotiated_base_price", sa.Numeric(10, 2), nullable=True),
        sa.Column("additional_free_seats", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("additional_free_locations", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("custom_additional_seat_rate", sa.Numeric(10, 2), nullable=True),
        sa.Column("custom_additional_location_rate", sa.Numeric(10, 2), nullable=True),
        sa.Column("discount_amount", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column("premium_modules_amount", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column("implementation_charge", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column("tax_rate", sa.Numeric(5, 2), nullable=False, server_default="0"),
        sa.Column("negotiated_features", sa.Text(), nullable=True),
        sa.Column("contract_start_date", sa.Date(), nullable=True),
        sa.Column("contract_end_date", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tier_id"], ["pricing_tiers.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id"),
    )
    op.execute("""
        UPDATE pricing_tiers
        SET included_active_contracted_seats = CASE key
            WHEN 'starter' THEN 50
            WHEN 'growth' THEN 150
            ELSE max_seats
        END,
        annual_price = CASE WHEN monthly_price IS NOT NULL THEN monthly_price * 12 ELSE NULL END,
        status = 'ACTIVE'
    """)
    op.execute("UPDATE pricing_tiers SET max_private_offices = NULL, max_rooms = NULL")


def downgrade():
    op.drop_table("operator_subscriptions")
    with op.batch_alter_table("pricing_tiers") as batch_op:
        batch_op.drop_column("trial_period_days")
        batch_op.drop_column("premium_modules")
        batch_op.drop_column("included_features")
        batch_op.drop_column("additional_location_rate")
        batch_op.drop_column("additional_seat_rate")
        batch_op.drop_column("included_active_contracted_seats")
        batch_op.drop_column("status")
        batch_op.drop_column("annual_discount")
        batch_op.drop_column("annual_price")