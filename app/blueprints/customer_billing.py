"""'Invoices & payments' routes for whoever pays the operator: a company (company admin) or an individual member.

The same routes are added to the company and member blueprints; ``owner()`` says whose documents they may see.
"""
from __future__ import annotations

from flask import flash, g, redirect, render_template, url_for

from ..extensions import db
from ..models import CreditNote, CreditNoteStatus, Invoice, InvoiceStatus, Payment, PaymentSubmission
from ..services import customer_billing
from ..services.pdf_docs import credit_note_context, pdf_response, receipt_context


def register_customer_billing_routes(bp, guard, owner):
    """``owner()`` returns ("company_id", id) or ("user_id", id) for the signed-in payer."""
    name = bp.name

    def _invoices():
        col, oid = owner()
        return Invoice.query.filter(getattr(Invoice, col) == oid, Invoice.status != InvoiceStatus.DRAFT)

    def _invoice(invoice_id: int) -> Invoice:
        return _invoices().filter(Invoice.id == invoice_id).first_or_404()

    @bp.route("/invoices")
    @guard
    def invoices():
        col, oid = owner()
        invs = _invoices().order_by(Invoice.issued_at.desc().nullslast(), Invoice.id.desc()).all()
        payments = (Payment.query.join(Invoice, Payment.invoice_id == Invoice.id)
                    .filter(getattr(Invoice, col) == oid).order_by(Payment.paid_at.desc()).all())
        notes = (CreditNote.query.filter(getattr(CreditNote, col) == oid, CreditNote.status != CreditNoteStatus.CANCELLED)
                 .order_by(CreditNote.created_at.desc()).all())
        submissions = (PaymentSubmission.query.filter(getattr(PaymentSubmission, col) == oid)
                       .order_by(PaymentSubmission.created_at.desc()).all())
        return render_template("billing/customer_invoices.html", bp=name,
                               **customer_billing.page_context(g.operator, invs, payments, notes, submissions))

    @bp.route("/invoices/<int:invoice_id>/pdf")
    @guard
    def invoice_pdf(invoice_id: int):
        inv = _invoice(invoice_id)
        return pdf_response("admin/invoices/pdf.html", f"invoice-{inv.number}.pdf", invoice=inv,
                            issuer_name=(g.operator.company_legal_name or g.operator.name) if g.operator else None)

    @bp.route("/invoices/<int:invoice_id>/upi.png")
    @guard
    def invoice_upi_png(invoice_id: int):
        return customer_billing.invoice_qr(g.operator, _invoice(invoice_id))

    @bp.route("/payments/<int:payment_id>/receipt.pdf")
    @guard
    def payment_receipt(payment_id: int):
        col, oid = owner()
        payment = (Payment.query.join(Invoice, Payment.invoice_id == Invoice.id)
                   .filter(Payment.id == payment_id, getattr(Invoice, col) == oid).first_or_404())
        return pdf_response("pdf/document.html", f"receipt-{payment.invoice.number}-{payment.id}.pdf",
                            **receipt_context(payment, g.operator))

    @bp.route("/credit-notes/<int:note_id>/pdf")
    @guard
    def credit_note_pdf(note_id: int):
        col, oid = owner()
        note = CreditNote.query.filter(CreditNote.id == note_id, getattr(CreditNote, col) == oid,
                                       CreditNote.status != CreditNoteStatus.CANCELLED).first_or_404()
        return pdf_response("pdf/document.html", f"credit-note-{note.number}.pdf", **credit_note_context(note, g.operator))

    @bp.route("/invoices/<int:invoice_id>/payments", methods=["POST"])
    @guard
    def payment_submission_new(invoice_id: int):
        from .company.forms import PaymentSubmissionForm

        col, oid = owner()
        invoice = _invoice(invoice_id)
        form = PaymentSubmissionForm()
        if not form.validate_on_submit():
            flash("Enter a valid payment amount and date.", "warning")
        elif form.amount.data > invoice.balance_due:
            flash("The amount is more than this invoice's balance.", "warning")
        else:
            db.session.add(PaymentSubmission(
                operator_id=g.operator_id, invoice_id=invoice.id, **{col: oid},
                amount=form.amount.data, paid_on=form.paid_on.data,
                reference=(form.reference.data or "").strip() or None,
                notes=(form.notes.data or "").strip() or None,
            ))
            db.session.commit()
            flash("Thanks. Your payment is reported and will show as paid once it is confirmed.", "success")
        return redirect(url_for(f"{name}.invoices"))
