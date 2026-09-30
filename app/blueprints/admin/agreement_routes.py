"""Operator billing settings (invoice timing, default terms, GST) and the agreement page of a subscription."""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from flask import render_template, redirect, url_for, flash, g
from flask_login import current_user

from ...extensions import db
from ...models import (
    BillingSettings, DepositEntry, Invoice, RateRevision, Subscription, SubscriptionStatus, TaxRate,
)
from ...services import audit_service, billing_service
from ...services.billing_service import BillingError
from ...services.gst import CHARGE_TYPES, STATE_NAMES
from ...utils.decorators import admin_required, manager_or_super_required, super_admin_required
from .forms import (
    BillingSettingsForm, DepositEntryForm, NoticeForm, OperatorTaxForm, RevisionDecisionForm, TaxRateForm,
)

_SETTINGS_FIELDS = (
    "invoice_issue_day", "due_day", "term_months", "lock_in_months", "notice_months", "deposit_months",
    "deposit_refund_days", "escalation_percent", "escalation_after_months", "late_fee_mode", "late_fee_value",
    "late_fee_grace_days", "early_exit_rule",
)


def register_agreement_routes(bp):

    # ------------------------------------------------- billing settings --
    def _settings_page(settings_form=None, tax_form=None, rate_form=None):
        settings = BillingSettings.for_operator(g.operator_id)
        operator = g.operator
        if settings_form is None:
            settings_form = BillingSettingsForm(obj=settings)
        if tax_form is None:
            tax_form = OperatorTaxForm(obj=operator)
        if rate_form is None:
            rate_form = TaxRateForm()
            rate_form.effective_from.data = date.today()
        rates = TaxRate.query.order_by(TaxRate.charge_type, TaxRate.effective_from.desc()).all()
        db.session.commit()
        return render_template("admin/billing_settings.html", settings_form=settings_form, tax_form=tax_form,
                               rate_form=rate_form, rates=rates, charge_names=dict(CHARGE_TYPES),
                               state_names=STATE_NAMES, default_rate=operator.default_tax_rate)

    @bp.route("/billing/settings")
    @super_admin_required
    def billing_settings():
        return _settings_page()

    @bp.route("/billing/settings/terms", methods=["POST"])
    @super_admin_required
    def billing_settings_save():
        form = BillingSettingsForm()
        if not form.validate_on_submit():
            flash("Some billing settings are not valid.", "danger")
            return _settings_page(settings_form=form)
        settings = BillingSettings.for_operator(g.operator_id)
        for name in _SETTINGS_FIELDS:
            value = getattr(form, name).data
            if value is not None:
                setattr(settings, name, value)
        db.session.commit()
        audit_service.record("billing_settings.updated", "billing_settings", settings.id, {})
        flash("Billing settings saved. Existing agreements keep their own terms.", "success")
        return redirect(url_for("admin.billing_settings"))

    @bp.route("/billing/settings/tax-details", methods=["POST"])
    @super_admin_required
    def billing_tax_details_save():
        form = OperatorTaxForm()
        if not form.validate_on_submit():
            flash("Some tax details are not valid.", "danger")
            return _settings_page(tax_form=form)
        operator = g.operator
        operator.company_legal_name = form.company_legal_name.data or None
        operator.gstin = (form.gstin.data or "").strip().upper() or None
        operator.pan = (form.pan.data or "").strip().upper() or None
        operator.gst_state = form.gst_state.data or None
        db.session.commit()
        flash("Tax details saved. They appear on invoices raised from now on.", "success")
        return redirect(url_for("admin.billing_settings"))

    @bp.route("/billing/settings/tax-rates", methods=["POST"])
    @super_admin_required
    def billing_tax_rate_add():
        form = TaxRateForm()
        if not form.validate_on_submit():
            flash("Some tax rate fields are not valid.", "danger")
            return _settings_page(rate_form=form)
        exists = TaxRate.query.filter_by(charge_type=form.charge_type.data,
                                         effective_from=form.effective_from.data).first()
        if exists:
            flash("That charge already has a rate from that date. Delete it first to replace it.", "warning")
            return redirect(url_for("admin.billing_settings"))
        db.session.add(TaxRate(operator_id=g.operator_id, charge_type=form.charge_type.data,
                               rate=form.rate.data, sac_code=(form.sac_code.data or None),
                               effective_from=form.effective_from.data))
        db.session.commit()
        flash("GST rate added.", "success")
        return redirect(url_for("admin.billing_settings"))

    @bp.route("/billing/settings/tax-rates/<int:rate_id>/delete", methods=["POST"])
    @super_admin_required
    def billing_tax_rate_delete(rate_id: int):
        row = TaxRate.query.get_or_404(rate_id)
        db.session.delete(row)
        db.session.commit()
        flash("GST rate removed.", "info")
        return redirect(url_for("admin.billing_settings"))

    # -------------------------------------------------------- agreement --
    def _sub_or_404(company_id: int, sub_id: int) -> Subscription:
        return Subscription.query.filter_by(id=sub_id, company_id=company_id).first_or_404()

    @bp.route("/companies/<int:company_id>/subscriptions/<int:sub_id>/agreement")
    @admin_required
    def subscription_agreement(company_id: int, sub_id: int):
        sub = _sub_or_404(company_id, sub_id)
        entries = (DepositEntry.query.filter_by(subscription_id=sub.id)
                   .order_by(DepositEntry.entry_date, DepositEntry.id).all())
        revisions = (RateRevision.query.filter_by(subscription_id=sub.id)
                     .order_by(RateRevision.effective_from.desc()).all())
        invoices = (Invoice.query.filter_by(subscription_id=sub.id)
                    .order_by(Invoice.period_start.desc(), Invoice.id.desc()).limit(24).all())
        notice_form = NoticeForm()
        notice_form.notice_date.data = date.today()
        deposit_form = DepositEntryForm()
        deposit_form.entry_date.data = date.today()
        return render_template(
            "admin/companies/agreement.html", sub=sub, company=sub.company, entries=entries,
            revisions=revisions, invoices=invoices, held=billing_service.deposit_balance(sub),
            notice_form=notice_form, deposit_form=deposit_form, decision_form=RevisionDecisionForm(),
            current_price=billing_service.effective_unit_price(sub, date.today()),
            refund_by=(sub.terminate_on + timedelta(days=sub.deposit_refund_days)) if sub.terminate_on else None,
        )

    @bp.route("/companies/<int:company_id>/subscriptions/<int:sub_id>/notice", methods=["POST"])
    @manager_or_super_required
    def subscription_notice(company_id: int, sub_id: int):
        sub = _sub_or_404(company_id, sub_id)
        form = NoticeForm()
        if not form.validate_on_submit():
            flash("Enter the date notice was given.", "warning")
            return redirect(url_for("admin.subscription_agreement", company_id=company_id, sub_id=sub.id))
        try:
            result = billing_service.give_notice(sub, form.notice_date.data, current_user)
        except BillingError as e:
            flash(str(e), "warning")
            return redirect(url_for("admin.subscription_agreement", company_id=company_id, sub_id=sub.id))
        db.session.commit()
        audit_service.record("subscription.notice", "subscription", sub.id,
                             {"terminate_on": result["terminate_on"].isoformat(), "months": result["months"]})
        flash(f"Notice recorded. The agreement ends on {result['terminate_on']}.", "success")
        if result["early_exit_invoice"] is not None:
            flash(f"Early exit inside the lock-in: invoice {result['early_exit_invoice'].number} raised for "
                  f"the remaining {result['months']} month(s).", "info")
        if result["forfeited"]:
            flash(f"Early exit inside the lock-in: the deposit of {result['forfeited']} is forfeited.", "info")
        return redirect(url_for("admin.subscription_agreement", company_id=company_id, sub_id=sub.id))

    @bp.route("/companies/<int:company_id>/subscriptions/<int:sub_id>/deposit", methods=["POST"])
    @manager_or_super_required
    def subscription_deposit(company_id: int, sub_id: int):
        sub = _sub_or_404(company_id, sub_id)
        form = DepositEntryForm()
        if not form.validate_on_submit():
            flash("Enter a valid amount and date.", "warning")
            return redirect(url_for("admin.subscription_agreement", company_id=company_id, sub_id=sub.id))
        try:
            billing_service.record_deposit(sub, form.entry_type.data, form.amount.data, form.entry_date.data,
                                           form.note.data, current_user)
        except BillingError as e:
            flash(str(e), "warning")
            return redirect(url_for("admin.subscription_agreement", company_id=company_id, sub_id=sub.id))
        db.session.commit()
        audit_service.record(f"deposit.{form.entry_type.data}", "subscription", sub.id,
                             {"amount": str(form.amount.data)})
        flash("Deposit entry recorded.", "success")
        return redirect(url_for("admin.subscription_agreement", company_id=company_id, sub_id=sub.id))

    @bp.route("/companies/<int:company_id>/subscriptions/<int:sub_id>/revisions/<int:rev_id>/<decision>",
              methods=["POST"])
    @manager_or_super_required
    def subscription_revision(company_id: int, sub_id: int, rev_id: int, decision: str):
        sub = _sub_or_404(company_id, sub_id)
        rev = RateRevision.query.filter_by(id=rev_id, subscription_id=sub.id).first_or_404()
        if decision not in ("confirm", "dismiss"):
            flash("Invalid decision.", "warning")
            return redirect(url_for("admin.subscription_agreement", company_id=company_id, sub_id=sub.id))
        form = RevisionDecisionForm()
        percent = form.percent.data if form.validate_on_submit() and form.percent.data is not None else None
        try:
            billing_service.decide_revision(rev, decision == "confirm", current_user, percent)
        except BillingError as e:
            flash(str(e), "warning")
            return redirect(url_for("admin.subscription_agreement", company_id=company_id, sub_id=sub.id))
        db.session.commit()
        audit_service.record(f"rate_revision.{decision}", "subscription", sub.id,
                             {"effective_from": rev.effective_from.isoformat(), "new_price": str(rev.new_unit_price)})
        flash("Increase confirmed." if decision == "confirm" else "Increase dismissed.", "success")
        return redirect(url_for("admin.subscription_agreement", company_id=company_id, sub_id=sub.id))
