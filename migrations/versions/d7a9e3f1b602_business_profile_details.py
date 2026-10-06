"""Optional company and operator business profile details."""
from alembic import op
import sqlalchemy as sa

revision = 'd7a9e3f1b602'
down_revision = 'c4d8e1f3a275'
branch_labels = None
depends_on = None


def upgrade():
    for table in ('companies', 'operators'):
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column('profile_details', sa.JSON(), nullable=True))
    with op.batch_alter_table('users') as batch:
        batch.add_column(sa.Column('invite_revoked', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    with op.batch_alter_table('users') as batch:
        batch.drop_column('invite_revoked')
    for table in ('companies', 'operators'):
        with op.batch_alter_table(table) as batch:
            batch.drop_column('profile_details')