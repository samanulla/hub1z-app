"""finalize Hub1 tier validation

Revision ID: fc1f2a3b4c5d
Revises: fb0e1f2a3b4c
"""
from alembic import op
import sqlalchemy as sa


revision = "fc1f2a3b4c5d"
down_revision = "fb0e1f2a3b4c"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    method = sa.Enum("MAXIMUM_DURING_BILLING_PERIOD", "AVERAGE_DAILY_USAGE", "END_OF_PERIOD_USAGE", name="seatusagemethod")
    method.create(bind, checkfirst=True)
    with op.batch_alter_table("pricing_tiers") as batch_op:
        batch_op.add_column(sa.Column("seat_usage_method", method, nullable=False, server_default="MAXIMUM_DURING_BILLING_PERIOD"))
        batch_op.add_column(sa.Column("pricing_version", sa.Integer(), nullable=False, server_default="1"))
    with op.batch_alter_table("platform_modules") as batch_op:
        batch_op.add_column(sa.Column("kind", sa.String(20), nullable=False, server_default="module"))
    op.execute("""
        INSERT INTO platform_modules (code, name, monthly_price, kind, is_active, created_at, updated_at)
        VALUES
          ('core-operations', 'Core operations', 0, 'feature', true, NOW(), NOW()),
          ('booking', 'Booking and availability', 0, 'feature', true, NOW(), NOW()),
          ('billing', 'Billing and invoicing', 0, 'feature', true, NOW(), NOW()),
          ('analytics', 'Analytics and reporting', 0, 'module', true, NOW(), NOW()),
          ('integrations', 'Integrations', 0, 'module', true, NOW(), NOW()),
          ('priority-support', 'Priority support', 0, 'module', true, NOW(), NOW())
        ON CONFLICT (code) DO NOTHING
    """)


def downgrade():
    with op.batch_alter_table("platform_modules") as batch_op:
        batch_op.drop_column("kind")
    with op.batch_alter_table("pricing_tiers") as batch_op:
        batch_op.drop_column("pricing_version")
        batch_op.drop_column("seat_usage_method")