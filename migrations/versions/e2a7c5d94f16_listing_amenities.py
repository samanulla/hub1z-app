"""Marketplace: amenities per listing.

Revision ID: e2a7c5d94f16
Revises: d1f6b4c83e95
"""
from alembic import op
import sqlalchemy as sa


revision = "e2a7c5d94f16"
down_revision = "d1f6b4c83e95"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("marketplace_listings", sa.Column("amenities", sa.JSON(), nullable=False,
                                                    server_default=sa.text("'{}'")))


def downgrade():
    op.drop_column("marketplace_listings", "amenities")
