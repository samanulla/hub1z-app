"""Admin routes for system-wide settings (super-admin only)."""
from __future__ import annotations

from flask import render_template, redirect, url_for, flash, g
from flask_login import current_user

from ...extensions import db
from ...models import SystemSettings, Location, UserRole, Seat, User, Document
from ...services import audit_service
from ...utils.decorators import super_admin_required
from .forms import SystemSettingsForm, OperatorSettingsForm
from ..profile_forms import PROFILE_GROUPS, save_details


def register_settings_routes(bp):

    @bp.route("/settings", methods=["GET", "POST"])
    @super_admin_required
    def settings():
        if current_user.role == UserRole.SUPER_ADMIN and getattr(g, "operator", None):
            operator = g.operator
            details = dict(operator.profile_details or {})
            form = OperatorSettingsForm(obj=operator, data=details)
            form.primary_location_id.choices = [(0, "No primary location")] + [
                (loc.id, f"{loc.name} ({loc.code})")
                for loc in Location.query.filter_by(is_active=True).order_by(Location.name).all()
            ]
            if not form.is_submitted():
                form.tagline.data = operator.tagline
                form.logo_url.data = operator.logo_url
                form.brand_color.data = operator.brand_color
                form.support_email.data = operator.support_email
                form.primary_location_id.data = operator.primary_location_id or 0
                form.payment_instructions.data = operator.payment_instructions
                form.payment_upi_id.data = operator.payment_upi_id
                form.payment_gpay.data = operator.payment_gpay
                form.payment_bank_details.data = operator.payment_bank_details
            if form.validate_on_submit():
                operator.name = (form.name.data or operator.name).strip()
                for name in ("company_legal_name", "pan", "gstin", "gst_state", "payment_bank_account_name",
                             "payment_bank_account_number", "payment_bank_ifsc_or_routing"):
                    setattr(operator, name, form[name].data)
                save_details(operator, form)
                operator.profile_details = {**operator.profile_details,
                                            **{name: form[name].data for name in ("industry", "website", "contact_phone", "billing_email")}}
                operator.tagline = form.tagline.data
                operator.logo_url = form.logo_url.data
                operator.brand_color = form.brand_color.data or operator.brand_color
                operator.support_email = form.support_email.data
                operator.primary_location_id = form.primary_location_id.data or None
                operator.payment_instructions = form.payment_instructions.data
                operator.payment_upi_id = form.payment_upi_id.data
                operator.payment_gpay = form.payment_gpay.data
                operator.payment_bank_details = form.payment_bank_details.data
                if not operator.payment_bank_details:
                    bank_parts = [form.bank_name.data] if form.bank_name.data else []
                    for label, value in (("Account holder", form.payment_bank_account_name.data),
                                         ("Account", form.payment_bank_account_number.data),
                                         ("IFSC", form.payment_bank_ifsc_or_routing.data)):
                        if value:
                            bank_parts.append(f"{label}: {value}")
                    operator.payment_bank_details = "; ".join(bank_parts) or None
                db.session.commit()
                flash("Workspace settings saved.", "success")
                return redirect(url_for("admin.settings"))
            counts = {"locations": Location.query.count(), "seats": Seat.query.count(),
                      "staff": User.query.filter(User.role.in_([UserRole.SUPER_ADMIN, UserRole.MANAGER, UserRole.LOCATION_MANAGER])).count()}
            documents = Document.query.filter_by(owner_type="operator", operator_id=operator.id).all()
            return render_template("admin/operator_settings.html", form=form, operator=operator,
                                   profile_groups=PROFILE_GROUPS, counts=counts, documents=documents)

        s = SystemSettings.get()
        form = SystemSettingsForm(obj=s)
        if form.validate_on_submit():
            form.populate_obj(s)
            db.session.commit()
            audit_service.record("settings.updated", "settings", s.id,
                                 {"currency": s.currency_code, "tz": s.timezone,
                                  "tax_rate": str(s.default_tax_rate)})
            flash("Settings saved. Currency, timezone, and date formats updated system-wide.", "success")
            return redirect(url_for("admin.settings"))
        return render_template("admin/settings.html", form=form, s=s)
