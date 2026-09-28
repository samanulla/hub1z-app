"""complete operator plan contract

Revision ID: ff4c5d6e7f8a
Revises: fe3b4c5d6e7f
"""
from alembic import op
import sqlalchemy as sa


revision = "ff4c5d6e7f8a"
down_revision = "fe3b4c5d6e7f"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("pricing_plans") as batch_op:
        batch_op.add_column(sa.Column("additional_seats_allowed", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column("meeting_room_access_included", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column("meeting_credit_unit", sa.String(20), nullable=True))
        batch_op.add_column(sa.Column("meeting_credits_rollover", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column("meeting_room_overage_allowed", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column("deposit_required", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column("deposit_calculation", sa.String(30), nullable=True))
        batch_op.add_column(sa.Column("deposit_value", sa.Numeric(10, 2), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("deposit_refundable", sa.Boolean(), nullable=False, server_default=sa.true()))
        batch_op.add_column(sa.Column("tax_code", sa.String(30), nullable=True))
        batch_op.add_column(sa.Column("price_includes_tax", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column("currency", sa.String(3), nullable=False, server_default="INR"))
        batch_op.add_column(sa.Column("effective_from", sa.Date(), nullable=True))
        batch_op.add_column(sa.Column("effective_until", sa.Date(), nullable=True))
        batch_op.add_column(sa.Column("version", sa.Integer(), nullable=False, server_default="1"))
    with op.batch_alter_table("subscriptions") as batch_op:
        batch_op.add_column(sa.Column("pricing_snapshot", sa.Text(), nullable=True))


def downgrade():
    pass