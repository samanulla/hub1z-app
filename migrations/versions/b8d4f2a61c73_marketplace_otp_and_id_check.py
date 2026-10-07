"""Marketplace: customer one-time codes and guest ID checks.

Revision ID: b8d4f2a61c73
Revises: a7c3e9b15d42
"""
from alembic import op
import sqlalchemy as sa


revision = "b8d4f2a61c73"
down_revision = "a7c3e9b15d42"
branch_labels = None
depends_on = None

ID_STATUSES = ("not_required", "pending_upload", "pending_review", "approved", "rejected")


def upgrade():
    op.add_column("marketplace_customers", sa.Column("otp_hash", sa.String(64)))
    op.add_column("marketplace_customers", sa.Column("otp_expires_at", sa.DateTime()))
    op.add_column("marketplace_customers", sa.Column("otp_attempts", sa.Integer(), nullable=False,
                                                     server_default="0"))
    op.add_column("marketplace_bookings", sa.Column("id_status", sa.String(20), nullable=False,
                                                    server_default="not_required"))
    op.add_column("marketplace_bookings", sa.Column("id_document_key", sa.String(300)))
    op.add_column("marketplace_bookings", sa.Column("id_document_name", sa.String(200)))
    op.add_column("marketplace_bookings", sa.Column("id_reviewed_at", sa.DateTime()))
    op.add_column("marketplace_bookings", sa.Column("id_reject_reason", sa.String(300)))
    op.create_check_constraint("ck_mkt_booking_id_status", "marketplace_bookings",
                               f"id_status IN ({', '.join(repr(v) for v in ID_STATUSES)})")


def downgrade():
    op.drop_constraint("ck_mkt_booking_id_status", "marketplace_bookings", type_="check")
    for col in ("id_reject_reason", "id_reviewed_at", "id_document_name", "id_document_key", "id_status"):
        op.drop_column("marketplace_bookings", col)
    for col in ("otp_attempts", "otp_expires_at", "otp_hash"):
        op.drop_column("marketplace_customers", col)
