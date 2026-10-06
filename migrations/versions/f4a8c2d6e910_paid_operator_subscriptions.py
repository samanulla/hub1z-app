"""Paid operator subscriptions, invoice tax and add-on entitlements.

Revision ID: f4a8c2d6e910
Revises: b8d3f6a2c914
"""
from datetime import datetime, timedelta

from alembic import op
import sqlalchemy as sa

revision = 'f4a8c2d6e910'
down_revision = 'b8d3f6a2c914'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('operator_subscriptions') as batch:
        batch.add_column(sa.Column('status', sa.String(12), nullable=False, server_default='trial'))
        batch.add_column(sa.Column('current_period_start', sa.Date()))
        batch.add_column(sa.Column('current_period_end', sa.Date()))
        batch.add_column(sa.Column('scheduled_tier_id', sa.Integer()))
        batch.add_column(sa.Column('scheduled_billing_cycle', sa.String(10)))
        batch.create_foreign_key('fk_subscription_scheduled_tier', 'pricing_tiers', ['scheduled_tier_id'], ['id'],
                                 ondelete='SET NULL')
    with op.batch_alter_table('platform_invoices') as batch:
        batch.add_column(sa.Column('kind', sa.String(12), nullable=False, server_default='manual'))
        batch.add_column(sa.Column('idempotency_key', sa.String(160)))
        batch.create_unique_constraint('uq_platform_invoice_intent', ['idempotency_key'])
        for name in ('subtotal', 'cgst', 'sgst', 'igst'):
            batch.add_column(sa.Column(name, sa.Numeric(10, 2), nullable=False, server_default='0'))
        batch.add_column(sa.Column('tax_rate', sa.Numeric(5, 2), nullable=False, server_default='0'))
        batch.add_column(sa.Column('gst_state', sa.String(2)))
        batch.add_column(sa.Column('sac_code', sa.String(10)))
        batch.add_column(sa.Column('lines', sa.JSON(), nullable=False, server_default=sa.text("'[]'")))
        batch.add_column(sa.Column('activation', sa.JSON()))
        batch.add_column(sa.Column('paid_at', sa.DateTime()))
    op.create_table('operator_addons',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('operator_id', sa.Integer(), sa.ForeignKey('operators.id', ondelete='CASCADE'), nullable=False),
        sa.Column('module_id', sa.Integer(), sa.ForeignKey('platform_modules.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('quantity', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('monthly_price', sa.Numeric(10, 2), nullable=False, server_default='0'),
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('paid_through', sa.Date()),
        sa.Column('cancel_at_period_end', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('operator_id', 'module_id', name='uq_operator_addon'))
    op.create_index('ix_operator_addons_operator_id', 'operator_addons', ['operator_id'])
    op.create_table('platform_payments',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('invoice_id', sa.Integer(), sa.ForeignKey('platform_invoices.id', ondelete='CASCADE'), nullable=False),
        sa.Column('report_id', sa.Integer(), sa.ForeignKey('platform_payment_reports.id', ondelete='SET NULL'), unique=True),
        sa.Column('amount', sa.Numeric(10, 2), nullable=False),
        sa.Column('method', sa.String(16), nullable=False),
        sa.Column('reference', sa.String(120)),
        sa.Column('recorded_by_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL')),
        sa.Column('paid_on', sa.Date(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False))
    op.create_index('ix_platform_payments_invoice_id', 'platform_payments', ['invoice_id'])
    bind = op.get_bind()
    bind.execute(sa.text('UPDATE platform_invoices SET subtotal = amount'))
    days = bind.execute(sa.text('SELECT trial_days FROM platform_profile ORDER BY id LIMIT 1')).scalar() or 14
    deadline = datetime.utcnow() + timedelta(days=days)
    bind.execute(sa.text("UPDATE operators SET status = 'TRIAL', trial_ends_at = :deadline "
                         "WHERE status IN ('ACTIVE', 'TRIAL') AND id NOT IN "
                         "(SELECT operator_id FROM platform_invoices WHERE status = 'PAID')"), {'deadline': deadline})
    bind.execute(sa.text("UPDATE operator_subscriptions SET status = 'active', "
                         "current_period_start = (SELECT period_start FROM platform_invoices "
                         "WHERE operator_id = operator_subscriptions.operator_id AND status = 'PAID' "
                         "ORDER BY period_end DESC LIMIT 1), "
                         "current_period_end = (SELECT period_end FROM platform_invoices "
                         "WHERE operator_id = operator_subscriptions.operator_id AND status = 'PAID' "
                         "ORDER BY period_end DESC LIMIT 1) "
                         "WHERE operator_id IN (SELECT operator_id FROM platform_invoices WHERE status = 'PAID')"))


def downgrade():
    op.drop_table('platform_payments')
    op.drop_table('operator_addons')
    with op.batch_alter_table('platform_invoices') as batch:
        batch.drop_constraint('uq_platform_invoice_intent', type_='unique')
        for name in ('kind', 'idempotency_key', 'subtotal', 'cgst', 'sgst', 'igst', 'tax_rate', 'gst_state',
                     'sac_code', 'lines', 'activation', 'paid_at'):
            batch.drop_column(name)
    with op.batch_alter_table('operator_subscriptions') as batch:
        batch.drop_constraint('fk_subscription_scheduled_tier', type_='foreignkey')
        for name in ('status', 'current_period_start', 'current_period_end', 'scheduled_tier_id', 'scheduled_billing_cycle'):
            batch.drop_column(name)