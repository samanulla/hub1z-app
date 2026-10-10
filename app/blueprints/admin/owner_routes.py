"""Operator profile, part 2: the business owner, the representative's authority and the owner's KYC documents."""
from __future__ import annotations

from flask import flash, g, redirect, render_template, url_for
from flask_login import current_user
from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, FileField
from wtforms import BooleanField, RadioField, StringField, SubmitField
from wtforms.validators import Email, Length, Optional

from ...extensions import db
from ...models import Document, DocumentKind
from ...services import audit_service, owner_details as owner
from ...services.storage import storage_service
from ...utils.decorators import super_admin_required

ALLOWED = ["pdf", "png", "jpg", "jpeg"]


class OwnerDetailsForm(FlaskForm):
    owner_setup_role = RadioField("Who is setting up this account?", choices=owner.ROLE_CHOICES,
                                  validators=[Optional()])
    rep_designation = StringField("Your role in the business", validators=[Optional(), Length(max=120)],
                                  description="For example Manager, Finance head or Company secretary.")
    owner_name = StringField("Owner or director's full name", validators=[Optional(), Length(max=150)])
    owner_designation = StringField("Designation", validators=[Optional(), Length(max=120)],
                                    description="Proprietor, Partner, Director, Managing Partner and so on.")
    owner_mobile = StringField("Owner's mobile number", validators=[Optional(), Length(max=20)])
    owner_email = StringField("Owner's email", validators=[Optional(), Email(), Length(max=255)])
    owner_pan = StringField("Owner's PAN", validators=[Optional(), Length(max=10)],
                            description="Optional. Used only to match the PAN card you upload.")
    rep_declaration = BooleanField("I confirm that I am authorised by the owner or director to set up and manage "
                                   "this account and to accept Hub1z's terms for the business.")
    pan_file = FileField("Owner PAN card", validators=[FileAllowed(ALLOWED, "Upload a PDF, PNG or JPG.")])
    id_file = FileField("Owner ID proof", validators=[FileAllowed(ALLOWED, "Upload a PDF, PNG or JPG.")])
    auth_file = FileField("Authorisation letter", validators=[FileAllowed(ALLOWED, "Upload a PDF, PNG or JPG.")])
    submit = SubmitField("Save owner details")

    def validate(self, extra_validators=None):
        ok = super().validate(extra_validators)
        if self.owner_mobile.data and not owner.mobile_ok(self.owner_mobile.data):
            self.owner_mobile.errors.append("Enter a 10-digit Indian mobile number.")
            ok = False
        if self.owner_pan.data and not owner.pan_ok(self.owner_pan.data):
            self.owner_pan.errors.append("A PAN looks like ABCDE1234F.")
            ok = False
        if self.owner_setup_role.data == owner.ROLE_REP and not self.rep_designation.data:
            self.rep_designation.errors.append("Tell us your role in the business.")
            ok = False
        return ok


def _store(operator, upload, tag: str) -> None:
    stored = storage_service.upload(namespace=f"operators/{operator.id}/owner-kyc", filename=upload.filename,
                                    stream=upload.stream, content_type=upload.mimetype, scope="operator")
    db.session.add(Document(
        operator_id=operator.id, kind=DocumentKind.KYC, owner_type="operator", owner_id=operator.id,
        filename=upload.filename, tag=tag, content_type=upload.mimetype, size_bytes=stored.size_bytes,
        storage_backend=stored.backend, storage_bucket=stored.bucket, storage_key=stored.key,
        uploaded_by_id=current_user.id))


def register_owner_routes(bp):

    @bp.route("/settings/owner", methods=["GET", "POST"])
    @super_admin_required
    def owner_details_page():
        operator = g.operator
        saved = owner.details(operator)
        form = OwnerDetailsForm(data={**saved, "rep_declaration": bool(saved["rep_declaration_at"])})
        if form.validate_on_submit():
            data = dict(operator.profile_details or {})
            data["owner_setup_role"] = form.owner_setup_role.data or None
            data["rep_designation"] = (form.rep_designation.data or "").strip() or None
            data["owner_name"] = (form.owner_name.data or "").strip() or None
            data["owner_designation"] = (form.owner_designation.data or "").strip() or None
            data["owner_mobile"] = owner.clean_mobile(form.owner_mobile.data) or None
            data["owner_email"] = (form.owner_email.data or "").strip().lower() or None
            data["owner_pan"] = (form.owner_pan.data or "").strip().upper() or None
            operator.profile_details = data
            if form.owner_setup_role.data == owner.ROLE_REP and form.rep_declaration.data:
                if not saved["rep_declaration_at"]:
                    owner.declare(operator, current_user.full_name)
            else:
                data = dict(operator.profile_details)
                data["rep_declaration_at"] = data["rep_declaration_by"] = None
                operator.profile_details = data
            for field, tag in ((form.pan_file, owner.DOC_PAN), (form.id_file, owner.DOC_ID),
                               (form.auth_file, owner.DOC_AUTH)):
                if field.data and getattr(field.data, "filename", ""):
                    _store(operator, field.data, tag)
            audit_service.record("operator.owner_details", "operator", operator.id,
                                 {"role": form.owner_setup_role.data, "by": current_user.email})
            db.session.commit()
            flash("Owner details saved.", "success")
            return redirect(url_for("admin.owner_details_page"))
        return render_template("admin/owner_details.html", form=form, status=owner.status(operator),
                               labels=owner.DOC_LABELS, operator=operator)
