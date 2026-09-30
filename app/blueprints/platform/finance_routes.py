"""Platform's own invoices/credit notes/refunds/expenses for its
commercial relationship with operators — separate from an operator's own
/admin billing of its member companies."""
from __future__ import annotations

from datetime import datetime

from flask import render_template, redirect, url_for, flash

from ...extensions import db
from ...models import (
    Operator, PlatformInvoice, PlatformCreditNote, PlatformRefund, PlatformExpense,
)
from ...utils.decorators import platform_permission_required
from .forms import (
    PlatformInvoiceForm, PlatformCreditNoteForm, PlatformRefundForm, PlatformExpenseForm,
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
        return render_template("platform/finance/dashboard.html", invoices=invoices,
                               credit_notes=credit_notes, refunds=refunds, expenses=expenses)

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
