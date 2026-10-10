"""Small counts shown as badges in the left menu, worked out once per request."""
from __future__ import annotations

from flask import current_app, g, request, url_for, has_request_context
from flask_login import current_user

from ..models import Parcel, PlatformPaymentReport, UserRole
from ..models.parcel import WAITING


def section_navigation():
    if not has_request_context() or not current_user.is_authenticated or current_user.is_platform_staff:
        return None
    endpoint = request.endpoint or ""
    if endpoint.startswith("notifications."):
        return None
    groups = {}
    if current_user.is_admin:
        groups = {
            "overview": [("Dashboard", "admin.dashboard"), ("Alerts", "admin.alerts")],
            "workspace": [("Locations & seats", "admin.locations_list"), ("Book", "book.index"),
                          ("Pricing plans", "admin.plans_list"), ("Credits", "admin.credits_overview"),
                          ("Seat allocations", "admin.allocations"), ("Documents", "admin.operator_documents")],
            "people": [("People", "admin.people"), ("Companies", "admin.companies_list"),
                       ("Individuals", "admin.individuals_list"), ("Staff", "admin.staff_list"),
                       ("Attendance", "admin.attendance"), ("Payroll", "admin.payroll_list")],
            "billing": [("Invoices", "admin.invoices_list"), ("Credit notes", "admin.credit_notes"),
                        ("Refunds", "admin.refunds"), ("Expenses", "admin.expenses_list"),
                        ("Expense categories", "admin.expense_categories")],
            "reports": [("Reports", "admin.reports_home")],
            "marketplace": [("Overview & listings", "admin.marketplace"), ("Bookings", "admin.marketplace_bookings"), ("Commission", "admin.marketplace_commission")],
            "settings": [],
        }
        if current_user.is_manager or current_user.is_super_admin:
            groups["people"].insert(3, ("Invitations", "admin.invites_list"))
        if current_user.is_super_admin:
            groups["billing"] += [("Hub1z invoices", "admin.hub1z_billing"), ("Billing settings", "admin.billing_settings")]
            groups["settings"] = [("Operator profile", "admin.settings"), ("Email templates", "admin.email_templates"), ("Audit log", "admin.audit_log")]
        else:
            groups["settings"] = [("Email templates", "admin.email_templates")]
        if endpoint in ("admin.dashboard", "admin.alerts"):
            key = "overview"
        elif endpoint.startswith(("admin.company", "admin.companies", "admin.individual", "admin.invite", "admin.staff", "admin.salary", "admin.payroll", "admin.attendance")) or endpoint == "admin.people":
            key = "people"
        elif endpoint.startswith(("admin.invoice", "admin.payment", "admin.billing", "admin.hub1z", "admin.credit_note", "admin.refund", "admin.expense")):
            key = "billing"
        elif endpoint.startswith("admin.report"):
            key = "reports"
        elif endpoint.startswith("admin.marketplace"):
            key = "marketplace"
        elif endpoint.startswith(("admin.email_template", "admin.audit")) or endpoint == "admin.settings":
            key = "settings"
        elif endpoint.startswith(("admin.parcel", "admin.reception", "community.", "member.day_pass")):
            key = "services"
        else:
            key = "workspace"
    elif current_user.is_company_admin:
        groups = {
            "overview": [("Dashboard", "company.dashboard")],
            "people": [("People", "company.employees")],
            "workspace": [("Book", "book.index"), ("Seat allocations", "company.allocations"),
                          ("Team activity", "company.bookings"), ("Meeting credits", "company.credits"),
                          ("Documents", "company.documents")],
            "billing": [("Invoices & payments", "company.invoices"), ("Plans & subscriptions", "company.plans"),
                        ("Subscription history", "company.subscriptions")],
        }
        if endpoint.startswith("company.employee"):
            key = "people"
        elif endpoint.startswith(("company.invoice", "company.payment", "company.credit_note")) or endpoint in ("company.plans", "company.subscriptions"):
            key = "billing"
        elif endpoint.startswith(("community.", "member.day_pass")) or endpoint == "company.parcels":
            key = "services"
        elif endpoint == "company.dashboard":
            key = "overview"
        else:
            key = "workspace"
    else:
        return None
    groups["services"] = [("Announcements", "community.announcements"), ("Member directory", "community.directory"),
                          ("Guest passes", "community.guest_passes"), ("Visitors", "community.visitors"),
                          ("Day pass", "member.day_passes"), ("Support tickets", "community.tickets"),
                          ("Printing credits", "community.printing"), ("Refer & earn", "community.referrals")]
    if current_user.is_admin:
        groups["services"] += [("Mail & parcels", "admin.parcels"), ("Lockers", "community.lockers"), ("Reception", "community.visitors_reception")]
    else:
        groups["services"] += [("Mail & parcels", "company.parcels")]
    feature_codes = {"admin.payroll_list": "payroll", "admin.expenses_list": "expenses", "admin.expense_categories": "expenses"}
    items = [{"label": label, "url": url_for(target), "active": endpoint == target,
              "feature": feature_codes.get(target)} for label, target in groups[key]]
    return {"key": key, "items": items}


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
