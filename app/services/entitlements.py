"""One source of truth for paid plans, retained trials and paid add-ons."""
from datetime import date, datetime
import json

from sqlalchemy import func

from ..extensions import db
from ..models import (Document, Lead, OperatorAddon, OperatorStatus, OperatorSubscription,
                      PlatformModule, PlatformProfile, PricingTier, PlatformInvoice, PlatformInvoiceStatus, UserRole)
from .catalog import ALWAYS, ADDON, BY_CODE, LOCKABLE_CODES


def plan_terms(operator):
    if operator is None:
        return {}
    subscription = OperatorSubscription.query.filter_by(operator_id=operator.id).first()
    if subscription and subscription.status == "active" and subscription.tier:
        from .operator_billing import paid_terms
        return paid_terms(subscription)
    trial = operator.status == OperatorStatus.TRIAL or (subscription and subscription.status == "trial")
    profile = PlatformProfile.peek()
    key = (profile.trial_tier_key if profile else "growth") if trial else operator.plan_tier
    tier = PricingTier.query.filter_by(key=key).first()
    if tier:
        from .operator_billing import snapshot
        return snapshot(tier, subscription)
    if trial:
        return {"features": LOCKABLE_CODES, "name": "Growth trial", "storage_mb": 2048}
    return {}


def active_addon(operator, code, today=None):
    if operator is None:
        return None
    return (OperatorAddon.query.join(PlatformModule).filter(
        OperatorAddon.operator_id == operator.id, OperatorAddon.active.is_(True),
        OperatorAddon.paid_through >= (today or date.today()), PlatformModule.code == code,
        PlatformModule.is_active.is_(True), PlatformModule.availability == "available").first())


def legacy_has_feature(operator, code):
    entry = BY_CODE.get(code)
    if entry is None or not entry.built:
        return False
    if entry.kind == ALWAYS:
        return True
    module = PlatformModule.query.filter_by(code=code).first()
    if module and (not module.is_active or module.availability != "available"):
        return False
    if entry.kind == ADDON:
        if active_addon(operator, code) is not None:
            return True
        return code in plan_terms(operator).get("included_addons", [])
    terms = plan_terms(operator)
    return bool(terms.get("all_features") or code in terms.get("features", []))


def has_feature(operator, code):
    """Compatibility adapter; optional shadow checks never change legacy access."""
    from flask import current_app, has_app_context

    legacy_allowed = legacy_has_feature(operator, code)
    if operator is None or not has_app_context():
        return legacy_allowed
    shadow = current_app.config.get("ENTITLEMENTS_SHADOW_ENABLED", False)
    enforcing = current_app.config.get("ENTITLEMENTS_ENFORCEMENT_ENABLED", False)
    if not shadow and not enforcing:
        return legacy_allowed
    from .entitlement_resolver import check_entitlement
    decision = check_entitlement(operator.id, code)
    return decision.allowed if enforcing else legacy_allowed


def storage_used(operator_id):
    return (db.session.query(func.coalesce(func.sum(Document.size_bytes), 0))
            .execution_options(skip_operator_filter=True).filter(Document.operator_id == operator_id).scalar())


def open_manual_leads(operator_id):
    return Lead.query.execution_options(skip_operator_filter=True).filter(
        Lead.operator_id == operator_id, Lead.stage.notin_(("won", "lost")),
        Lead.is_website_enquiry.is_(False)).count()


def storage_limit_mb(operator):
    terms = plan_terms(operator)
    subscription = OperatorSubscription.query.filter_by(operator_id=operator.id).first()
    if subscription and subscription.scheduled_terms and subscription.scheduled_terms.get("storage_mb") is not None:
        terms = dict(terms)
        pending_limit = subscription.scheduled_terms["storage_mb"]
        terms["storage_mb"] = min(terms["storage_mb"], pending_limit) if terms.get("storage_mb") is not None else pending_limit
        terms["all_features"] = False
    if terms.get("all_features") or terms.get("storage_mb") is None:
        return None
    addon = active_addon(operator, "extra_storage")
    return terms["storage_mb"] + (addon.quantity * 5 * 1024 if addon else 0)


def billing_banner(operator, user):
    from flask import session
    if operator is not None and operator.plan_tier == "marketplace_partner":
        return None
    if (not user.is_authenticated or not operator or user.operator_id != operator.id
            or user.role not in (UserRole.SUPER_ADMIN, UserRole.MANAGER, UserRole.LOCATION_MANAGER)
            or session.get("billing_banner_dismissed")):
        return None
    subscription = OperatorSubscription.query.filter_by(operator_id=operator.id).first()
    unpaid = PlatformInvoice.query.filter_by(operator_id=operator.id).filter(
        PlatformInvoice.status.in_((PlatformInvoiceStatus.ISSUED, PlatformInvoiceStatus.OVERDUE))).first()
    if unpaid:
        message = "A Hub1z invoice is awaiting payment. Your workspace access continues."
    elif operator.status == OperatorStatus.TRIAL or not subscription or subscription.status == "trial":
        if operator.trial_ends_at and operator.trial_ends_at > datetime.utcnow():
            message = f"Your trial ends on {operator.trial_ends_at:%d %b %Y}."
        else:
            message = "Your trial has ended. Trial features and workspace access continue until you choose a paid plan."
    elif subscription.current_period_end and subscription.current_period_end < date.today():
        message = "Your plan is awaiting renewal. Your workspace access continues."
    else:
        return None
    return {"message": message, "owner": user.role == UserRole.SUPER_ADMIN}


def install(app):
    from flask import abort, g, render_template, request
    from flask_login import current_user
    from .operator_quotas import QuotaExceeded

    @app.errorhandler(QuotaExceeded)
    def quota_exceeded(error):
        db.session.rollback()
        return render_template("admin/upgrade_required.html", feature=str(error)), 403

    @app.before_request
    def enforce_feature_access():
        operator = getattr(g, "operator", None)
        endpoint = request.endpoint or ""
        if not operator or not current_user.is_authenticated or current_user.is_platform_staff:
            return None
        feature = None
        if endpoint.startswith(("admin.payroll", "admin.salary", "admin.payslip")):
            feature = "payroll"
        elif endpoint.startswith("admin.expense"):
            feature = "expenses"
        else:
            feature = {"admin.attendance_screen": "rotating_qr_screen", "admin.attendance_export": "attendance_export",
                       "admin.leads_export": "lead_export", "admin.audit_log_csv": "audit_export",
                       "admin.report_people": "advanced_reports", "admin.report_heatmap": "advanced_reports"}.get(endpoint)
        if endpoint == "admin.attendance_qr_png" and request.args.get("rotating") == "1":
            feature = "rotating_qr_screen"
        if endpoint in ("admin.subscription_address_letter", "company.address_letter", "member.address_letter"):
            feature = "virtual_office"
        if endpoint in ("admin.plan_new", "admin.plan_edit") and request.method == "POST" and request.form.get("plan_type") == "virtual_office":
            feature = "virtual_office"
        if feature and not has_feature(operator, feature):
            if current_user.is_admin:
                return render_template("admin/upgrade_required.html", feature=BY_CODE[feature].name), 403
            abort(403)
        return None