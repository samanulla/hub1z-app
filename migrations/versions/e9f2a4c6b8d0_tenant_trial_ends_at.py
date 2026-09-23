"""tenant trial_ends_at

Self-serve tenant sign-up gets a time-boxed trial (see auth.register_tenant);
staff-provisioned/invited tenants leave this null (no forced deadline).

Revision ID: e9f2a4c6b8d0
Revises: d7e1f3a5b8c0
Create Date: 2026-09-23 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e9f2a4c6b8d0'
down_revision = 'd7e1f3a5b8c0'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('tenants', sa.Column('trial_ends_at', sa.DateTime(), nullable=True))


def downgrade():
    op.drop_column('tenants', 'trial_ends_at')
