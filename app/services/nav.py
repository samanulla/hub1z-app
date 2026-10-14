"""Small counts shown as badges in the left menu, worked out once per request."""
from __future__ import annotations

from flask import current_app, g, request, url_for, has_request_context
from flask_login import current_user

from ..models import Invoice, InvoiceStatus, Parcel, PlatformPaymentReport, UserRole
from ..models.parcel import WAITING


def section_navigation():
    if not has_request_context() or not current_user.is_authenticated or current_user.is_platform_staff:
        return None
    endpoint = request.endpoint or ""
    if endpoint.startswith("notifications."):
        return None
    if current_user.is_admin and endpoint.startswith("book."):
        return None  # the Calendar is opened from the top bar and has no tabs of its own
    groups = {}
    if current_user.is_admin:
        groups = {
            "overview": [("Dashboard", "admin.dashboard"), ("Alerts", "admin.alerts")],
            "frontdesk": [("Reception", "community.visitors_reception"), ("Mail & parcels", "admin.parcels"),
                          ("Lockers", "community.lockers"), ("Check-in scan", "admin.attendance_scan")],
            # Customers, Space Setup and Team have no tabs: their pages are siblings in the left menu.
            "customers": [], "space": [], "team": [],
            "passes": [("Day pass", "member.day_passes"), ("Visitor pass", "community.visitors"),
                       ("Guest pass", "community.guest_passes")],
            # Finance tabs only link the pages that belong to one left-menu item.
            "money": [],
            "setup": [("Documents", "admin.operator_documents"), ("Email templates", "admin.email_templates")],
            "community": [("Announcements", "community.announcements"), ("Member directory", "community.directory"),
                          ("Printing credits", "community.printing"), ("Refer & earn", "community.referrals")],
            "marketplace": [("Overview & listings", "admin.marketplace"), ("Bookings", "admin.marketplace_bookings"), ("Commission", "admin.marketplace_commission")],
        }
        if current_user.is_super_admin:
            groups["setup"] = [("Profile", "admin.settings"), ("Home page", "admin.website_settings"),
                               ("Billing", "admin.billing_settings"),
                               ("Documents", "admin.operator_documents"), ("Email templates", "admin.email_templates"),
                               ("Audit log", "admin.audit_log")]
        if endpoint in ("admin.dashboard", "admin.alerts"):
            key = "overview"
        elif endpoint.startswith(("admin.parcel", "admin.attendance_scan", "community.visitors_reception",
                                  "community.lockers", "admin.reception")):
            key = "frontdesk"
        elif endpoint.startswith(("admin.compan", "admin.individual", "admin.invite", "admin.lead",
                                  "admin.subscription")) or endpoint == "admin.people":
            key = "customers"
        elif endpoint.startswith(("admin.staff", "admin.salary", "admin.payroll", "admin.attendance")):
            key = "team"
        elif endpoint.startswith(("admin.invoice", "admin.payment", "admin.credit_note", "admin.refund",
                                  "admin.expense", "admin.report", "admin.billing_run", "admin.hub1z")):
            key = "money"
        elif endpoint.startswith(("admin.operator_documents", "admin.email_template", "admin.audit",
                                  "admin.billing", "admin.website")) or endpoint == "admin.settings":
            key = "setup"
        elif endpoint.startswith("admin.plan"):
            key = "space"
        elif endpoint in ("community.visitors", "community.visitor_check_in", "community.visitor_check_out",
                          "community.guest_passes") or endpoint.startswith("member.day_pass"):
            key = "passes"
        elif endpoint.startswith("admin.marketplace"):
            key = "marketplace"
        elif endpoint.startswith("community."):
            key = "community"
        else:
            key = "space"
        if key == "money":
            if endpoint.startswith(("admin.invoice", "admin.payment", "admin.credit_note", "admin.refund",
                                    "admin.billing_run")):
                groups["money"] = [("Invoices", "admin.invoices_list"), ("Credit notes", "admin.credit_notes"),
                                   ("Refunds", "admin.refunds")]
            elif endpoint.startswith("admin.expense"):
                groups["money"] = [("Expenses", "admin.expenses_list"),
                                   ("Expense categories", "admin.expense_categories")]
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
                          ("Day pass", "member.day_passes"),
                          ("Printing credits", "community.printing"), ("Refer & earn", "community.referrals")]
    if not current_user.is_admin:
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
            out["drafts"] = Invoice.query.filter_by(status=InvoiceStatus.DRAFT).filter(
                Invoice.subscription_id.isnot(None)).count()
        elif current_user.role == UserRole.COMPANY_ADMIN:
            out["parcels"] = Parcel.query.filter_by(company_id=current_user.company_id, status=WAITING).count()
        else:
            out["parcels"] = Parcel.query.filter_by(user_id=current_user.id, status=WAITING).count()
    except Exception:  # a badge must never break the page
        current_app.logger.exception("nav badges failed")
    g._nav_badges = out
    return out
