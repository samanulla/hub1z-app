from .routes import admin_bp
from .staff_routes import register_staff_routes
from .expense_routes import register_expense_routes
from .billing_routes import register_billing_routes
from .email_routes import register_email_template_routes
from .report_routes import register_report_routes
from .settings_routes import register_settings_routes
from .audit_routes import register_audit_routes
from .invite_routes import register_invite_routes
from .subscription_routes import register_subscription_routes
from .credits_routes import register_credit_routes
from .agreement_routes import register_agreement_routes
from .attendance_routes import register_attendance_routes
from ..lead_routes import register_lead_routes
from ...utils.decorators import admin_required

register_staff_routes(admin_bp)
register_expense_routes(admin_bp)
register_billing_routes(admin_bp)
register_email_template_routes(admin_bp)
register_report_routes(admin_bp)
register_settings_routes(admin_bp)
register_audit_routes(admin_bp)
register_invite_routes(admin_bp)
register_subscription_routes(admin_bp)
register_credit_routes(admin_bp)
register_agreement_routes(admin_bp)
register_attendance_routes(admin_bp)
register_lead_routes(admin_bp, "operator", admin_required)

__all__ = ["admin_bp"]
