"""Idempotent manual payments and scheduled contract snapshots.

Revision ID: d6b2f8c1a395
Revises: a7c9e2b4d681
"""
from alembic import op
import sqlalchemy as sa

revision = 'd6b2f8c1a395'
down_revision = 'a7c9e2b4d681'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('platform_payments') as batch:
        batch.add_column(sa.Column('request_key', sa.String(64)))
        batch.create_unique_constraint('uq_platform_payment_request', ['request_key'])
    with op.batch_alter_table('operator_subscriptions') as batch:
        batch.add_column(sa.Column('scheduled_terms', sa.JSON()))
    op.get_bind().execute(sa.text("""
        INSERT INTO operator_subscriptions
            (operator_id, tier_id, billing_cycle, additional_free_seats, additional_free_locations,
             discount_amount, premium_modules_amount, implementation_charge, tax_rate,
             status, current_period_start, current_period_end, created_at, updated_at)
        SELECT operators.id, pricing_tiers.id, 'monthly', 0, 0, 0, 0, 0, 0,
            CASE WHEN EXISTS (SELECT 1 FROM platform_invoices
                              WHERE operator_id = operators.id AND status = 'PAID') THEN 'active' ELSE 'trial' END,
            (SELECT period_start FROM platform_invoices WHERE operator_id = operators.id AND status = 'PAID'
             ORDER BY period_end DESC LIMIT 1),
            (SELECT period_end FROM platform_invoices WHERE operator_id = operators.id AND status = 'PAID'
             ORDER BY period_end DESC LIMIT 1), CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        FROM operators LEFT JOIN pricing_tiers ON pricing_tiers.key = operators.plan_tier
        WHERE NOT EXISTS (SELECT 1 FROM operator_subscriptions WHERE operator_id = operators.id)
    """))


def downgrade():
    with op.batch_alter_table('operator_subscriptions') as batch:
        batch.drop_column('scheduled_terms')
    with op.batch_alter_table('platform_payments') as batch:
        batch.drop_constraint('uq_platform_payment_request', type_='unique')
        batch.drop_column('request_key')