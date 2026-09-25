"""document ownership metadata and scoped storage buckets

Revision ID: f3c4d5e6f7a8
Revises: f2b3c4d5e6f7
"""
from alembic import op
import sqlalchemy as sa


revision = "f3c4d5e6f7a8"
down_revision = "f2b3c4d5e6f7"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("documents") as batch_op:
        batch_op.add_column(sa.Column("owner_type", sa.String(length=30), nullable=True))
        batch_op.add_column(sa.Column("owner_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("storage_bucket", sa.String(length=255), nullable=True))
        batch_op.create_index("ix_documents_owner_type", ["owner_type"], unique=False)
        batch_op.create_index("ix_documents_owner_id", ["owner_id"], unique=False)

    op.execute("UPDATE documents SET owner_type = CASE WHEN tenant_id IS NULL THEN 'platform' ELSE 'operator' END WHERE owner_type IS NULL")
    op.execute("""
        UPDATE documents d
        SET owner_type = 'company', owner_id = cd.company_id
        FROM company_documents cd
        WHERE cd.document_id = d.id
    """)

    with op.batch_alter_table("documents") as batch_op:
        batch_op.alter_column("owner_type", existing_type=sa.String(length=30), nullable=False,
                              server_default="operator")


def downgrade():
    with op.batch_alter_table("documents") as batch_op:
        batch_op.drop_index("ix_documents_owner_id")
        batch_op.drop_index("ix_documents_owner_type")
        batch_op.drop_column("storage_bucket")
        batch_op.drop_column("owner_id")
        batch_op.drop_column("owner_type")
