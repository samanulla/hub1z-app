"""agreements, GST split, deposits, rate revisions

Revision ID: a7d41c9e6b52
Revises: 3f6f9529f9e3
Create Date: 2026-10-02 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a7d41c9e6b52'
down_revision = '3f6f9529f9e3'
branch_labels = None
depends_on = None


def _base_columns():
    return [
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('operator_id', sa.Integer(), nullable=False),
    ]


def upgrade():
    op.create_table(
        'billing_settings',
        sa.Column('invoice_issue_day', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('due_day', sa.Integer(), nullable=False, server_default='5'),
        sa.Column('late_fee_mode', sa.String(length=10), nullable=False, server_default='none'),
        sa.Column('late_fee_value', sa.Numeric(10, 2), nullable=False, server_default='0'),
        sa.Column('late_fee_grace_days', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('term_months', sa.Integer(), nullable=False, server_default='11'),
        sa.Column('lock_in_months', sa.Integer(), nullable=False, server_default='6'),
        sa.Column('notice_months', sa.Integer(), nullable=False, server_default='3'),
        sa.Column('deposit_months', sa.Integer(), nullable=False, server_default='3'),
        sa.Column('deposit_refund_days', sa.Integer(), nullable=False, server_default='15'),
        sa.Column('escalation_percent', sa.Numeric(5, 2), nullable=False, server_default='10'),
        sa.Column('escalation_after_months', sa.Integer(), nullable=False, server_default='11'),
        sa.Column('early_exit_rule', sa.String(length=20), nullable=False, server_default='remaining_fees'),
        *_base_columns(),
        sa.ForeignKeyConstraint(['operator_id'], ['operators.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('operator_id', name='uq_billing_settings_operator'),
    )
    with op.batch_alter_table('billing_settings', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_billing_settings_operator_id'), ['operator_id'], unique=False)

    op.create_table(
        'tax_rates',
        sa.Column('charge_type', sa.String(length=20), nullable=False),
        sa.Column('rate', sa.Numeric(5, 2), nullable=False),
        sa.Column('sac_code', sa.String(length=12), nullable=True),
        sa.Column('effective_from', sa.Date(), nullable=False),
        *_base_columns(),
        sa.ForeignKeyConstraint(['operator_id'], ['operators.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('operator_id', 'charge_type', 'effective_from', name='uq_tax_rates_operator_type_from'),
    )
    with op.batch_alter_table('tax_rates', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_tax_rates_operator_id'), ['operator_id'], unique=False)

    op.create_table(
        'rate_revisions',
        sa.Column('subscription_id', sa.Integer(), nullable=False),
        sa.Column('effective_from', sa.Date(), nullable=False),
        sa.Column('percent', sa.Numeric(5, 2), nullable=False),
        sa.Column('old_unit_price', sa.Numeric(10, 2), nullable=False),
        sa.Column('new_unit_price', sa.Numeric(10, 2), nullable=False),
        sa.Column('status', sa.String(length=10), nullable=False),
        sa.Column('decided_by_id', sa.Integer(), nullable=True),
        sa.Column('decided_at', sa.DateTime(), nullable=True),
        *_base_columns(),
        sa.ForeignKeyConstraint(['decided_by_id'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['operator_id'], ['operators.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['subscription_id'], ['subscriptions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('rate_revisions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_rate_revisions_operator_id'), ['operator_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_rate_revisions_status'), ['status'], unique=False)
        batch_op.create_index(batch_op.f('ix_rate_revisions_subscription_id'), ['subscription_id'], unique=False)

    op.create_table(
        'deposit_entries',
        sa.Column('subscription_id', sa.Integer(), nullable=False),
        sa.Column('entry_type', sa.String(length=10), nullable=False),
        sa.Column('amount', sa.Numeric(10, 2), nullable=False),
        sa.Column('entry_date', sa.Date(), nullable=False),
        sa.Column('note', sa.String(length=255), nullable=True),
        sa.Column('invoice_id', sa.Integer(), nullable=True),
        sa.Column('created_by_id', sa.Integer(), nullable=True),
        *_base_columns(),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['invoice_id'], ['invoices.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['operator_id'], ['operators.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['subscription_id'], ['subscriptions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('deposit_entries', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_deposit_entries_operator_id'), ['operator_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_deposit_entries_subscription_id'), ['subscription_id'], unique=False)

    with op.batch_alter_table('operators', schema=None) as batch_op:
        batch_op.add_column(sa.Column('gst_state', sa.String(length=2), nullable=True))

    with op.batch_alter_table('companies', schema=None) as batch_op:
        batch_op.add_column(sa.Column('pan', sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column('gst_state', sa.String(length=2), nullable=True))

    with op.batch_alter_table('invoices', schema=None) as batch_op:
        batch_op.add_column(sa.Column('cgst_amount', sa.Numeric(10, 2), nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('sgst_amount', sa.Numeric(10, 2), nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('igst_amount', sa.Numeric(10, 2), nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('seller_gstin', sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column('seller_pan', sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column('seller_state', sa.String(length=2), nullable=True))
        batch_op.add_column(sa.Column('buyer_gstin', sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column('buyer_pan', sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column('buyer_state', sa.String(length=2), nullable=True))
        batch_op.add_column(sa.Column('late_fee_charged_through', sa.Date(), nullable=True))

    with op.batch_alter_table('invoice_line_items', schema=None) as batch_op:
        batch_op.add_column(sa.Column('line_type', sa.String(length=20), nullable=False, server_default='other'))
        batch_op.add_column(sa.Column('tax_rate', sa.Numeric(5, 2), nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('tax_amount', sa.Numeric(10, 2), nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('sac_code', sa.String(length=12), nullable=True))

    with op.batch_alter_table('subscriptions', schema=None) as batch_op:
        batch_op.add_column(sa.Column('term_months', sa.Integer(), nullable=False, server_default='11'))
        batch_op.add_column(sa.Column('lock_in_months', sa.Integer(), nullable=False, server_default='6'))
        batch_op.add_column(sa.Column('notice_months', sa.Integer(), nullable=False, server_default='3'))
        batch_op.add_column(sa.Column('deposit_amount', sa.Numeric(10, 2), nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('deposit_refund_days', sa.Integer(), nullable=False, server_default='15'))
        batch_op.add_column(sa.Column('escalation_percent', sa.Numeric(5, 2), nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('escalation_after_months', sa.Integer(), nullable=False, server_default='11'))
        batch_op.add_column(sa.Column('due_day', sa.Integer(), nullable=False, server_default='5'))
        batch_op.add_column(sa.Column('late_fee_mode', sa.String(length=10), nullable=False, server_default='none'))
        batch_op.add_column(sa.Column('late_fee_value', sa.Numeric(10, 2), nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('late_fee_grace_days', sa.Integer(), nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('early_exit_rule', sa.String(length=20), nullable=False,
                                      server_default='remaining_fees'))
        batch_op.add_column(sa.Column('price_includes_tax', sa.Boolean(), nullable=False,
                                      server_default=sa.false()))
        batch_op.add_column(sa.Column('notice_given_on', sa.Date(), nullable=True))
        batch_op.add_column(sa.Column('terminate_on', sa.Date(), nullable=True))
        batch_op.add_column(sa.Column('agreement_document_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key('fk_subscriptions_agreement_document', 'documents',
                                    ['agreement_document_id'], ['id'], ondelete='SET NULL')


def downgrade():
    with op.batch_alter_table('subscriptions', schema=None) as batch_op:
        batch_op.drop_constraint('fk_subscriptions_agreement_document', type_='foreignkey')
        for col in ('agreement_document_id', 'terminate_on', 'notice_given_on', 'price_includes_tax',
                    'early_exit_rule', 'late_fee_grace_days', 'late_fee_value', 'late_fee_mode', 'due_day',
                    'escalation_after_months', 'escalation_percent', 'deposit_refund_days', 'deposit_amount',
                    'notice_months', 'lock_in_months', 'term_months'):
            batch_op.drop_column(col)

    with op.batch_alter_table('invoice_line_items', schema=None) as batch_op:
        for col in ('sac_code', 'tax_amount', 'tax_rate', 'line_type'):
            batch_op.drop_column(col)

    with op.batch_alter_table('invoices', schema=None) as batch_op:
        for col in ('late_fee_charged_through', 'buyer_state', 'buyer_pan', 'buyer_gstin', 'seller_state',
                    'seller_pan', 'seller_gstin', 'igst_amount', 'sgst_amount', 'cgst_amount'):
            batch_op.drop_column(col)

    with op.batch_alter_table('companies', schema=None) as batch_op:
        batch_op.drop_column('gst_state')
        batch_op.drop_column('pan')

    with op.batch_alter_table('operators', schema=None) as batch_op:
        batch_op.drop_column('gst_state')

    op.drop_table('deposit_entries')
    op.drop_table('rate_revisions')
    op.drop_table('tax_rates')
    op.drop_table('billing_settings')
