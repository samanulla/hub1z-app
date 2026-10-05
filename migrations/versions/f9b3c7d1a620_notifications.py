"""Recipient notifications with persistent read state."""
from alembic import op
import sqlalchemy as sa

revision = 'f9b3c7d1a620'
down_revision = 'e8c2a4d6b910'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('notifications',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('operator_id', sa.Integer(), sa.ForeignKey('operators.id', ondelete='CASCADE'), nullable=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('event_key', sa.String(180), nullable=False),
        sa.Column('kind', sa.String(30), nullable=False),
        sa.Column('title', sa.String(200), nullable=False),
        sa.Column('body', sa.Text()),
        sa.Column('href', sa.String(500), nullable=False),
        sa.Column('read_at', sa.DateTime()),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('user_id', 'event_key', name='uq_notification_user_event'))
    op.create_index('ix_notifications_operator_id', 'notifications', ['operator_id'])
    op.create_index('ix_notification_user_unread', 'notifications', ['user_id', 'read_at', 'created_at'])


def downgrade():
    op.drop_table('notifications')