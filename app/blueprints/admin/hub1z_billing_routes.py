"""What the operator owes Hub1z: the Platform's invoices, credit notes and refunds to this operator, with PDFs,
UPI payment and a way to report a payment for Hub1z to confirm."""
from __future__ import annotations

from datetime import date

from flask import Response, abort, flash, g, redirect, render_template, url_for
from flask_login import current_user

from ...extensions import db
from ...models import (PlatformCreditNote, PlatformInvoice, PlatformInvoiceStatus, PlatformPaymentReport,
                       PlatformProfile, PlatformRefund)
from ...services import upi
from ...services.pdf_docs import (pdf_response, platform_credit_note_context, platform_invoice_context,
                                  platform_refund_context)
from ...utils.decorators import super_admin_required

UNPAID = (PlatformInvoiceStatus.ISSUED, PlatformInvoiceStatus.OVERDUE)


def register_hub1z_billing_routes(bp):
    # Platform billing tables are not auto-scoped, so every query names the operator.

    def _invoice(invoice_id: int) -> PlatformInvoice:
        return PlatformInvoice.query.filter_by(id=invoice_id, operator_id=g.operator_id).first_or_404()

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
                               pending_for=[r.invoice_id for r in reports if r.status == "pending"],
                               upi_links={i.id: upi.upi_uri(pay["vpa"], pay["payee"], i.amount, f"Hub1z {i.number}")
                                          for i in unpaid})

    @bp.route("/hub1z-billing/invoices/<int:invoice_id>/upi.png")
    @super_admin_required
    def hub1z_invoice_upi_png(invoice_id: int):
        inv = _invoice(invoice_id)
        pay = upi.platform_details(PlatformProfile.get())
        link = upi.upi_uri(pay["vpa"], pay["payee"], inv.amount, f"Hub1z {inv.number}")
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
        elif not form.validate_on_submit():
            flash("Enter a valid payment amount and date.", "warning")
        else:
            db.session.add(PlatformPaymentReport(
                operator_id=g.operator_id, invoice_id=inv.id, amount=form.amount.data, paid_on=form.paid_on.data,
                reference=(form.reference.data or "").strip() or None, notes=(form.notes.data or "").strip() or None,
                reported_by_id=current_user.id))
            db.session.commit()
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
