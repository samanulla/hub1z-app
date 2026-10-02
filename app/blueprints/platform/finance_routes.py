"""Platform's own invoices/credit notes/refunds/expenses for its
commercial relationship with operators — separate from an operator's own
/admin billing of its member companies."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from uuid import uuid4

from flask import render_template, redirect, url_for, flash, request, Response, abort
from flask_login import current_user

from ...extensions import db
from ...models import (
    Operator, PlatformInvoice, PlatformCreditNote, PlatformRefund, PlatformExpense, PlatformInvoiceStatus,
    PlatformPaymentReport, PlatformProfile,
)
from ...utils.decorators import platform_permission_required
from ...services import upi, operator_billing
from ...services.pdf_docs import (pdf_response, platform_credit_note_context, platform_invoice_context,
                                  platform_refund_context)
from .forms import (
    PlatformInvoiceForm, PlatformCreditNoteForm, PlatformRefundForm, PlatformExpenseForm, PlatformProfileForm,
)


def _operator_choices():
    return [(t.id, t.name) for t in
            Operator.query.execution_options(skip_operator_filter=True).order_by(Operator.name).all()]


def _invoice_choices(operator_id: int | None = None):
    q = PlatformInvoice.query
    if operator_id:
        q = q.filter_by(operator_id=operator_id)
    return [(0, "\u2014 none \u2014")] + [(i.id, i.number) for i in q.order_by(PlatformInvoice.number).all()]


def register_finance_routes(bp):

    @bp.route("/finance")
    @platform_permission_required("billing")
    def finance_dashboard():
        invoices = PlatformInvoice.query.order_by(PlatformInvoice.created_at.desc()).limit(50).all()
        credit_notes = PlatformCreditNote.query.order_by(PlatformCreditNote.created_at.desc()).limit(50).all()
        refunds = PlatformRefund.query.order_by(PlatformRefund.created_at.desc()).limit(50).all()
        expenses = PlatformExpense.query.order_by(PlatformExpense.incurred_on.desc()).limit(50).all()
        reports = (PlatformPaymentReport.query.order_by((PlatformPaymentReport.status == "pending").desc(),
                                                        PlatformPaymentReport.created_at.desc()).limit(50).all())
        profile = PlatformProfile.get()
        db.session.commit()
        return render_template("platform/finance/dashboard.html", invoices=invoices, reports=reports,
                               credit_notes=credit_notes, refunds=refunds, expenses=expenses, profile=profile,
                               payment_total=operator_billing.payment_total,
                               payment_keys={invoice.id: uuid4().hex for invoice in invoices})

    @bp.route("/finance/invoices/<int:invoice_id>/payment", methods=["POST"])
    @platform_permission_required("billing")
    def finance_confirm_payment(invoice_id):
        invoice = PlatformInvoice.query.get_or_404(invoice_id)
        try:
            amount = Decimal(request.form.get("amount", ""))
            if not amount.is_finite():
                raise ValueError("Enter a valid payment amount.")
            key = request.form.get("request_key", "")
            if len(key) != 32 or any(character not in "0123456789abcdef" for character in key):
                raise ValueError("Reload the invoice page before recording payment.")
            operator_billing.confirm_payment(invoice, amount, request.form.get("method"),
                                             request.form.get("reference"), current_user.id, request_key=key)
            db.session.commit()
            flash("Payment recorded. Fully paid plans and add-ons are activated.", "success")
        except (ValueError, InvalidOperation) as error:
            db.session.rollback()
            flash(str(error) if isinstance(error, ValueError) else "Enter a valid payment amount.", "warning")
        return redirect(url_for("platform.finance_dashboard"))

    @bp.route("/finance/payment-reports/<int:report_id>/<decision>", methods=["POST"])
    @platform_permission_required("billing")
    def finance_payment_report_review(report_id: int, decision: str):
        report = PlatformPaymentReport.query.filter_by(id=report_id).with_for_update().first_or_404()
        if report.status != "pending":
            return redirect(url_for("platform.finance_dashboard"))
        message = (request.form.get("message") or "").strip()[:500] or None
        if decision == "accept" and report.invoice.status == PlatformInvoiceStatus.PAID:
            report.status = "rejected"
            message = message or "This invoice was already paid."
            flash("That invoice is already paid, so this duplicate report was closed.", "info")
        elif decision == "accept":
            try:
                operator_billing.confirm_payment(report.invoice, report.amount, request.form.get("method", "upi"),
                                                 report.reference, current_user.id, report.id, report.paid_on)
            except ValueError as error:
                db.session.rollback()
                flash(str(error), "warning")
                return redirect(url_for("platform.finance_dashboard"))
            report.status = "accepted"
            flash(f"Payment from {report.operator.name} confirmed.", "success")
        elif decision == "reject" and message:
            report.status = "rejected"
            flash("Payment report rejected.", "info")
        else:
            flash("Add a message explaining why the payment was not accepted.", "warning")
            return redirect(url_for("platform.finance_dashboard"))
        report.platform_message = message
        report.reviewed_by_id = current_user.id
        report.reviewed_at = datetime.utcnow()
        db.session.commit()
        return redirect(url_for("platform.finance_dashboard"))

    @bp.route("/payment-details", methods=["GET", "POST"])
    @platform_permission_required("payment_setup")
    def payment_details():
        profile = PlatformProfile.get()
        form = PlatformProfileForm(obj=profile)
        if form.validate_on_submit():
            form.populate_obj(profile)
            profile.gst_state = profile.gst_state or None
            profile.sac_code = profile.sac_code or None
            profile.default_gst_rate = Decimal("18") if profile.default_gst_rate is None else profile.default_gst_rate
            profile.invoice_prefix = (profile.invoice_prefix or "H1Z").upper()
            profile.payment_terms_days = 7 if profile.payment_terms_days is None else profile.payment_terms_days
            db.session.commit()
            flash("Hub1z payment details saved. Operators see them on their Hub1z invoices.", "success")
            return redirect(url_for("platform.payment_details"))
        db.session.commit()
        return render_template("platform/payment_details.html", form=form,
                               qr_available=bool(upi.platform_details(profile)["vpa"]))

    @bp.route("/payment-details/qr.png")
    @platform_permission_required("payment_setup")
    def payment_details_qr():
        profile = PlatformProfile.peek()
        details = upi.platform_details(profile) if profile else None
        if not details or not details["vpa"]:
            abort(404)
        uri = upi.upi_uri(details["vpa"], details["payee"], None, "Hub1z payments")
        return Response(upi.qr_png(uri), mimetype="image/png", headers={"Cache-Control": "no-store"})

    @bp.route("/finance/invoices/<int:invoice_id>/pdf")
    @platform_permission_required("billing")
    def finance_invoice_pdf(invoice_id: int):
        inv = PlatformInvoice.query.get_or_404(invoice_id)
        return pdf_response("pdf/document.html", f"hub1z-invoice-{inv.number}.pdf", **platform_invoice_context(inv))

    @bp.route("/finance/credit-notes/<int:note_id>/pdf")
    @platform_permission_required("billing")
    def finance_credit_note_pdf(note_id: int):
        note = PlatformCreditNote.query.get_or_404(note_id)
        return pdf_response("pdf/document.html", f"hub1z-credit-note-{note.number}.pdf", **platform_credit_note_context(note))

    @bp.route("/finance/refunds/<int:refund_id>/pdf")
    @platform_permission_required("billing")
    def finance_refund_pdf(refund_id: int):
        refund = PlatformRefund.query.get_or_404(refund_id)
        return pdf_response("pdf/document.html", f"hub1z-refund-{refund.number}.pdf", **platform_refund_context(refund))

    @bp.route("/finance/invoices/new", methods=["GET", "POST"])
    @platform_permission_required("billing")
    def finance_invoice_new():
        form = PlatformInvoiceForm()
        form.operator_id.choices = _operator_choices()
        if form.validate_on_submit():
            if PlatformInvoice.query.filter_by(number=form.number.data.strip()).first():
                flash("An invoice with that number already exists.", "warning")
            else:
                inv = PlatformInvoice(number=form.number.data.strip())
                form.populate_obj(inv)
                inv.number = form.number.data.strip()
                db.session.add(inv)
                db.session.commit()
                flash("Invoice recorded.", "success")
                return redirect(url_for("platform.finance_dashboard"))
        return render_template("platform/finance/form.html", form=form, title="New platform invoice")

    @bp.route("/finance/credit-notes/new", methods=["GET", "POST"])
    @platform_permission_required("billing")
    def finance_credit_note_new():
        form = PlatformCreditNoteForm()
        form.operator_id.choices = _operator_choices()
        form.invoice_id.choices = _invoice_choices()
        if form.validate_on_submit():
            if PlatformCreditNote.query.filter_by(number=form.number.data.strip()).first():
                flash("A credit note with that number already exists.", "warning")
            else:
                cn = PlatformCreditNote(issued_at=datetime.utcnow())
                form.populate_obj(cn)
                cn.number = form.number.data.strip()
                cn.invoice_id = form.invoice_id.data or None
                db.session.add(cn)
                db.session.commit()
                flash("Credit note recorded.", "success")
                return redirect(url_for("platform.finance_dashboard"))
        return render_template("platform/finance/form.html", form=form, title="New credit note")

    @bp.route("/finance/refunds/new", methods=["GET", "POST"])
    @platform_permission_required("billing")
    def finance_refund_new():
        form = PlatformRefundForm()
        form.operator_id.choices = _operator_choices()
        form.invoice_id.choices = _invoice_choices()
        if form.validate_on_submit():
            if PlatformRefund.query.filter_by(number=form.number.data.strip()).first():
                flash("A refund with that reference already exists.", "warning")
            else:
                r = PlatformRefund(processed_at=datetime.utcnow())
                form.populate_obj(r)
                r.number = form.number.data.strip()
                r.invoice_id = form.invoice_id.data or None
                db.session.add(r)
                db.session.commit()
                flash("Refund recorded.", "success")
                return redirect(url_for("platform.finance_dashboard"))
        return render_template("platform/finance/form.html", form=form, title="New refund")

    @bp.route("/finance/expenses/new", methods=["GET", "POST"])
    @platform_permission_required("billing")
    def finance_expense_new():
        form = PlatformExpenseForm()
        if form.validate_on_submit():
            e = PlatformExpense()
            form.populate_obj(e)
            db.session.add(e)
            db.session.commit()
            flash("Expense recorded.", "success")
            return redirect(url_for("platform.finance_dashboard"))
        return render_template("platform/finance/form.html", form=form, title="New platform expense")
