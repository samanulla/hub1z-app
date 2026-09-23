"""Platform reports: cross-tenant analytics (gated by the 'reports' feature)."""
from __future__ import annotations

from datetime import date

from flask import render_template
from sqlalchemy import func

from ...extensions import db
from ...models import Tenant, TenantStatus, User, UserRole, Company
from ...utils.decorators import platform_permission_required


def register_reports_routes(bp):

    @bp.route("/reports")
    @platform_permission_required("reports")
    def reports():
        q = lambda model: model.query.execution_options(skip_tenant_filter=True)

        by_status = dict(
            q(Tenant).with_entities(Tenant.status, func.count())
            .group_by(Tenant.status).all()
        )
        status_counts = {s.value: by_status.get(s, 0) for s in TenantStatus}

        # Tenants provisioned per month, last 6 months.
        months = []
        today = date.today().replace(day=1)
        for i in range(5, -1, -1):
            m = (today.year, today.month)
            for _ in range(i):
                m = (m[0] - 1, 12) if m[1] == 1 else (m[0], m[1] - 1)
            months.append(m)
        growth = {f"{y:04d}-{m:02d}": 0 for y, m in months}
        window_start = date(months[0][0], months[0][1], 1)
        tenants = q(Tenant).filter(Tenant.created_at >= window_start).all()
        for t in tenants:
            key = t.created_at.strftime("%Y-%m")
            if key in growth:
                growth[key] += 1

        top_tenants = (
            q(User).with_entities(User.tenant_id, func.count().label("n"))
            .filter(User.tenant_id.isnot(None))
            .group_by(User.tenant_id).order_by(func.count().desc()).limit(5).all()
        )
        tenant_names = {t.id: t.name for t in q(Tenant).all()}
        top_tenants_named = [(tenant_names.get(tid, f"#{tid}"), n) for tid, n in top_tenants]

        stats = {
            "total_tenants": q(Tenant).count(),
            "status_counts": status_counts,
            "growth": growth,
            "top_tenants": top_tenants_named,
            "total_companies": q(Company).count(),
            "custom_domain_count": q(Tenant).filter(Tenant.custom_domain.isnot(None)).count(),
        }
        return render_template("platform/reports.html", stats=stats)
