"""leads and attendance

Revision ID: c3a19d7e5b40
Revises: a7d41c9e6b52
Create Date: 2026-10-03 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c3a19d7e5b40'
down_revision = 'a7d41c9e6b52'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('locations', sa.Column('checkin_key', sa.String(length=32), nullable=True))

    op.create_table(
        'leads',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('operator_id', sa.Integer(), nullable=True),
        sa.Column('name', sa.String(length=160), nullable=False),
        sa.Column('company_name', sa.String(length=200), nullable=True),
        sa.Column('email', sa.String(length=255), nullable=True),
        sa.Column('phone', sa.String(length=40), nullable=True),
        sa.Column('interest', sa.String(length=200), nullable=True),
        sa.Column('seats', sa.Integer(), nullable=True),
        sa.Column('expected_value', sa.Numeric(precision=12, scale=2), nullable=False, server_default='0'),
        sa.Column('source', sa.String(length=40), nullable=True),
        sa.Column('stage', sa.String(length=20), nullable=False, server_default='new'),
        sa.Column('temperature', sa.String(length=10), nullable=False, server_default='warm'),
        sa.Column('owner_id', sa.Integer(), nullable=True),
        sa.Column('next_follow_up', sa.Date(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('lost_reason', sa.String(length=200), nullable=True),
        sa.Column('closed_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['operator_id'], ['operators.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_leads_operator_id', 'leads', ['operator_id'])
    op.create_index('ix_leads_stage', 'leads', ['stage'])
    op.create_index('ix_leads_owner_id', 'leads', ['owner_id'])
    op.create_index('ix_leads_next_follow_up', 'leads', ['next_follow_up'])

    op.create_table(
        'lead_activities',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('operator_id', sa.Integer(), nullable=True),
        sa.Column('lead_id', sa.Integer(), nullable=False),
        sa.Column('kind', sa.String(length=20), nullable=False, server_default='note'),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('created_by_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['operator_id'], ['operators.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['lead_id'], ['leads.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_lead_activities_operator_id', 'lead_activities', ['operator_id'])
    op.create_index('ix_lead_activities_lead_id', 'lead_activities', ['lead_id'])

    op.create_table(
        'attendance_records',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('operator_id', sa.Integer(), nullable=True),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('location_id', sa.Integer(), nullable=True),
        sa.Column('check_in_at', sa.DateTime(), nullable=False),
        sa.Column('check_out_at', sa.DateTime(), nullable=True),
        sa.Column('method', sa.String(length=20), nullable=False, server_default='manual'),
        sa.Column('recorded_by_id', sa.Integer(), nullable=True),
        sa.Column('note', sa.String(length=200), nullable=True),
        sa.ForeignKeyConstraint(['operator_id'], ['operators.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['location_id'], ['locations.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['recorded_by_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_attendance_records_operator_id', 'attendance_records', ['operator_id'])
    op.create_index('ix_attendance_records_user_id', 'attendance_records', ['user_id'])
    op.create_index('ix_attendance_records_location_id', 'attendance_records', ['location_id'])
    op.create_index('ix_attendance_operator_checkin', 'attendance_records', ['operator_id', 'check_in_at'])


def downgrade():
    op.drop_table('attendance_records')
    op.drop_table('lead_activities')
    op.drop_table('leads')
    op.drop_column('locations', 'checkin_key')
