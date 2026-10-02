"""Let an operator reduce an add-on's units at the next renewal.

Revision ID: e2f7a9c4b106
Revises: d6b2f8c1a395
"""
from alembic import op
import sqlalchemy as sa

revision = 'e2f7a9c4b106'
down_revision = 'd6b2f8c1a395'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('operator_addons') as batch:
        batch.add_column(sa.Column('renewal_quantity', sa.Integer()))


def downgrade():
    with op.batch_alter_table('operator_addons') as batch:
        batch.drop_column('renewal_quantity')
