"""direct tenant scope for booking resources and billing location snapshots

Revision ID: f1a2b3c4d5e6
Revises: e9f2a4c6b8d0, e8acfa92bd79
"""
from alembic import op
import sqlalchemy as sa


revision = "f1a2b3c4d5e6"
down_revision = ("e9f2a4c6b8d0", "e8acfa92bd79")
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("tenants") as batch_op:
        batch_op.add_column(sa.Column("primary_location_id", sa.Integer(), nullable=True))
        batch_op.create_index("ix_tenants_primary_location_id", ["primary_location_id"], unique=False)
        batch_op.create_foreign_key("fk_tenants_primary_location", "locations", ["primary_location_id"], ["id"], ondelete="SET NULL")

    for table, source, source_id in [
        ("floors", "locations", "location_id"),
        ("seats", "locations", "location_id"),
        ("conference_rooms", "locations", "location_id"),
    ]:
        with op.batch_alter_table(table) as batch_op:
            batch_op.add_column(sa.Column("tenant_id", sa.Integer(), nullable=True))
            batch_op.create_index(f"ix_{table}_tenant_id", ["tenant_id"], unique=False)
            batch_op.create_foreign_key(f"fk_{table}_tenant", "tenants", ["tenant_id"], ["id"], ondelete="CASCADE")
        op.execute(
            f"UPDATE {table} SET tenant_id = (SELECT tenant_id FROM {source} WHERE {source}.id = {table}.{source_id}) "
            f"WHERE tenant_id IS NULL"
        )

    for table, resource_table, resource_id in [
        ("seat_bookings", "seats", "seat_id"),
        ("room_bookings", "conference_rooms", "room_id"),
    ]:
        with op.batch_alter_table(table) as batch_op:
            batch_op.add_column(sa.Column("tenant_id", sa.Integer(), nullable=True))
            batch_op.create_index(f"ix_{table}_tenant_id", ["tenant_id"], unique=False)
            batch_op.create_foreign_key(f"fk_{table}_tenant", "tenants", ["tenant_id"], ["id"], ondelete="CASCADE")
            if table == "room_bookings":
                batch_op.add_column(sa.Column("recurring_booking_id", sa.Integer(), nullable=True))
                batch_op.create_index("ix_room_bookings_recurring_booking_id", ["recurring_booking_id"], unique=False)
                batch_op.create_foreign_key("fk_room_bookings_recurring", "recurring_room_bookings", ["recurring_booking_id"], ["id"], ondelete="SET NULL")
        op.execute(
            f"UPDATE {table} SET tenant_id = (SELECT tenant_id FROM {resource_table} WHERE {resource_table}.id = {table}.{resource_id}) "
            f"WHERE tenant_id IS NULL"
        )

    with op.batch_alter_table("invoices") as batch_op:
        batch_op.add_column(sa.Column("subscription_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("billing_name", sa.String(length=200), nullable=True))
        batch_op.add_column(sa.Column("billing_address", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("billing_city", sa.String(length=80), nullable=True))
        batch_op.add_column(sa.Column("billing_state", sa.String(length=80), nullable=True))
        batch_op.add_column(sa.Column("billing_country", sa.String(length=80), nullable=True))
        batch_op.add_column(sa.Column("billing_postal_code", sa.String(length=20), nullable=True))
        batch_op.create_index("ix_invoices_subscription_id", ["subscription_id"], unique=False)
        batch_op.create_foreign_key("fk_invoices_subscription", "subscriptions", ["subscription_id"], ["id"], ondelete="SET NULL")

    op.execute("""
        UPDATE tenants
        SET primary_location_id = (
            SELECT id FROM locations
            WHERE locations.tenant_id = tenants.id
            ORDER BY locations.id LIMIT 1
        )
        WHERE primary_location_id IS NULL
    """)


def downgrade():
    with op.batch_alter_table("invoices") as batch_op:
        batch_op.drop_constraint("fk_invoices_subscription", type_="foreignkey")
        batch_op.drop_index("ix_invoices_subscription_id")
        for column in ("billing_postal_code", "billing_country", "billing_state",
                       "billing_city", "billing_address", "billing_name",
                       "subscription_id"):
            batch_op.drop_column(column)

    for table in ("room_bookings", "seat_bookings"):
        with op.batch_alter_table(table) as batch_op:
            if table == "room_bookings":
                batch_op.drop_constraint("fk_room_bookings_recurring", type_="foreignkey")
                batch_op.drop_index("ix_room_bookings_recurring_booking_id")
                batch_op.drop_column("recurring_booking_id")
            batch_op.drop_constraint(f"fk_{table}_tenant", type_="foreignkey")
            batch_op.drop_index(f"ix_{table}_tenant_id")
            batch_op.drop_column("tenant_id")

    for table in ("conference_rooms", "seats", "floors"):
        with op.batch_alter_table(table) as batch_op:
            batch_op.drop_constraint(f"fk_{table}_tenant", type_="foreignkey")
            batch_op.drop_index(f"ix_{table}_tenant_id")
            batch_op.drop_column("tenant_id")

    with op.batch_alter_table("tenants") as batch_op:
        batch_op.drop_constraint("fk_tenants_primary_location", type_="foreignkey")
        batch_op.drop_index("ix_tenants_primary_location_id")
        batch_op.drop_column("primary_location_id")