"""scope pricing_plans name uniqueness per tenant instead of globally

Revision ID: f5e6f7a8b9c0
Revises: f4d5e6f7a8b9
"""
from alembic import op


revision = "f5e6f7a8b9c0"
down_revision = "f4d5e6f7a8b9"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("pricing_plans") as batch_op:
        batch_op.drop_constraint("pricing_plans_name_key", type_="unique")
        batch_op.create_unique_constraint(
            "uq_pricing_plans_tenant_name", ["tenant_id", "name"])


def downgrade():
    with op.batch_alter_table("pricing_plans") as batch_op:
        batch_op.drop_constraint("uq_pricing_plans_tenant_name", type_="unique")
        batch_op.create_unique_constraint("pricing_plans_name_key", ["name"])
