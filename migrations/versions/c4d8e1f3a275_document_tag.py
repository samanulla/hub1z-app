"""Optional tag or short description on documents, to identify and search them.

Revision ID: c4d8e1f3a275
Revises: e2f7a9c4b106
"""
from alembic import op
import sqlalchemy as sa

revision = 'c4d8e1f3a275'
down_revision = 'e2f7a9c4b106'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('documents') as batch:
        batch.add_column(sa.Column('tag', sa.String(255)))


def downgrade():
    with op.batch_alter_table('documents') as batch:
        batch.drop_column('tag')
