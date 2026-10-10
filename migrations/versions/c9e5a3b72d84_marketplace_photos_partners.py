"""Marketplace: listing photos, partner applications and virtual-office listings.

Revision ID: c9e5a3b72d84
Revises: b8d4f2a61c73
"""
from alembic import op
import sqlalchemy as sa


revision = "c9e5a3b72d84"
down_revision = "b8d4f2a61c73"
branch_labels = None
depends_on = None


def _ts():
    return (sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False))


def upgrade():
    op.drop_constraint("ck_mkt_listing_resource", "marketplace_listings", type_="check")
    op.create_check_constraint("ck_mkt_listing_resource", "marketplace_listings",
                               "resource_type IN ('room', 'day_access', 'virtual_office')")
    op.create_table(
        "marketplace_listing_photos",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("operator_id", sa.Integer(), sa.ForeignKey("operators.id", ondelete="CASCADE"), nullable=False),
        sa.Column("listing_id", sa.Integer(), sa.ForeignKey("marketplace_listings.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("storage_key", sa.String(300), nullable=False), sa.Column("content_type", sa.String(60), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False), *_ts())
    op.create_index("ix_marketplace_listing_photos_operator_id", "marketplace_listing_photos", ["operator_id"])
    op.create_index("ix_marketplace_listing_photos_listing_id", "marketplace_listing_photos", ["listing_id"])
    op.create_table(
        "marketplace_partner_applications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("business_name", sa.String(200), nullable=False), sa.Column("contact_name", sa.String(150), nullable=False),
        sa.Column("email", sa.String(255), nullable=False), sa.Column("phone", sa.String(30)),
        sa.Column("address_line1", sa.String(255), nullable=False), sa.Column("city", sa.String(80), nullable=False),
        sa.Column("state", sa.String(80)), sa.Column("postal_code", sa.String(20)),
        sa.Column("gstin", sa.String(20)), sa.Column("pan", sa.String(20)), sa.Column("upi_id", sa.String(120)),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("lead_id", sa.Integer(), sa.ForeignKey("leads.id", ondelete="SET NULL")),
        sa.Column("operator_id", sa.Integer(), sa.ForeignKey("operators.id", ondelete="SET NULL")), *_ts())
    op.create_index("ix_marketplace_partner_applications_email", "marketplace_partner_applications", ["email"])


def downgrade():
    op.drop_table("marketplace_partner_applications")
    op.drop_table("marketplace_listing_photos")
    op.drop_constraint("ck_mkt_listing_resource", "marketplace_listings", type_="check")
    op.create_check_constraint("ck_mkt_listing_resource", "marketplace_listings", "resource_type IN ('room', 'day_access')")
