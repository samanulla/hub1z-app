"""Admin routes for email templates."""
from __future__ import annotations

from flask import render_template, redirect, url_for, flash, request
from flask_login import current_user
from jinja2 import Environment, BaseLoader, TemplateSyntaxError

from ...extensions import db
from ...models import EmailTemplate, EmailKind
from ...utils.decorators import admin_required, super_admin_required
from .forms import EmailTemplateForm


_SAMPLE_CONTEXT = {
    "user": {"full_name": "Jane Doe", "email": "jane@example.com"},
    "company": {"name": "Acme Robotics"},
    "booking": {"room_name": "Hudson", "start_at": "2026-01-15 14:00",
                "end_at": "2026-01-15 15:00", "credits_used": 1,
                "total_amount": "0.00"},
    "invoice": {"number": "INV-202601-00042", "total_amount": "1299.00",
                "due_date": "2026-02-15"},
    "app": {"name": "hub1z", "base_url": "https://hub1z.example.com"},
    "temp_password": "S3cure!Temp",
}


def _render_sample(template_source: str) -> tuple[str, str | None]:
    """Render a template with sample context. Returns (output, error)."""
    try:
        env = Environment(loader=BaseLoader(), autoescape=True)
        tpl = env.from_string(template_source)
        return tpl.render(**_SAMPLE_CONTEXT), None
    except TemplateSyntaxError as e:
        return "", f"Template syntax error: {e.message} (line {e.lineno})"
    except Exception as e:  # noqa: BLE001
        return "", f"Render error: {e}"


def register_email_template_routes(bp):

    @bp.route("/email-templates")
    @admin_required
    def email_templates():
        templates = EmailTemplate.query.order_by(EmailTemplate.kind, EmailTemplate.name).all()
        return render_template("admin/email_templates/list.html", templates=templates)

    @bp.route("/email-templates/new", methods=["GET", "POST"])
    @admin_required
    def email_template_new():
        form = EmailTemplateForm()
        preview_subject = preview_body = preview_error = None
        if request.method == "POST" and request.form.get("action") == "preview":
            preview_subject, subj_err = _render_sample(request.form.get("subject", ""))
            preview_body, body_err = _render_sample(request.form.get("body_html", ""))
            preview_error = subj_err or body_err
        elif form.validate_on_submit():
            t = EmailTemplate(updated_by_id=current_user.id)
            form.populate_obj(t)
            db.session.add(t)
            db.session.commit()
            flash("Email template created.", "success")
            return redirect(url_for("admin.email_templates"))
        return render_template("admin/email_templates/form.html", form=form,
                               title="New email template",
                               preview_subject=preview_subject,
                               preview_body=preview_body,
                               preview_error=preview_error,
                               sample_context=_SAMPLE_CONTEXT)

    @bp.route("/email-templates/<int:tpl_id>/edit", methods=["GET", "POST"])
    @admin_required
    def email_template_edit(tpl_id: int):
        t = EmailTemplate.query.get_or_404(tpl_id)
        form = EmailTemplateForm(obj=t)
        preview_subject = preview_body = preview_error = None
        if request.method == "POST" and request.form.get("action") == "preview":
            preview_subject, subj_err = _render_sample(request.form.get("subject", ""))
            preview_body, body_err = _render_sample(request.form.get("body_html", ""))
            preview_error = subj_err or body_err
        elif form.validate_on_submit():
            form.populate_obj(t)
            t.updated_by_id = current_user.id
            db.session.commit()
            flash("Template updated.", "success")
            return redirect(url_for("admin.email_templates"))
        return render_template("admin/email_templates/form.html", form=form,
                               title=f"Edit {t.name}",
                               preview_subject=preview_subject,
                               preview_body=preview_body,
                               preview_error=preview_error,
                               sample_context=_SAMPLE_CONTEXT)

    @bp.route("/email-templates/<int:tpl_id>/delete", methods=["POST"])
    @super_admin_required
    def email_template_delete(tpl_id: int):
        t = EmailTemplate.query.get_or_404(tpl_id)
        db.session.delete(t)
        db.session.commit()
        flash("Template deleted.", "info")
        return redirect(url_for("admin.email_templates"))
