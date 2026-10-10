"""Platform control of the operator marketplace: who is approved, at what commission, partner applications, invoices."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from flask import abort, current_app, flash, redirect, render_template, request, url_for

from ...extensions import db
from ...models import (
    CommissionLedgerEntry, MarketplacePartnerApplication, Operator, OperatorMarketplaceTerms, OperatorStatus,
    PlatformInvoice,
)
from ...services import audit_service, mail_service
from ...services import marketplace_commission as commission
from ...services import marketplace_partner as partners
from ...services.marketplace import MarketplaceError
from ...utils.decorators import platform_permission_required


def register_marketplace_routes(bp):

    def _gate():
        if not current_app.config.get("MARKETPLACE_ENABLED"):
            abort(404)

    def _pct(raw, default):
        try:
            value = Decimal(raw)
        except Exception:  # noqa: BLE001 - any malformed number falls back to the default
            return default
        return value if Decimal(0) <= value <= Decimal(30) else default

    @bp.route("/marketplace")
    @platform_permission_required("operators")
    def marketplace():
        _gate()
        operators = (Operator.query.execution_options(skip_operator_filter=True)
                     .filter(Operator.status.in_((OperatorStatus.ACTIVE, OperatorStatus.TRIAL)))
                     .order_by(Operator.name).all())
        terms = {t.operator_id: t for t in OperatorMarketplaceTerms.query.execution_options(
            skip_operator_filter=True).all()}
        rows = [{"operator": o, "terms": terms.get(o.id), "pending": commission.pending_total(o.id),
                 "partner": partners.is_marketplace_partner(o)} for o in operators]
        applications = (MarketplacePartnerApplication.query.order_by(MarketplacePartnerApplication.created_at.desc())
                        .limit(50).all())
        invoices = (PlatformInvoice.query.execution_options(skip_operator_filter=True)
                    .filter_by(kind="commission").order_by(PlatformInvoice.created_at.desc()).limit(15).all())
        return render_template("platform/marketplace.html", rows=rows, applications=applications, invoices=invoices,
                               month=commission.previous_month())

    @bp.route("/marketplace/operators/<int:operator_id>", methods=["POST"])
    @platform_permission_required("operators")
    def marketplace_operator(operator_id):
        _gate()
        operator = Operator.query.execution_options(skip_operator_filter=True).filter_by(id=operator_id).first()
        if operator is None:
            abort(404)
        terms = OperatorMarketplaceTerms.query.execution_options(skip_operator_filter=True).filter_by(
            operator_id=operator_id).first() or OperatorMarketplaceTerms(operator_id=operator_id)
        approved = request.form.get("approved") == "1"
        pct = _pct(request.form.get("commission_pct", ""), terms.commission_pct or Decimal("10"))
        if pct != terms.commission_pct:
            terms.effective_from = datetime.utcnow()
        terms.commission_pct = pct
        terms.kyc_approved = approved
        db.session.add(terms)
        audit_service.record("marketplace.terms", "operator", operator_id, {"approved": approved, "commission_pct": str(pct)})
        db.session.commit()
        flash(f"{operator.name}: {'approved' if approved else 'not approved'} at {pct}% commission.", "success")
        return redirect(url_for("platform.marketplace"))

    @bp.route("/marketplace/applications/<int:application_id>/<action>", methods=["POST"])
    @platform_permission_required("operators")
    def marketplace_application(application_id, action):
        _gate()
        application = db.session.get(MarketplacePartnerApplication, application_id)
        if application is None:
            abort(404)
        if action == "reject":
            if application.status == "pending":
                application.status = "rejected"
                db.session.commit()
                flash("Application declined.", "success")
            return redirect(url_for("platform.marketplace"))
        if action != "approve":
            abort(404)
        try:
            operator, owner = partners.provision(application, _pct(request.form.get("commission_pct", ""), Decimal("12")))
            db.session.commit()
        except MarketplaceError as e:
            db.session.rollback()
            flash(str(e), "warning")
            return redirect(url_for("platform.marketplace"))
        token = mail_service.make_token(owner.id, "platform-operator-invite")
        mail_service.send(subject=f"{operator.name} is approved to list on Hub1z", recipient=owner.email,
                          template="platform_operator_invite", user=owner, operator=operator,
                          accept_url=url_for("platform.operator_accept_invite", token=token, _external=True),
                          ttl_days=partners.INVITE_TTL_SECONDS // 86400)
        audit_service.record("marketplace.partner_approved", "operator", operator.id, {"email": owner.email})
        flash(f"{operator.name} approved. An invitation was sent to {owner.email}.", "success")
        return redirect(url_for("platform.marketplace"))

    @bp.route("/marketplace/invoices", methods=["POST"])
    @platform_permission_required("billing")
    def marketplace_invoices():
        _gate()
        try:
            month = date.fromisoformat((request.form.get("month") or "") + "-01")
        except ValueError:
            flash("Choose a month.", "warning")
            return redirect(url_for("platform.marketplace"))
        made = commission.generate_invoices(month)
        flash(f"Raised {len(made)} commission invoice(s) for {month:%B %Y}." if made
              else f"Nothing to invoice for {month:%B %Y}.", "success")
        return redirect(url_for("platform.marketplace"))
