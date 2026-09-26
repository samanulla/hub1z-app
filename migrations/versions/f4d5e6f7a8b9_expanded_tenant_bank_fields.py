"""expanded tenant bank account fields

Revision ID: f4d5e6f7a8b9
Revises: f3c4d5e6f7a8
"""
from alembic import op
import sqlalchemy as sa


revision = "f4d5e6f7a8b9"
down_revision = "f3c4d5e6f7a8"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("tenants") as batch_op:
        batch_op.add_column(sa.Column("payment_bank_account_name", sa.String(length=200), nullable=True))
        batch_op.add_column(sa.Column("payment_bank_account_number", sa.String(length=60), nullable=True))
        batch_op.add_column(sa.Column("payment_bank_account_type", sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column("payment_bank_ifsc_or_routing", sa.String(length=30), nullable=True))


def downgrade():
    with op.batch_alter_table("tenants") as batch_op:
        batch_op.drop_column("payment_bank_ifsc_or_routing")
        batch_op.drop_column("payment_bank_account_type")
        batch_op.drop_column("payment_bank_account_number")
        batch_op.drop_column("payment_bank_account_name")
