"""Extra people on a subscription and allocations linked to the subscription

Revision ID: a2c4e6f81b35
Revises: f1a8d3c5b207
Create Date: 2026-10-11 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a2c4e6f81b35'
down_revision = 'f1a8d3c5b207'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('subscriptions') as batch:
        batch.add_column(sa.Column('people_per_unit', sa.Integer(), nullable=False, server_default='1'))
        batch.add_column(sa.Column('extra_people', sa.Integer(), nullable=False, server_default='0'))
        batch.add_column(sa.Column('extra_people_before', sa.Integer(), nullable=False, server_default='0'))
        batch.add_column(sa.Column('extra_effective_from', sa.Date(), nullable=True))
        batch.add_column(sa.Column('extra_person_price', sa.Numeric(10, 2), nullable=False, server_default='0'))
    with op.batch_alter_table('seat_allocations') as batch:
        batch.add_column(sa.Column('subscription_id', sa.Integer(), nullable=True))
        batch.create_foreign_key('fk_seat_allocations_subscription_id', 'subscriptions',
                                 ['subscription_id'], ['id'], ondelete='SET NULL')
    op.create_index('ix_seat_allocations_subscription_id', 'seat_allocations', ['subscription_id'])


def downgrade():
    op.drop_index('ix_seat_allocations_subscription_id', table_name='seat_allocations')
    with op.batch_alter_table('seat_allocations') as batch:
        batch.drop_constraint('fk_seat_allocations_subscription_id', type_='foreignkey')
        batch.drop_column('subscription_id')
    with op.batch_alter_table('subscriptions') as batch:
        for name in ('extra_person_price', 'extra_effective_from', 'extra_people_before', 'extra_people',
                     'people_per_unit'):
            batch.drop_column(name)
