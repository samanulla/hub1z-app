"""tenant hold status

Adds TenantStatus.HOLD — a soft, reversible pause distinct from SUSPENDED
(hard stop, Owner-only). Platform Managers with the 'tenants' feature can
place/release a Hold; only the Platform Super Admin can Suspend/reactivate
from Suspended.

Revision ID: c5d8e0f2a4b6
Revises: a3f9d7c1e2b4
Create Date: 2026-09-22 00:00:00.000000

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = 'c5d8e0f2a4b6'
down_revision = 'a3f9d7c1e2b4'
branch_labels = None
depends_on = None


def upgrade():
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE tenantstatus ADD VALUE IF NOT EXISTS 'HOLD'")


def downgrade():
    # Removing enum values in Postgres requires recreating the type. No-op here.
    pass
