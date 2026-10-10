"""Marketplace: optional locality on locations for the public area filter.

Revision ID: d1f6b4c83e95
Revises: c9e5a3b72d84
"""
from alembic import op
import sqlalchemy as sa


revision = "d1f6b4c83e95"
down_revision = "c9e5a3b72d84"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("locations", sa.Column("locality", sa.String(80)))


def downgrade():
    op.drop_column("locations", "locality")
