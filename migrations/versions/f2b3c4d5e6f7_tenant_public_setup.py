"""tenant regional signup and public payment instructions

Revision ID: f2b3c4d5e6f7
Revises: f1a2b3c4d5e6
"""
from alembic import op
import sqlalchemy as sa


revision = "f2b3c4d5e6f7"
down_revision = "f1a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("tenants") as batch_op:
        batch_op.add_column(sa.Column("country_code", sa.String(length=2), nullable=True))
        batch_op.add_column(sa.Column("payment_instructions", sa.String(length=500), nullable=True))
        batch_op.add_column(sa.Column("payment_upi_id", sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column("payment_gpay", sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column("payment_bank_details", sa.String(length=500), nullable=True))
    op.execute("UPDATE tenants SET country_code = 'IN' WHERE country_code IS NULL")
    with op.batch_alter_table("tenants") as batch_op:
        batch_op.alter_column("country_code", existing_type=sa.String(length=2), nullable=False,
                              server_default="IN")


def downgrade():
    with op.batch_alter_table("tenants") as batch_op:
        batch_op.drop_column("payment_bank_details")
        batch_op.drop_column("payment_gpay")
        batch_op.drop_column("payment_upi_id")
        batch_op.drop_column("payment_instructions")
        batch_op.drop_column("country_code")