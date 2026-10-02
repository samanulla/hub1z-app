"""Public lead origin and location usage for operator quotas and arrears.

Revision ID: a7c9e2b4d681
Revises: f4a8c2d6e910
"""
from alembic import op
import sqlalchemy as sa

revision = 'a7c9e2b4d681'
down_revision = 'f4a8c2d6e910'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('leads') as batch:
        batch.add_column(sa.Column('is_website_enquiry', sa.Boolean(), nullable=False, server_default=sa.false()))
    with op.batch_alter_table('operator_usage_snapshots') as batch:
        batch.add_column(sa.Column('active_locations', sa.Integer(), nullable=False, server_default='0'))


def downgrade():
    with op.batch_alter_table('operator_usage_snapshots') as batch:
        batch.drop_column('active_locations')
    with op.batch_alter_table('leads') as batch:
        batch.drop_column('is_website_enquiry')