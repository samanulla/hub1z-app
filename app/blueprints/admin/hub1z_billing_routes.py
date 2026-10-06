"""What the operator owes Hub1z: the Platform's invoices, credit notes and refunds to this operator, with PDFs,
UPI payment and a way to report a payment for Hub1z to confirm."""
from __future__ import annotations

from datetime import date

from flask import Response, abort, current_app, flash, g, redirect, render_template, url_for, request, session
from flask_login import current_user

from ...extensions import db
from ...models import (PlatformCreditNote, PlatformInvoice, PlatformInvoiceStatus, PlatformPaymentReport,
                       PlatformProfile, PlatformRefund, OperatorSubscription, PricingTier, TierStatus,
                       PlatformModule, OperatorAddon)
from ...services import upi
from ...services import mail_service, operator_billing
from ...services.pdf_docs import (pdf_response, platform_credit_note_context, platform_invoice_context,
                                  platform_refund_context)
from ...utils.decorators import super_admin_required, admin_required

UNPAID = (PlatformInvoiceStatus.ISSUED, PlatformInvoiceStatus.OVERDUE)


def _notify_support(report, invoice) -> None:
    """Tell Hub1z support a payment awaits approval. The report is already saved, so a mail failure is only logged."""
    try:
        mail_service.send(
            f"Payment reported: {g.operator.name} · {invoice.number}", current_app.config["PLATFORM_SUPPORT_EMAIL"],
            "payment_reported", report=report, invoice=invoice, reporter=current_user, reporter_operator=g.operator)
    except Exception:  # noqa: BLE001
        current_app.logger.exception("payment report email failed for invoice %s", invoice.number)


def register_hub1z_billing_routes(bp):
    # Platform billing tables are not auto-scoped, so every query names the operator.

    def _invoice(invoice_id: int) -> PlatformInvoice:
        return PlatformInvoice.query.filter_by(id=invoice_id, operator_id=g.operator_id).first_or_404()

    @bp.route("/hub1z-billing/banner/dismiss", methods=["POST"])
    @admin_required
    def hub1z_banner_dismiss():
        if g.operator_id is None or current_user.operator_id != g.operator_id:
            abort(403)
        session["billing_banner_dismissed"] = True
        target = request.form.get("next", "")
        return redirect(target if target.startswith("/admin/") and not target.startswith("//")
                        else url_for("admin.dashboard"))

    @bp.route("/hub1z-billing/plans", methods=["GET", "POST"])
    @super_admin_required
    def hub1z_plans():
        if g.operator_id is None:
            abort(404)
        if request.method == "POST":
            tier = PricingTier.query.filter_by(id=request.form.get("tier_id", type=int)).first_or_404()
            try:
                invoice = operator_billing.request_plan(g.operator, tier, request.form.get("cycle", "monthly"),
                                                       actor_id=current_user.id)
                db.session.commit()
                flash(f"Invoice {invoice.number} is due now. Your plan changes after payment confirmation."
                      if invoice else "Plan change scheduled for the next renewal.", "success")
                return redirect(url_for("admin.hub1z_billing"))
            except ValueError as error:
                db.session.rollback()
                flash(str(error), "warning")
        tiers = PricingTier.query.filter_by(status=TierStatus.ACTIVE, is_active=True).filter(
            PricingTier.key != "scale").order_by(PricingTier.sort_order).all()
        subscription = OperatorSubscription.query.filter_by(operator_id=g.operator_id).first()
        addons = PlatformModule.query.filter_by(kind="addon", availability="available", is_active=True).order_by(
            PlatformModule.sort_order).all()
        purchased = OperatorAddon.query.filter_by(operator_id=g.operator_id, active=True).all()
        from ...services.entitlements import plan_terms
        from ...services.pricing_page import tier_limit_lines, tier_feature_names
        return render_template("admin/hub1z_plans.html", tiers=tiers, subscription=subscription, addons=addons,
                               purchased=purchased, limits=tier_limit_lines, features=tier_feature_names,
                               included_addons=set(plan_terms(g.operator).get("included_addons", [])))

    @bp.route("/hub1z-billing/addons/<int:module_id>", methods=["POST"])
    @super_admin_required
    def hub1z_addon_purchase(module_id):
        module = PlatformModule.query.get_or_404(module_id)
        try:
            quantity = request.form.get("quantity", type=int)
            if quantity is None:
                raise ValueError("Enter a valid quantity.")
            invoice = operator_billing.request_addon(g.operator, module, quantity, actor_id=current_user.id)
            db.session.commit()
            flash(f"Invoice {invoice.number} created. The add-on activates after payment confirmation.", "success")
        except ValueError as error:
            db.session.rollback()
            flash(str(error), "warning")
        return redirect(url_for("admin.hub1z_billing"))

    @bp.route("/hub1z-billing/addons/<int:addon_id>/renewal", methods=["POST"])
    @super_admin_required
    def hub1z_addon_renewal(addon_id):
        addon = OperatorAddon.query.filter_by(id=addon_id, operator_id=g.operator_id).first_or_404()
        change = request.form.get("change")
        try:
            if change == "cancel":
                units = 0
            elif change == "keep":
                units = None
            else:
                units = request.form.get("quantity", type=int)
                if units is None:
                    raise ValueError("Enter how many units should renew.")
            operator_billing.schedule_addon_renewal(g.operator, addon, units, actor_id=current_user.id)
            db.session.commit()
            name = addon.module.name
            flash(f"{name} ends when your paid period ends." if units == 0
                  else f"{name} will renew as before." if addon.renewal_quantity is None
                  else f"{name} renews with {addon.renewal_quantity} unit(s).", "success")
        except ValueError as error:
            db.session.rollback()
            flash(str(error), "warning")
        return redirect(url_for("admin.hub1z_plans"))

    @bp.route("/hub1z-billing/invoices/<int:invoice_id>/cancel", methods=["POST"])
    @super_admin_required
    def hub1z_invoice_cancel(invoice_id):
        invoice = _invoice(invoice_id)
        if invoice.status not in UNPAID or invoice.kind not in ("plan", "upgrade", "addon") or invoice.payments:
            abort(403)
        invoice.status = PlatformInvoiceStatus.VOID
        operator_billing.audit("operator_invoice.cancelled", invoice.id, current_user.id)
        db.session.commit()
        flash("Unpaid invoice cancelled. Your current access is unchanged.", "info")
        return redirect(url_for("admin.hub1z_billing"))

    @bp.route("/hub1z-billing")
    @super_admin_required
    def hub1z_billing():
        from ..company.forms import PaymentSubmissionForm

        oid = g.operator_id
        invoices = PlatformInvoice.query.filter_by(operator_id=oid).order_by(PlatformInvoice.created_at.desc()).all()
        notes = PlatformCreditNote.query.filter_by(operator_id=oid).order_by(PlatformCreditNote.created_at.desc()).all()
        refunds = PlatformRefund.query.filter_by(operator_id=oid).order_by(PlatformRefund.created_at.desc()).all()
        reports = (PlatformPaymentReport.query.filter_by(operator_id=oid)
                   .order_by(PlatformPaymentReport.created_at.desc()).all())
        pay = upi.platform_details(PlatformProfile.get())
        db.session.commit()
        form = PaymentSubmissionForm()
        form.paid_on.data = date.today()
        unpaid = [i for i in invoices if i.status in UNPAID]
        return render_template("admin/hub1z_billing.html", invoices=invoices, credit_notes=notes, refunds=refunds,
                               reports=reports, pay=pay, payment_form=form, today=date.today(),
                               balances={invoice.id: operator_billing.balance(invoice) for invoice in invoices},
                               to_pay=sum((operator_billing.balance(invoice) for invoice in unpaid), 0),
                               pending_for=[r.invoice_id for r in reports if r.status == "pending"],
                               upi_links={i.id: upi.upi_uri(pay["vpa"], pay["payee"], operator_billing.balance(i), f"Hub1z {i.number}")
                                          for i in unpaid})

    @bp.route("/hub1z-billing/invoices/<int:invoice_id>/upi.png")
    @super_admin_required
    def hub1z_invoice_upi_png(invoice_id: int):
        inv = _invoice(invoice_id)
        pay = upi.platform_details(PlatformProfile.get())
        link = upi.upi_uri(pay["vpa"], pay["payee"], operator_billing.balance(inv), f"Hub1z {inv.number}")
        if link is None or inv.status not in UNPAID:
            abort(404)
        resp = Response(upi.qr_png(link), mimetype="image/png")
        resp.headers["Cache-Control"] = "no-store"
        return resp

    @bp.route("/hub1z-billing/invoices/<int:invoice_id>/report", methods=["POST"])
    @super_admin_required
    def hub1z_payment_report(invoice_id: int):
        from ..company.forms import PaymentSubmissionForm

        inv = _invoice(invoice_id)
        form = PaymentSubmissionForm()
        if inv.status not in UNPAID:
            flash("This invoice is not open for payment.", "warning")
        elif PlatformPaymentReport.query.filter_by(invoice_id=inv.id, operator_id=g.operator_id,
                                                    status="pending").first():
            flash("You have already reported a payment for this invoice. Hub1z will confirm it shortly.", "info")
        elif not form.validate_on_submit():
            flash("Enter a valid payment amount and date.", "warning")
        else:
            report = PlatformPaymentReport(
                operator_id=g.operator_id, invoice_id=inv.id, amount=form.amount.data, paid_on=form.paid_on.data,
                reference=(form.reference.data or "").strip() or None, notes=(form.notes.data or "").strip() or None,
                reported_by_id=current_user.id)
            db.session.add(report)
            db.session.commit()
            _notify_support(report, inv)
            flash("Thanks. Hub1z will confirm your payment shortly.", "success")
        return redirect(url_for("admin.hub1z_billing"))

    @bp.route("/hub1z-billing/invoices/<int:invoice_id>.pdf")
    @super_admin_required
    def hub1z_invoice_pdf(invoice_id: int):
        inv = _invoice(invoice_id)
        return pdf_response("pdf/document.html", f"hub1z-invoice-{inv.number}.pdf", **platform_invoice_context(inv))

    @bp.route("/hub1z-billing/credit-notes/<int:note_id>.pdf")
    @super_admin_required
    def hub1z_credit_note_pdf(note_id: int):
        note = PlatformCreditNote.query.filter_by(id=note_id, operator_id=g.operator_id).first_or_404()
        return pdf_response("pdf/document.html", f"hub1z-credit-note-{note.number}.pdf", **platform_credit_note_context(note))

    @bp.route("/hub1z-billing/refunds/<int:refund_id>.pdf")
    @super_admin_required
    def hub1z_refund_pdf(refund_id: int):
        refund = PlatformRefund.query.filter_by(id=refund_id, operator_id=g.operator_id).first_or_404()
        return pdf_response("pdf/document.html", f"hub1z-refund-{refund.number}.pdf", **platform_refund_context(refund))
