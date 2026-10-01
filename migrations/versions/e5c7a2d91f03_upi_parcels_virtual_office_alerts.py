"""UPI payments, parcels, virtual office, renewal alerts

Revision ID: e5c7a2d91f03
Revises: c3a19d7e5b40
Create Date: 2026-10-04 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e5c7a2d91f03'
down_revision = 'c3a19d7e5b40'
branch_labels = None
depends_on = None


def _stamps():
    return [sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=False)]


def upgrade():
    if op.get_bind().dialect.name == 'postgresql':
        op.execute("ALTER TYPE plantype ADD VALUE IF NOT EXISTS 'VIRTUAL_OFFICE'")

    with op.batch_alter_table('payment_submissions') as batch:
        batch.alter_column('company_id', existing_type=sa.Integer(), nullable=True)
        batch.add_column(sa.Column('user_id', sa.Integer(), nullable=True))
        batch.create_foreign_key('fk_payment_submissions_user_id', 'users', ['user_id'], ['id'], ondelete='SET NULL')
    op.create_index('ix_payment_submissions_user_id', 'payment_submissions', ['user_id'])

    op.create_table(
        'parcels', *_stamps(),
        sa.Column('operator_id', sa.Integer(), nullable=False),
        sa.Column('location_id', sa.Integer(), nullable=True),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('company_id', sa.Integer(), nullable=True),
        sa.Column('kind', sa.String(length=20), nullable=False, server_default='parcel'),
        sa.Column('carrier', sa.String(length=60), nullable=True),
        sa.Column('reference', sa.String(length=120), nullable=True),
        sa.Column('sender', sa.String(length=120), nullable=True),
        sa.Column('note', sa.String(length=255), nullable=True),
        sa.Column('received_at', sa.DateTime(), nullable=False),
        sa.Column('received_by_id', sa.Integer(), nullable=True),
        sa.Column('status', sa.String(length=12), nullable=False, server_default='waiting'),
        sa.Column('pickup_code', sa.String(length=6), nullable=False),
        sa.Column('notified_at', sa.DateTime(), nullable=True),
        sa.Column('collected_at', sa.DateTime(), nullable=True),
        sa.Column('collected_by', sa.String(length=120), nullable=True),
        sa.Column('handed_over_by_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['operator_id'], ['operators.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['location_id'], ['locations.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['received_by_id'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['handed_over_by_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_parcels_operator_id', 'parcels', ['operator_id'])
    op.create_index('ix_parcels_user_id', 'parcels', ['user_id'])
    op.create_index('ix_parcels_company_id', 'parcels', ['company_id'])
    op.create_index('ix_parcels_operator_status', 'parcels', ['operator_id', 'status'])

    op.create_table(
        'alert_notices',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('operator_id', sa.Integer(), nullable=False),
        sa.Column('key', sa.String(length=120), nullable=False),
        sa.Column('sent_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['operator_id'], ['operators.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('operator_id', 'key', name='uq_alert_notices_operator_key'),
    )
    op.create_index('ix_alert_notices_operator_id', 'alert_notices', ['operator_id'])

    op.create_table(
        'platform_profile', *_stamps(),
        sa.Column('legal_name', sa.String(length=200), nullable=False),
        sa.Column('gstin', sa.String(length=20), nullable=True),
        sa.Column('pan', sa.String(length=20), nullable=True),
        sa.Column('address', sa.String(length=300), nullable=True),
        sa.Column('billing_email', sa.String(length=255), nullable=True),
        sa.Column('upi_id', sa.String(length=120), nullable=True),
        sa.Column('gpay', sa.String(length=120), nullable=True),
        sa.Column('bank_details', sa.String(length=500), nullable=True),
        sa.Column('payment_instructions', sa.String(length=500), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table(
        'platform_payment_reports', *_stamps(),
        sa.Column('operator_id', sa.Integer(), nullable=False),
        sa.Column('invoice_id', sa.Integer(), nullable=False),
        sa.Column('amount', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('paid_on', sa.Date(), nullable=False),
        sa.Column('reference', sa.String(length=120), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=12), nullable=False, server_default='pending'),
        sa.Column('platform_message', sa.Text(), nullable=True),
        sa.Column('reported_by_id', sa.Integer(), nullable=True),
        sa.Column('reviewed_by_id', sa.Integer(), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['operator_id'], ['operators.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['invoice_id'], ['platform_invoices.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['reported_by_id'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['reviewed_by_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_platform_payment_reports_operator_id', 'platform_payment_reports', ['operator_id'])
    op.create_index('ix_platform_payment_reports_invoice_id', 'platform_payment_reports', ['invoice_id'])
    op.create_index('ix_platform_payment_reports_status', 'platform_payment_reports', ['status'])


def downgrade():
    op.drop_table('platform_payment_reports')
    op.drop_table('platform_profile')
    op.drop_table('alert_notices')
    op.drop_table('parcels')
    op.drop_index('ix_payment_submissions_user_id', table_name='payment_submissions')
    with op.batch_alter_table('payment_submissions') as batch:
        batch.drop_constraint('fk_payment_submissions_user_id', type_='foreignkey')
        batch.drop_column('user_id')
    # The VIRTUAL_OFFICE value stays in the plantype enum: Postgres cannot drop an enum value.
