"""Give legacy trial workspaces a deadline without requiring approval."""
from datetime import datetime, timedelta
import os

from alembic import op
import sqlalchemy as sa

revision = 'e8c2a4d6b910'
down_revision = 'd7a9e3f1b602'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('users') as batch:
        batch.add_column(sa.Column('auth_version', sa.Integer(), nullable=False, server_default='0'))
    connection = op.get_bind()
    profile = sa.table('platform_profile', sa.column('trial_days', sa.Integer))
    days = connection.execute(sa.select(profile.c.trial_days).limit(1)).scalar()
    days = days if days is not None else int(os.getenv('OPERATOR_TRIAL_DAYS', '14'))
    operators = sa.table('operators', sa.column('status', sa.String), sa.column('trial_ends_at', sa.DateTime))
    connection.execute(operators.update().where(operators.c.status == 'TRIAL', operators.c.trial_ends_at.is_(None))
                       .values(trial_ends_at=datetime.utcnow() + timedelta(days=days)))


def downgrade():
    with op.batch_alter_table('users') as batch:
        batch.drop_column('auth_version')