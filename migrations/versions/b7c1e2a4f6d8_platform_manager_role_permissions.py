"""platform manager role + permissions

Revision ID: b7c1e2a4f6d8
Revises: 468c0a7134a7
Create Date: 2026-09-19 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b7c1e2a4f6d8'
down_revision = '468c0a7134a7'
branch_labels = None
depends_on = None


def upgrade():
    # Postgres requires ALTER TYPE ... ADD VALUE to run outside a transaction.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE userrole ADD VALUE IF NOT EXISTS 'PLATFORM_MANAGER'")
    op.add_column('users', sa.Column('platform_permissions', sa.Text(), nullable=True))


def downgrade():
    op.drop_column('users', 'platform_permissions')
    # Removing enum values in Postgres requires recreating the type. No-op here.
