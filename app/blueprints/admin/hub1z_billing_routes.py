"""What the operator owes Hub1z: the Platform's invoices, credit notes and refunds to this operator, with PDFs."""
from __future__ import annotations

from flask import g, render_template

from ...models import PlatformCreditNote, PlatformInvoice, PlatformRefund
from ...services.pdf_docs import (pdf_response, platform_credit_note_context, platform_invoice_context,
                                  platform_refund_context)
from ...utils.decorators import super_admin_required


def register_hub1z_billing_routes(bp):
    # Platform billing tables are not auto-scoped, so every query names the operator.

    @bp.route("/hub1z-billing")
    @super_admin_required
    def hub1z_billing():
        oid = g.operator_id
        invoices = PlatformInvoice.query.filter_by(operator_id=oid).order_by(PlatformInvoice.created_at.desc()).all()
        notes = PlatformCreditNote.query.filter_by(operator_id=oid).order_by(PlatformCreditNote.created_at.desc()).all()
        refunds = PlatformRefund.query.filter_by(operator_id=oid).order_by(PlatformRefund.created_at.desc()).all()
        return render_template("admin/hub1z_billing.html", invoices=invoices, credit_notes=notes, refunds=refunds)

    @bp.route("/hub1z-billing/invoices/<int:invoice_id>.pdf")
    @super_admin_required
    def hub1z_invoice_pdf(invoice_id: int):
        inv = PlatformInvoice.query.filter_by(id=invoice_id, operator_id=g.operator_id).first_or_404()
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
