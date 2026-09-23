"""pricing tiers

Introduces platform-defined tenant plan tiers with resource limits
(max_locations/max_seats/max_private_offices/max_rooms) and a monthly
price. Seeds the three tiers that already existed as a hardcoded string
list (starter/growth/enterprise) with starter defaults, so existing
tenants' `plan_tier` values keep resolving.

Revision ID: d7e1f3a5b8c0
Revises: c5d8e0f2a4b6
Create Date: 2026-09-22 00:10:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd7e1f3a5b8c0'
down_revision = 'c5d8e0f2a4b6'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'pricing_tiers',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('key', sa.String(length=30), nullable=False),
        sa.Column('name', sa.String(length=80), nullable=False),
        sa.Column('monthly_price', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('max_locations', sa.Integer(), nullable=True),
        sa.Column('max_seats', sa.Integer(), nullable=True),
        sa.Column('max_private_offices', sa.Integer(), nullable=True),
        sa.Column('max_rooms', sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('pricing_tiers', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_pricing_tiers_key'), ['key'], unique=True)

    op.execute("""
        INSERT INTO pricing_tiers
            (key, name, monthly_price, is_active, max_locations, max_seats, max_private_offices, max_rooms,
             created_at, updated_at)
        VALUES
            ('starter', 'Starter', 4999, true, 1, 30, 3, 2, NOW(), NOW()),
            ('growth', 'Growth', 14999, true, 3, 100, 10, 6, NOW(), NOW()),
            ('enterprise', 'Enterprise', NULL, true, NULL, NULL, NULL, NULL, NOW(), NOW())
    """)


def downgrade():
    op.drop_table('pricing_tiers')
