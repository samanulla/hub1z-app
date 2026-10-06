"""Pricing catalog, tier limits, plan settings and platform tax profile

Revision ID: b8d3f6a2c914
Revises: e5c7a2d91f03
Create Date: 2026-10-05 10:00:00.000000

"""
from datetime import datetime

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'b8d3f6a2c914'
down_revision = 'e5c7a2d91f03'
branch_labels = None
depends_on = None

_CATALOG = [
    ('bookings', 'Bookings', 'always', '', 'available', None),
    ('calendar', 'Calendar', 'always', '', 'available', None),
    ('meeting_credits', 'Meeting room credits', 'always', '', 'available', None),
    ('gst_invoices', 'GST invoices', 'always', '', 'available', None),
    ('pdf_documents', 'PDF documents', 'always', '', 'available', None),
    ('upi_payments', 'UPI QR payments with manual confirmation', 'always', '', 'available', None),
    ('location_qr_checkin', 'Location QR check-in', 'always', '', 'available', None),
    ('member_app', 'Member mobile app', 'always', '', 'available', None),
    ('parcels', 'Parcels', 'always', '', 'available', None),
    ('inapp_alerts', 'In-app alerts', 'always', '', 'available', None),
    ('leads', 'Leads', 'always', '', 'available', None),
    ('lead_email_alerts', 'Email lead notifications', 'always', '', 'available', None),
    ('basic_reports', 'Basic reports', 'always', '', 'available', None),
    ('rotating_qr_screen', 'Rotating reception QR screen', 'feature',
    'A reception display with a QR code that changes every few minutes.', 'available', None),
    ('attendance_reports', 'Attendance reports', 'feature',
    'Attendance history beyond the last 7 days.', 'available', None),
    ('attendance_export', 'Attendance CSV export', 'feature', 'Download attendance as a CSV file.', 'available', None),
    ('lead_export', 'Lead export', 'feature', 'Download leads as a CSV file.', 'available', None),
    ('advanced_reports', 'Advanced reporting', 'feature',
    'People and heatmap reports, plus new advanced reports as they ship.', 'available', None),
    ('alert_digests', 'Alert email digests', 'feature',
    'Emailed digests of parcels, agreements and overdue invoices.', 'available', None),
    ('payment_reminders', 'Payment reminders', 'feature',
    'Automatic reminder emails to customers with unpaid invoices.', 'available', None),
    ('payroll', 'Payroll', 'feature', 'Salary structures, payroll runs and payslips.', 'available', None),
    ('expenses', 'Expenses', 'feature', 'Expense tracking and approvals.', 'available', None),
    ('audit_export', 'Audit log exports', 'feature', 'Download the audit log as a CSV file.', 'available', None),
    ('virtual_office', 'Virtual Office & NOC', 'addon',
    'Virtual office plans and NOC / address letters for customers.', 'available', None),
    ('white_label', 'White Label', 'addon',
    'Your own domain and no Hub1z branding on your portal.', 'available', None),
    ('extra_storage', 'Extra Storage', 'addon',
    'More document storage on top of the plan allowance.', 'available', 'per 5 GB'),
    ('accounting_sync', 'Accounting Sync', 'addon',
    'Sync invoices and payments to your accounting software.', 'coming_soon', None),
    ('api_webhooks', 'API & Webhooks', 'addon',
    'API keys and webhooks to connect your own tools.', 'coming_soon', None),
    ('gst_einvoicing', 'GST E-Invoicing', 'addon',
    'Generate IRN and QR codes through the GST e-invoice portal.', 'coming_soon', None),
    ('featured_listing', 'Featured Listing', 'addon',
    'Be featured in the Hub1z space directory.', 'coming_soon', None),
    ('online_payments', 'Online Payments (Razorpay)', 'addon',
    'Collect cards, netbanking and UPI with automatic confirmation.', 'coming_soon', None),
    ('whatsapp_packs', 'WhatsApp Messaging Packs', 'addon',
    'Send reminders and alerts on WhatsApp.', 'coming_soon', None),
    ('pan_verification', 'PAN verification', 'usage',
    'Live PAN check against government records.', 'coming_soon', 'per verification'),
    ('gstin_verification', 'GSTIN verification', 'usage',
    'Live GSTIN check against the GST portal.', 'coming_soon', 'per verification'),
]

_TIERS = [
    dict(key='starter', name='Starter', description='Get running quickly with everything a single space needs.',
        sort_order=10, max_locations=1, max_staff_users=3, max_open_leads=100, storage_mb=500),
    dict(key='growth', name='Growth', description='Multiple locations, attendance, payroll and advanced reporting.',
        sort_order=20, is_highlighted=True, storage_mb=2048),
    dict(key='enterprise', name='Enterprise', description='Large chains and custom contracts.',
        sort_order=30, contact_sales=True, all_features=True),
]


def _flag(name):
    return sa.Column(name, sa.Boolean(), nullable=False, server_default=sa.false())


def upgrade():
    with op.batch_alter_table('pricing_tiers') as batch:
        batch.add_column(sa.Column('description', sa.String(length=200), nullable=True))
        batch.add_column(sa.Column('sort_order', sa.Integer(), nullable=False, server_default='0'))
        batch.add_column(_flag('is_public'))
        batch.add_column(_flag('is_highlighted'))
        batch.add_column(_flag('contact_sales'))
        batch.add_column(_flag('all_features'))
        batch.add_column(sa.Column('max_staff_users', sa.Integer(), nullable=True))
        batch.add_column(sa.Column('max_open_leads', sa.Integer(), nullable=True))
        batch.add_column(sa.Column('storage_mb', sa.Integer(), nullable=True))
        batch.alter_column('trial_period_days', existing_type=sa.Integer(), server_default='0')

    with op.batch_alter_table('platform_modules') as batch:
        batch.add_column(sa.Column('description', sa.String(length=300), nullable=True))
        batch.add_column(sa.Column('unit_price', sa.Numeric(precision=10, scale=2), nullable=True))
        batch.add_column(sa.Column('unit_label', sa.String(length=40), nullable=True))
        batch.add_column(sa.Column('availability', sa.String(length=12), nullable=False, server_default='available'))
        batch.add_column(sa.Column('sort_order', sa.Integer(), nullable=False, server_default='0'))

    with op.batch_alter_table('platform_profile') as batch:
        batch.add_column(sa.Column('gst_state', sa.String(length=2), nullable=True))
        batch.add_column(sa.Column('default_gst_rate', sa.Numeric(precision=5, scale=2), nullable=False, server_default='18'))
        batch.add_column(sa.Column('sac_code', sa.String(length=10), nullable=True))
        batch.add_column(sa.Column('invoice_prefix', sa.String(length=10), nullable=False, server_default='H1Z'))
        batch.add_column(sa.Column('payment_terms_days', sa.Integer(), nullable=False, server_default='7'))
        batch.add_column(sa.Column('trial_days', sa.Integer(), nullable=True))
        batch.add_column(sa.Column('trial_tier_key', sa.String(length=30), nullable=False, server_default='growth'))
        batch.add_column(sa.Column('renewal_notice_days', sa.Integer(), nullable=False, server_default='7'))
        batch.add_column(_flag('pricing_page_public'))

    bind = op.get_bind()
    # Tiers that were already on the public page keep showing once the page itself is switched on.
    bind.execute(sa.text("UPDATE pricing_tiers SET is_public = :on WHERE is_active = :on AND key != 'scale'")
                 .bindparams(on=True))
    # What used to be a priced "module" is now an add-on.
    bind.execute(sa.text("UPDATE platform_modules SET kind = 'addon' WHERE kind = 'module'"))

    _seed_catalog(bind)
    _seed_tiers(bind)


def _seed_catalog(bind):
    modules = sa.table(
        'platform_modules',
        sa.column('code', sa.String), sa.column('name', sa.String), sa.column('description', sa.String),
        sa.column('monthly_price', sa.Numeric), sa.column('unit_label', sa.String), sa.column('kind', sa.String),
        sa.column('availability', sa.String), sa.column('sort_order', sa.Integer), sa.column('is_active', sa.Boolean),
        sa.column('created_at', sa.DateTime), sa.column('updated_at', sa.DateTime),
    )
    existing = {code for (code,) in bind.execute(sa.text("SELECT code FROM platform_modules"))}
    now = datetime.utcnow()
    rows = [dict(code=code, name=name, description=description, monthly_price=0,
                 unit_label=unit_label, kind=kind, availability=availability,
                 sort_order=order * 10, is_active=True, created_at=now, updated_at=now)
            for order, (code, name, kind, description, availability, unit_label) in enumerate(_CATALOG, start=1)
            if code not in existing]
    if rows:
        op.bulk_insert(modules, rows)
    for order, (code, name, kind, description, availability, unit_label) in enumerate(_CATALOG, start=1):
        if code not in existing:
            continue
        bind.execute(sa.text("UPDATE platform_modules SET kind = :kind, description = :description, "
                             "availability = :availability, unit_label = :unit_label, sort_order = :sort_order "
                             "WHERE code = :code"),
                     dict(code=code, kind=kind, description=description, availability=availability,
                          unit_label=unit_label, sort_order=order * 10))


def _seed_tiers(bind):
    overage = sa.Enum('ALLOW_AND_CHARGE', 'BLOCK_ADDITIONAL_USAGE', 'REQUIRE_PLAN_UPGRADE', 'CUSTOM_APPROVAL',
                      name='overagepolicy', create_type=False)
    tiers = sa.table(
        'pricing_tiers',
        sa.column('key', sa.String), sa.column('name', sa.String), sa.column('description', sa.String),
        sa.column('sort_order', sa.Integer), sa.column('annual_discount', sa.Numeric),
        sa.column('is_active', sa.Boolean),
        sa.column('status', sa.Enum('DRAFT', 'ACTIVE', 'INACTIVE', name='tierstatus', create_type=False)),
        sa.column('is_public', sa.Boolean), sa.column('is_highlighted', sa.Boolean),
        sa.column('contact_sales', sa.Boolean), sa.column('all_features', sa.Boolean),
        sa.column('max_locations', sa.Integer), sa.column('max_staff_users', sa.Integer),
        sa.column('max_open_leads', sa.Integer), sa.column('storage_mb', sa.Integer),
        sa.column('additional_seat_rate', sa.Numeric), sa.column('additional_location_rate', sa.Numeric),
        sa.column('seat_overage_policy', overage), sa.column('location_overage_policy', overage),
        sa.column('seat_usage_method', sa.Enum('MAXIMUM_DURING_BILLING_PERIOD', 'AVERAGE_DAILY_USAGE',
                                               'END_OF_PERIOD_USAGE', name='seatusagemethod', create_type=False)),
        sa.column('pricing_version', sa.Integer),
        sa.column('created_at', sa.DateTime), sa.column('updated_at', sa.DateTime),
    )
    existing = {key for (key,) in bind.execute(sa.text("SELECT key FROM pricing_tiers"))}
    now = datetime.utcnow()
    created = [t for t in _TIERS if t['key'] not in existing]
    # Drafts with no price: Platform admin sets prices and publishes them.
    rows = [dict(
        key=t['key'], name=t['name'], description=t['description'], sort_order=t['sort_order'],
        annual_discount=0, is_active=False, status='DRAFT', is_public=False,
        is_highlighted=t.get('is_highlighted', False), contact_sales=t.get('contact_sales', False),
        all_features=t.get('all_features', False), max_locations=t.get('max_locations'),
        max_staff_users=t.get('max_staff_users'), max_open_leads=t.get('max_open_leads'),
        storage_mb=t.get('storage_mb'), additional_seat_rate=0, additional_location_rate=0,
        seat_overage_policy='REQUIRE_PLAN_UPGRADE', location_overage_policy='REQUIRE_PLAN_UPGRADE',
        seat_usage_method='MAXIMUM_DURING_BILLING_PERIOD', pricing_version=1,
        created_at=now, updated_at=now) for t in created]
    if rows:
        op.bulk_insert(tiers, rows)
    for tier in _TIERS:
        bind.execute(sa.text("UPDATE pricing_tiers SET description = :description, sort_order = :sort_order, "
                             "is_highlighted = :is_highlighted, contact_sales = :contact_sales, "
                             "all_features = :all_features, max_staff_users = :max_staff_users, "
                             "max_open_leads = :max_open_leads, storage_mb = :storage_mb WHERE key = :key"),
                     dict(key=tier['key'], description=tier['description'], sort_order=tier['sort_order'],
                          is_highlighted=tier.get('is_highlighted', False), contact_sales=tier.get('contact_sales', False),
                          all_features=tier.get('all_features', False), max_staff_users=tier.get('max_staff_users'),
                          max_open_leads=tier.get('max_open_leads'), storage_mb=tier.get('storage_mb')))

    growth_id = bind.execute(sa.text("SELECT id FROM pricing_tiers WHERE key = 'growth'")).scalar()
    feature_codes = [entry[0] for entry in _CATALOG if entry[2] == 'feature']
    feature_ids = [row[0] for row in bind.execute(
        sa.text("SELECT id FROM platform_modules WHERE code IN :codes AND id NOT IN "
                "(SELECT module_id FROM tier_modules WHERE tier_id = :tier_id)")
        .bindparams(sa.bindparam('codes', expanding=True, value=feature_codes), tier_id=growth_id))]
    links = sa.table('tier_modules', sa.column('tier_id', sa.Integer), sa.column('module_id', sa.Integer))
    if feature_ids:
        op.bulk_insert(links, [dict(tier_id=growth_id, module_id=module_id) for module_id in feature_ids])


def downgrade():
    bind = op.get_bind()
    bind.execute(sa.text("UPDATE platform_modules SET kind = 'module' WHERE kind = 'addon'"))

    with op.batch_alter_table('platform_profile') as batch:
        for column in ('gst_state', 'default_gst_rate', 'sac_code', 'invoice_prefix', 'payment_terms_days',
                       'trial_days', 'trial_tier_key', 'renewal_notice_days', 'pricing_page_public'):
            batch.drop_column(column)

    with op.batch_alter_table('platform_modules') as batch:
        for column in ('description', 'unit_price', 'unit_label', 'availability', 'sort_order'):
            batch.drop_column(column)

    with op.batch_alter_table('pricing_tiers') as batch:
        batch.alter_column('trial_period_days', existing_type=sa.Integer(), server_default=None)
        for column in ('description', 'sort_order', 'is_public', 'is_highlighted', 'contact_sales',
                       'all_features', 'max_staff_users', 'max_open_leads', 'storage_mb'):
            batch.drop_column(column)
