"""Admin routes for system-wide settings (super-admin only)."""
from __future__ import annotations

from flask import render_template, redirect, url_for, flash, g
from flask_login import current_user

from ...extensions import db
from ...models import SystemSettings, Location, UserRole
from ...services import audit_service
from ...utils.decorators import super_admin_required
from .forms import SystemSettingsForm, TenantSettingsForm


def register_settings_routes(bp):

    @bp.route("/settings", methods=["GET", "POST"])
    @super_admin_required
    def settings():
        if current_user.role == UserRole.SUPER_ADMIN and getattr(g, "tenant", None):
            tenant = g.tenant
            form = TenantSettingsForm()
            form.primary_location_id.choices = [(0, "No primary location")] + [
                (loc.id, f"{loc.name} ({loc.code})")
                for loc in Location.query.filter_by(is_active=True).order_by(Location.name).all()
            ]
            if not form.is_submitted():
                form.primary_location_id.data = tenant.primary_location_id or 0
                form.payment_instructions.data = tenant.payment_instructions
                form.payment_upi_id.data = tenant.payment_upi_id
                form.payment_gpay.data = tenant.payment_gpay
                form.payment_bank_details.data = tenant.payment_bank_details
            if form.validate_on_submit():
                tenant.primary_location_id = form.primary_location_id.data or None
                tenant.payment_instructions = form.payment_instructions.data
                tenant.payment_upi_id = form.payment_upi_id.data
                tenant.payment_gpay = form.payment_gpay.data
                tenant.payment_bank_details = form.payment_bank_details.data
                db.session.commit()
                flash("Primary billing location saved.", "success")
                return redirect(url_for("admin.settings"))
            return render_template("admin/tenant_settings.html", form=form, tenant=tenant)

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
