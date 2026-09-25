"""Admin routes for expense categories and expenses."""
from __future__ import annotations

from datetime import datetime

from flask import render_template, redirect, url_for, flash, g
from flask_login import current_user

from ...extensions import db
from ...models import (
    Expense, ExpenseCategory, ExpenseStatus,
    Location, StaffMember, Document, DocumentKind,
)
from ...services.storage import storage_service
from ...utils.decorators import admin_required, manager_or_super_required
from .forms import ExpenseCategoryForm, ExpenseForm, ExpenseDecisionForm


def register_expense_routes(bp):

    # -------------------------------------------------------- categories --
    @bp.route("/expense-categories")
    @admin_required
    def expense_categories():
        cats = ExpenseCategory.query.order_by(ExpenseCategory.name).all()
        return render_template("admin/expenses/categories.html", categories=cats)

    @bp.route("/expense-categories/new", methods=["GET", "POST"])
    @admin_required
    def expense_category_new():
        form = ExpenseCategoryForm()
        if form.validate_on_submit():
            c = ExpenseCategory()
            form.populate_obj(c)
            db.session.add(c)
            db.session.commit()
            flash("Category created.", "success")
            return redirect(url_for("admin.expense_categories"))
        return render_template("admin/expenses/category_form.html", form=form, title="New category")

    @bp.route("/expense-categories/<int:cat_id>/edit", methods=["GET", "POST"])
    @admin_required
    def expense_category_edit(cat_id: int):
        c = ExpenseCategory.query.get_or_404(cat_id)
        form = ExpenseCategoryForm(obj=c)
        if form.validate_on_submit():
            form.populate_obj(c)
            db.session.commit()
            flash("Category updated.", "success")
            return redirect(url_for("admin.expense_categories"))
        return render_template("admin/expenses/category_form.html", form=form, title="Edit category")

    # ----------------------------------------------------------- expenses --
    @bp.route("/expenses")
    @admin_required
    def expenses_list():
        expenses = Expense.query.order_by(Expense.expense_date.desc()).limit(200).all()
        return render_template("admin/expenses/list.html", expenses=expenses)

    def _fill_expense_choices(form):
        form.category_id.choices = [
            (c.id, c.name) for c in
            ExpenseCategory.query.filter_by(is_active=True).order_by(ExpenseCategory.name).all()
        ]
        form.location_id.choices = [(0, "— none —")] + [
            (l.id, l.name) for l in Location.query.order_by(Location.name).all()
        ]
        form.staff_id.choices = [(0, "— none —")] + [
            (s.id, f"{s.employee_code} — {s.full_name}")
            for s in StaffMember.query.order_by(StaffMember.full_name).all()
        ]

    @bp.route("/expenses/new", methods=["GET", "POST"])
    @admin_required
    def expense_new():
        form = ExpenseForm()
        _fill_expense_choices(form)
        if form.validate_on_submit():
            exp = Expense(
                category_id=form.category_id.data,
                location_id=form.location_id.data or None,
                staff_id=form.staff_id.data or None,
                amount=form.amount.data,
                currency=form.currency.data,
                expense_date=form.expense_date.data,
                vendor=form.vendor.data,
                payment_method=form.payment_method.data,
                description=form.description.data,
                status=ExpenseStatus.SUBMITTED,
                submitted_by_id=current_user.id,
            )
            if form.receipt.data:
                f = form.receipt.data
                stored = storage_service.upload(
                    namespace=f"operators/{getattr(g, 'tenant_id', 'unscoped')}/expenses",
                    filename=f.filename, stream=f.stream, content_type=f.mimetype,
                    scope="operator",
                )
                doc = Document(
                    tenant_id=getattr(g, "tenant_id", None),
                    kind=DocumentKind.OTHER,
                    owner_type="expense",
                    filename=f.filename, content_type=f.mimetype,
                    size_bytes=stored.size_bytes,
                    storage_backend=stored.backend, storage_bucket=stored.bucket,
                    storage_key=stored.key,
                    uploaded_by_id=current_user.id,
                )
                db.session.add(doc)
                db.session.flush()
                exp.receipt_document_id = doc.id
            db.session.add(exp)
            db.session.commit()
            flash("Expense submitted.", "success")
            return redirect(url_for("admin.expenses_list"))
        return render_template("admin/expenses/form.html", form=form)

    @bp.route("/expenses/<int:exp_id>", methods=["GET", "POST"])
    @admin_required
    def expense_detail(exp_id: int):
        exp = Expense.query.get_or_404(exp_id)
        form = ExpenseDecisionForm()
        return render_template("admin/expenses/detail.html", expense=exp, form=form)

    @bp.route("/expenses/<int:exp_id>/approve", methods=["POST"])
    @manager_or_super_required
    def expense_approve(exp_id: int):
        exp = Expense.query.get_or_404(exp_id)
        exp.status = ExpenseStatus.APPROVED
        exp.approved_by_id = current_user.id
        exp.approved_at = datetime.utcnow()
        db.session.commit()
        flash("Expense approved.", "success")
        return redirect(url_for("admin.expense_detail", exp_id=exp.id))

    @bp.route("/expenses/<int:exp_id>/reject", methods=["POST"])
    @manager_or_super_required
    def expense_reject(exp_id: int):
        from flask import request
        exp = Expense.query.get_or_404(exp_id)
        exp.status = ExpenseStatus.REJECTED
        exp.rejection_reason = request.form.get("rejection_reason")
        exp.approved_by_id = current_user.id
        exp.approved_at = datetime.utcnow()
        db.session.commit()
        flash("Expense rejected.", "info")
        return redirect(url_for("admin.expense_detail", exp_id=exp.id))

    @bp.route("/expenses/<int:exp_id>/mark-paid", methods=["POST"])
    @manager_or_super_required
    def expense_mark_paid(exp_id: int):
        exp = Expense.query.get_or_404(exp_id)
        exp.status = ExpenseStatus.PAID
        exp.paid_at = datetime.utcnow()
        db.session.commit()
        flash("Expense marked as paid.", "success")
        return redirect(url_for("admin.expense_detail", exp_id=exp.id))
