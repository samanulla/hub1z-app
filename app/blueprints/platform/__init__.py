from .routes import platform_bp
from .team_routes import register_team_routes
from .reports_routes import register_reports_routes
from .billing_routes import register_billing_routes
from .invite_routes import register_invite_routes
from .tiers_routes import register_tiers_routes
from .document_routes import register_document_routes
from .finance_routes import register_finance_routes
from .attendance_routes import register_attendance_routes
from .marketplace_routes import register_marketplace_routes
from ..lead_routes import register_lead_routes
from ...utils.decorators import platform_permission_required

register_team_routes(platform_bp)
register_reports_routes(platform_bp)
register_billing_routes(platform_bp)
register_invite_routes(platform_bp)
register_tiers_routes(platform_bp)
register_document_routes(platform_bp)
register_finance_routes(platform_bp)
register_attendance_routes(platform_bp)
register_marketplace_routes(platform_bp)
register_lead_routes(platform_bp, "platform", platform_permission_required("leads"))

__all__ = ["platform_bp"]
