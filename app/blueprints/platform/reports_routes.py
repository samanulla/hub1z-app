"""Platform reports: cross-operator analytics (gated by the 'reports' feature)."""
from __future__ import annotations

from datetime import date

from flask import render_template
from sqlalchemy import func

from ...extensions import db
from ...models import (
    Operator, OperatorStatus, User, UserRole, Company, PricingTier,
    PlatformInvoice, PlatformInvoiceStatus, PlatformCreditNote, PlatformRefund,
)
from ...utils.decorators import platform_permission_required


def register_reports_routes(bp):

    @bp.route("/reports")
    @platform_permission_required("reports")
    def reports():
        q = lambda model: model.query.execution_options(skip_operator_filter=True)

        by_status = dict(
            q(Operator).with_entities(Operator.status, func.count())
            .group_by(Operator.status).all()
        )
        status_counts = {s.value: by_status.get(s, 0) for s in OperatorStatus}

        # Operators provisioned per month, last 6 months.
        months = []
        today = date.today().replace(day=1)
        for i in range(5, -1, -1):
            m = (today.year, today.month)
            for _ in range(i):
                m = (m[0] - 1, 12) if m[1] == 1 else (m[0], m[1] - 1)
            months.append(m)
        growth = {f"{y:04d}-{m:02d}": 0 for y, m in months}
        window_start = date(months[0][0], months[0][1], 1)
        operators = q(Operator).filter(Operator.created_at >= window_start).all()
        for t in operators:
            key = t.created_at.strftime("%Y-%m")
            if key in growth:
                growth[key] += 1

        top_operators = (
            q(User).with_entities(User.operator_id, func.count().label("n"))
            .filter(User.operator_id.isnot(None))
            .group_by(User.operator_id).order_by(func.count().desc()).limit(5).all()
        )
        operator_names = {t.id: t.name for t in q(Operator).all()}
        top_operators_named = [(operator_names.get(tid, f"#{tid}"), n) for tid, n in top_operators]

        # Subscription mix — only operators are subscribers to the platform.
        tier_names = {t.key: t.name for t in PricingTier.query.all()}
        by_tier_raw = dict(
            q(Operator).with_entities(Operator.plan_tier, func.count())
            .group_by(Operator.plan_tier).all()
        )
        subscription_mix = [(tier_names.get(key, key or "\u2014"), n) for key, n in by_tier_raw.items()]

        # Platform<->operator payments (see app/models/platform_billing.py).
        total_invoiced = PlatformInvoice.query.with_entities(func.coalesce(func.sum(PlatformInvoice.amount), 0)).scalar()
        total_paid = (PlatformInvoice.query
                     .filter_by(status=PlatformInvoiceStatus.PAID)
                     .with_entities(func.coalesce(func.sum(PlatformInvoice.amount), 0)).scalar())
        outstanding = (PlatformInvoice.query
                      .filter(PlatformInvoice.status.in_([PlatformInvoiceStatus.ISSUED, PlatformInvoiceStatus.OVERDUE]))
                      .with_entities(func.coalesce(func.sum(PlatformInvoice.amount), 0)).scalar())
        total_credited = PlatformCreditNote.query.with_entities(func.coalesce(func.sum(PlatformCreditNote.amount), 0)).scalar()
        total_refunded = PlatformRefund.query.with_entities(func.coalesce(func.sum(PlatformRefund.amount), 0)).scalar()
        recent_invoices = (PlatformInvoice.query.order_by(PlatformInvoice.created_at.desc())
                          .limit(10).all())

        stats = {
            "total_operators": q(Operator).count(),
            "status_counts": status_counts,
            "growth": growth,
            "top_operators": top_operators_named,
            "total_companies": q(Company).count(),
            "custom_domain_count": q(Operator).filter(Operator.custom_domain.isnot(None)).count(),
            "subscription_mix": subscription_mix,
            "total_invoiced": total_invoiced,
            "total_paid": total_paid,
            "outstanding": outstanding,
            "total_credited": total_credited,
            "total_refunded": total_refunded,
            "recent_invoices": recent_invoices,
        }
        return render_template("platform/reports.html", stats=stats)
