"""platform-level invoices, credit notes, refunds, expenses (operator billing)

Revision ID: f6a7b8c9d0e1
Revises: f5e6f7a8b9c0
"""
from alembic import op
import sqlalchemy as sa


revision = "f6a7b8c9d0e1"
down_revision = "f5e6f7a8b9c0"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "platform_invoices",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("number", sa.String(length=30), nullable=False, unique=True),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False, server_default="INR"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="issued"),
        sa.Column("notes", sa.Text(), nullable=True),
    )
    op.create_index("ix_platform_invoices_tenant_id", "platform_invoices", ["tenant_id"])
    op.create_index("ix_platform_invoices_status", "platform_invoices", ["status"])

    op.create_table(
        "platform_credit_notes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("invoice_id", sa.Integer(), sa.ForeignKey("platform_invoices.id", ondelete="SET NULL"), nullable=True),
        sa.Column("number", sa.String(length=30), nullable=False, unique=True),
        sa.Column("amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("reason", sa.String(length=255), nullable=False),
        sa.Column("issued_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_platform_credit_notes_tenant_id", "platform_credit_notes", ["tenant_id"])
    op.create_index("ix_platform_credit_notes_invoice_id", "platform_credit_notes", ["invoice_id"])

    op.create_table(
        "platform_refunds",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("invoice_id", sa.Integer(), sa.ForeignKey("platform_invoices.id", ondelete="SET NULL"), nullable=True),
        sa.Column("number", sa.String(length=30), nullable=False, unique=True),
        sa.Column("amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("reason", sa.String(length=255), nullable=False),
        sa.Column("processed_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_platform_refunds_tenant_id", "platform_refunds", ["tenant_id"])
    op.create_index("ix_platform_refunds_invoice_id", "platform_refunds", ["invoice_id"])

    op.create_table(
        "platform_expenses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("category", sa.String(length=60), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=False),
        sa.Column("amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("incurred_on", sa.Date(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
    )


def downgrade():
    op.drop_table("platform_expenses")
    op.drop_index("ix_platform_refunds_invoice_id", table_name="platform_refunds")
    op.drop_index("ix_platform_refunds_tenant_id", table_name="platform_refunds")
    op.drop_table("platform_refunds")
    op.drop_index("ix_platform_credit_notes_invoice_id", table_name="platform_credit_notes")
    op.drop_index("ix_platform_credit_notes_tenant_id", table_name="platform_credit_notes")
    op.drop_table("platform_credit_notes")
    op.drop_index("ix_platform_invoices_status", table_name="platform_invoices")
    op.drop_index("ix_platform_invoices_tenant_id", table_name="platform_invoices")
    op.drop_table("platform_invoices")
