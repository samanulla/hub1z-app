"""company requests and payment submissions

Revision ID: f8c9d0e1f2a3
Revises: f7b8c9d0e1f2
"""
from alembic import op
import sqlalchemy as sa


revision = "f8c9d0e1f2a3"
down_revision = "f7b8c9d0e1f2"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "subscription_change_requests",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("subscription_id", sa.Integer(), nullable=True),
        sa.Column("requested_plan_id", sa.Integer(), nullable=False),
        sa.Column("requested_quantity", sa.Integer(), nullable=False),
        sa.Column("status", sa.Enum("PENDING", "APPROVED", "DENIED", name="subscriptionrequeststatus"), nullable=False),
        sa.Column("company_message", sa.Text(), nullable=True),
        sa.Column("operator_message", sa.Text(), nullable=True),
        sa.Column("requested_by_id", sa.Integer(), nullable=True),
        sa.Column("reviewed_by_id", sa.Integer(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["requested_plan_id"], ["pricing_plans.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["requested_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["reviewed_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["subscription_id"], ["subscriptions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_subscription_change_requests_tenant_id", "subscription_change_requests", ["tenant_id"])
    op.create_index("ix_subscription_change_requests_company_id", "subscription_change_requests", ["company_id"])
    op.create_index("ix_subscription_change_requests_status", "subscription_change_requests", ["status"])
    op.create_table(
        "payment_submissions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("invoice_id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("paid_on", sa.Date(), nullable=False),
        sa.Column("reference", sa.String(length=120), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("status", sa.Enum("PENDING", "ACCEPTED", "REJECTED", name="paymentsubmissionstatus"), nullable=False),
        sa.Column("operator_message", sa.Text(), nullable=True),
        sa.Column("reviewed_by_id", sa.Integer(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["invoice_id"], ["invoices.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reviewed_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_payment_submissions_tenant_id", "payment_submissions", ["tenant_id"])
    op.create_index("ix_payment_submissions_invoice_id", "payment_submissions", ["invoice_id"])
    op.create_index("ix_payment_submissions_company_id", "payment_submissions", ["company_id"])
    op.create_index("ix_payment_submissions_status", "payment_submissions", ["status"])


def downgrade():
    op.drop_table("payment_submissions")
    op.drop_table("subscription_change_requests")