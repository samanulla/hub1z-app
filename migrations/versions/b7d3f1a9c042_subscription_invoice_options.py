"""Per-subscription proration and automatic-send options

Revision ID: b7d3f1a9c042
Revises: a2c4e6f81b35
Create Date: 2026-10-11 18:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b7d3f1a9c042'
down_revision = 'a2c4e6f81b35'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('subscriptions') as batch:
        batch.add_column(sa.Column('prorate_partial', sa.Boolean(), nullable=False, server_default=sa.true()))
        batch.add_column(sa.Column('auto_send_invoices', sa.Boolean(), nullable=False, server_default=sa.true()))


def downgrade():
    with op.batch_alter_table('subscriptions') as batch:
        batch.drop_column('auto_send_invoices')
        batch.drop_column('prorate_partial')
