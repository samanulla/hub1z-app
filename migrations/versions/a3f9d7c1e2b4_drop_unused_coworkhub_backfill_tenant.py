"""drop unused coworkhub backfill tenant

The multi-tenant migration (8711d3dcd846) unconditionally inserted a
'coworkhub' tenant on every install, including brand-new ones with nothing
to backfill — leaving a phantom platform-branded tenant that becomes the
default (lowest id) for any request that doesn't match a real tenant's
domain, shadowing whatever tenant `seed-demo` actually creates.

This only removes it where it's provably unused (no rows in any table that
migration could have backfilled reference it) — on a real deployment that
relied on that backfill, the tenant has dependents and is left untouched.

Revision ID: a3f9d7c1e2b4
Revises: b7c1e2a4f6d8
Create Date: 2026-09-20 00:00:00.000000

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = 'a3f9d7c1e2b4'
down_revision = 'b7c1e2a4f6d8'
branch_labels = None
depends_on = None

_BACKFILLED_TABLES = [
    'users', 'companies', 'locations', 'pricing_plans', 'subscriptions',
    'invoices', 'credit_notes', 'expenses', 'expense_categories',
    'staff_members', 'payroll_runs', 'email_templates',
    'documents', 'audit_logs',
]


def upgrade():
    exists_clauses = " OR ".join(
        f"EXISTS (SELECT 1 FROM {tbl} WHERE tenant_id = tenants.id)"
        for tbl in _BACKFILLED_TABLES
    )
    op.execute(f"""
        DELETE FROM tenants
        WHERE slug = 'coworkhub'
          AND NOT ({exists_clauses})
    """)


def downgrade():
    # The row it removed was, by definition, empty/unused — nothing to restore.
    pass
