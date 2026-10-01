"""Small counts shown as badges in the left menu, worked out once per request."""
from __future__ import annotations

from flask import current_app, g
from flask_login import current_user

from ..models import Parcel, PlatformPaymentReport, UserRole
from ..models.parcel import WAITING


def nav_badges() -> dict:
    cached = getattr(g, "_nav_badges", None)
    if cached is not None:
        return cached
    out: dict[str, int] = {}
    try:
        if not current_user.is_authenticated:
            pass
        elif current_user.is_platform_staff:
            if current_user.has_platform_permission("billing"):
                out["finance"] = PlatformPaymentReport.query.filter_by(status="pending").count()
        elif getattr(g, "operator_id", None) is None:
            pass
        elif current_user.is_admin:
            from .alerts import operator_alerts

            out["alerts"] = len(operator_alerts(g.operator_id))
            out["parcels"] = Parcel.query.filter_by(operator_id=g.operator_id, status=WAITING).count()
        elif current_user.role == UserRole.COMPANY_ADMIN:
            out["parcels"] = Parcel.query.filter_by(company_id=current_user.company_id, status=WAITING).count()
        else:
            out["parcels"] = Parcel.query.filter_by(user_id=current_user.id, status=WAITING).count()
    except Exception:  # a badge must never break the page
        current_app.logger.exception("nav badges failed")
    g._nav_badges = out
    return out
