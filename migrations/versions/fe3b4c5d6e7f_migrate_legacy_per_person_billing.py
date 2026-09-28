"""migrate legacy per person billing unit

Revision ID: fe3b4c5d6e7f
Revises: fd2a3b4c5d6e
"""
from alembic import op


revision = "fe3b4c5d6e7f"
down_revision = "fd2a3b4c5d6e"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("UPDATE pricing_plans SET billing_unit = 'PER_PERSON_DAY' WHERE billing_unit = 'PER_PERSON'")


def downgrade():
    op.execute("UPDATE pricing_plans SET billing_unit = 'PER_PERSON' WHERE billing_unit = 'PER_PERSON_DAY'")