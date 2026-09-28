"""refine operator plan conditions

Revision ID: fd2a3b4c5d6e
Revises: fc1f2a3b4c5d
"""
from alembic import op


revision = "fd2a3b4c5d6e"
down_revision = "fc1f2a3b4c5d"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        with op.get_context().autocommit_block():
            op.execute("ALTER TYPE planscope ADD VALUE IF NOT EXISTS 'COMPANY_STANDARD'")
            op.execute("ALTER TYPE planscope ADD VALUE IF NOT EXISTS 'COMPANY_CUSTOM'")
            op.execute("ALTER TYPE billingunit ADD VALUE IF NOT EXISTS 'PER_DAY_PASS'")
            op.execute("ALTER TYPE billingunit ADD VALUE IF NOT EXISTS 'PER_PERSON_DAY'")
        op.execute("UPDATE pricing_plans SET scope = 'COMPANY_STANDARD' WHERE scope = 'COMPANY'")


def downgrade():
    pass