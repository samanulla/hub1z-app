"""operator plan final conditions

Revision ID: 001a2b3c4d5e
Revises: ff4c5d6e7f8a
"""
from alembic import op
import sqlalchemy as sa


revision = "001a2b3c4d5e"
down_revision = "ff4c5d6e7f8a"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("pricing_plans") as batch_op:
        batch_op.add_column(sa.Column("maximum_additional_seats", sa.Integer(), nullable=True))


def downgrade():
    with op.batch_alter_table("pricing_plans") as batch_op:
        batch_op.drop_column("maximum_additional_seats")