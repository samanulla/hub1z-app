"""Operator marketplace: listings, customers, bookings, commission ledger, booking_source.

Revision ID: a7c3e9b15d42
Revises: fc72b8d19a04
"""
from alembic import op
import sqlalchemy as sa


revision = "a7c3e9b15d42"
down_revision = "fc72b8d19a04"
branch_labels = None
depends_on = None

SOURCES = ("hub1z_marketplace", "operator_site", "operator_member")
STATUSES = ("requested", "held", "confirmed", "checked_in", "completed", "declined", "expired",
            "cancelled_customer", "cancelled_operator", "no_show")
PAYMENT_STATUSES = ("unpaid", "pending_verification", "paid", "part_refunded", "refunded")


def _in(column, values):
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def _ts():
    return (sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False))


def _op():
    return sa.Column("operator_id", sa.Integer(), sa.ForeignKey("operators.id", ondelete="CASCADE"),
                     nullable=False, index=True)


def upgrade():
    for table in ("room_bookings", "seat_bookings", "day_passes"):
        op.add_column(table, sa.Column("booking_source", sa.String(24), nullable=False,
                                       server_default="operator_member"))

    op.create_table(
        "operator_marketplace_terms",
        sa.Column("id", sa.Integer(), primary_key=True), _op(),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("commission_pct", sa.Numeric(5, 2), nullable=False),
        sa.Column("effective_from", sa.DateTime(), nullable=False),
        sa.Column("accepted_terms_at", sa.DateTime()),
        sa.Column("kyc_approved", sa.Boolean(), nullable=False),
        sa.Column("payment_methods", sa.JSON(), nullable=False),
        sa.Column("operator_cancel_compensation_pct", sa.Numeric(5, 2), nullable=False), *_ts(),
        sa.UniqueConstraint("operator_id", name="uq_marketplace_terms_operator"))

    op.create_table(
        "marketplace_customers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("full_name", sa.String(150), nullable=False), sa.Column("phone", sa.String(30)),
        sa.Column("email_verified_at", sa.DateTime()), sa.Column("password_hash", sa.String(255)),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("billing_profiles", sa.JSON(), nullable=False),
        sa.Column("reliability_strikes", sa.Integer(), nullable=False),
        sa.Column("consented_at", sa.DateTime()), sa.Column("auth_version", sa.Integer(), nullable=False), *_ts())
    op.create_index("ix_marketplace_customers_email", "marketplace_customers", ["email"], unique=True)

    op.create_table(
        "marketplace_listings",
        sa.Column("id", sa.Integer(), primary_key=True), _op(),
        sa.Column("location_id", sa.Integer(), sa.ForeignKey("locations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("resource_type", sa.String(20), nullable=False),
        sa.Column("room_id", sa.Integer(), sa.ForeignKey("conference_rooms.id", ondelete="RESTRICT")),
        sa.Column("title", sa.String(160), nullable=False), sa.Column("description", sa.Text()),
        sa.Column("status", sa.String(12), nullable=False), sa.Column("approval_mode", sa.String(10), nullable=False),
        sa.Column("price", sa.Numeric(10, 2), nullable=False), sa.Column("gst_rate_pct", sa.Numeric(5, 2), nullable=False),
        sa.Column("daily_cap_units", sa.Integer()), sa.Column("daily_cap_hours_pct", sa.Integer()),
        sa.Column("availability_windows", sa.JSON(), nullable=False), sa.Column("blackout_dates", sa.JSON(), nullable=False),
        sa.Column("min_lead_hours", sa.Integer(), nullable=False), sa.Column("max_length_hours", sa.Integer(), nullable=False),
        sa.Column("visibility", sa.JSON(), nullable=False), sa.Column("guest_rules", sa.JSON(), nullable=False),
        sa.Column("access_instructions", sa.Text()),
        sa.Column("cancellation_preset", sa.String(20), nullable=False), sa.Column("payment_methods", sa.JSON()),
        sa.Column("paused_at", sa.DateTime()), *_ts(),
        sa.CheckConstraint(_in("resource_type", ("room", "day_access")), name="ck_mkt_listing_resource"),
        sa.CheckConstraint(_in("status", ("draft", "live", "paused", "unlisted")), name="ck_mkt_listing_status"),
        sa.CheckConstraint(_in("approval_mode", ("instant", "request")), name="ck_mkt_listing_approval"))
    op.create_index("ix_marketplace_listings_location_id", "marketplace_listings", ["location_id"])
    op.create_index("ix_marketplace_listings_room_id", "marketplace_listings", ["room_id"])
    op.create_index("ix_mkt_listing_public", "marketplace_listings", ["status", "location_id"])

    op.create_table(
        "marketplace_bookings",
        sa.Column("id", sa.Integer(), primary_key=True), _op(),
        sa.Column("listing_id", sa.Integer(), sa.ForeignKey("marketplace_listings.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("marketplace_customers.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("room_booking_id", sa.Integer(), sa.ForeignKey("room_bookings.id", ondelete="RESTRICT")),
        sa.Column("code", sa.String(16), nullable=False), sa.Column("idempotency_key", sa.String(64), nullable=False),
        sa.Column("source", sa.String(24), nullable=False), sa.Column("status", sa.String(24), nullable=False),
        sa.Column("payment_status", sa.String(24), nullable=False), sa.Column("payment_method", sa.String(20)),
        sa.Column("payment_reference", sa.String(120)), sa.Column("settlement_mode", sa.String(20), nullable=False),
        sa.Column("start_at", sa.DateTime(), nullable=False), sa.Column("end_at", sa.DateTime(), nullable=False),
        sa.Column("units", sa.Integer(), nullable=False), sa.Column("guests", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime()),
        sa.Column("customer_name", sa.String(150), nullable=False), sa.Column("customer_email", sa.String(255), nullable=False),
        sa.Column("customer_phone", sa.String(30)), sa.Column("billing_name", sa.String(200)),
        sa.Column("billing_gstin", sa.String(20)), sa.Column("allow_membership_contact", sa.Boolean(), nullable=False),
        sa.Column("subtotal", sa.Numeric(10, 2), nullable=False), sa.Column("gst_amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("total", sa.Numeric(10, 2), nullable=False), sa.Column("commission_pct", sa.Numeric(5, 2), nullable=False),
        sa.Column("cancellation_preset", sa.String(20), nullable=False),
        sa.Column("cancelled_at", sa.DateTime()), sa.Column("cancel_reason", sa.String(300)), *_ts(),
        sa.CheckConstraint(_in("source", SOURCES), name="ck_mkt_booking_source"),
        sa.CheckConstraint(_in("status", STATUSES), name="ck_mkt_booking_status"),
        sa.CheckConstraint(_in("payment_status", PAYMENT_STATUSES), name="ck_mkt_booking_payment_status"),
        sa.CheckConstraint(_in("settlement_mode", ("operator_collects", "platform_collects")), name="ck_mkt_booking_settlement"),
        sa.UniqueConstraint("customer_id", "idempotency_key", name="uq_mkt_booking_idempotency"))
    op.create_index("ix_marketplace_bookings_code", "marketplace_bookings", ["code"], unique=True)
    for col in ("listing_id", "customer_id", "room_booking_id", "start_at", "expires_at"):
        op.create_index(f"ix_marketplace_bookings_{col}", "marketplace_bookings", [col])
    op.create_index("ix_mkt_booking_slot", "marketplace_bookings", ["listing_id", "start_at", "end_at"])

    op.create_table(
        "commission_ledger",
        sa.Column("id", sa.Integer(), primary_key=True), _op(),
        sa.Column("booking_id", sa.Integer(), sa.ForeignKey("marketplace_bookings.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("entry_type", sa.String(12), nullable=False), sa.Column("gross_amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("commission_pct", sa.Numeric(5, 2), nullable=False), sa.Column("amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("note", sa.String(300)), sa.Column("invoiced_in", sa.String(40)), *_ts(),
        sa.CheckConstraint(_in("entry_type", ("accrual", "reversal", "adjustment")), name="ck_commission_entry_type"))
    op.create_index("ix_commission_ledger_booking_id", "commission_ledger", ["booking_id"])


def downgrade():
    op.drop_table("commission_ledger")
    op.drop_table("marketplace_bookings")
    op.drop_table("marketplace_listings")
    op.drop_table("marketplace_customers")
    op.drop_table("operator_marketplace_terms")
    for table in ("day_passes", "seat_bookings", "room_bookings"):
        op.drop_column(table, "booking_source")
