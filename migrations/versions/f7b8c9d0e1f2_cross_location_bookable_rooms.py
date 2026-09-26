"""cross-location bookable flag on conference rooms

Revision ID: f7b8c9d0e1f2
Revises: f6a7b8c9d0e1
"""
from alembic import op
import sqlalchemy as sa


revision = "f7b8c9d0e1f2"
down_revision = "f6a7b8c9d0e1"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("conference_rooms") as batch_op:
        batch_op.add_column(sa.Column("cross_location_bookable", sa.Boolean(), nullable=False,
                                      server_default=sa.false()))


def downgrade():
    with op.batch_alter_table("conference_rooms") as batch_op:
        batch_op.drop_column("cross_location_bookable")
