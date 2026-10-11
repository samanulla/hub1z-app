"""Executive office plan type; managed office plans become private office plans

Revision ID: f1a8d3c5b207
Revises: e2a7c5d94f16
Create Date: 2026-10-11 09:00:00.000000

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = 'f1a8d3c5b207'
down_revision = 'e2a7c5d94f16'
branch_labels = None
depends_on = None


def upgrade():
    if op.get_bind().dialect.name == 'postgresql':
        op.execute("ALTER TYPE plantype ADD VALUE IF NOT EXISTS 'EXECUTIVE_OFFICE'")
    op.execute("UPDATE pricing_plans SET plan_type = 'PRIVATE_OFFICE' WHERE plan_type = 'MANAGED_OFFICE'")


def downgrade():
    # The enum values stay: Postgres cannot drop one, and plans converted from managed office
    # are indistinguishable from private office plans afterwards.
    pass
