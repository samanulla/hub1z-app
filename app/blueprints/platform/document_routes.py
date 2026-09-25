"""Platform-owned document storage."""
from __future__ import annotations

from flask import render_template, redirect, url_for, flash
from flask_login import current_user

from ...extensions import db
from ...models import Document, DocumentKind
from ...services.storage import storage_service
from ...utils.decorators import platform_owner_required
from ..admin.forms import DocumentUploadForm


def register_document_routes(bp):
    @bp.route("/documents", methods=["GET", "POST"])
    @platform_owner_required
    def platform_documents():
        form = DocumentUploadForm()
        if form.validate_on_submit():
            f = form.file.data
            stored = storage_service.upload(
                namespace="platform/documents",
                filename=f.filename,
                stream=f.stream,
                content_type=f.mimetype,
                scope="platform",
            )
            db.session.add(Document(
                tenant_id=None,
                kind=DocumentKind(form.kind.data),
                owner_type="platform",
                owner_id=current_user.id,
                filename=f.filename,
                content_type=f.mimetype,
                size_bytes=stored.size_bytes,
                storage_backend=stored.backend,
                storage_bucket=stored.bucket,
                storage_key=stored.key,
                uploaded_by_id=current_user.id,
            ))
            db.session.commit()
            flash("Platform document uploaded.", "success")
            return redirect(url_for("platform.platform_documents"))
        documents = (Document.query.execution_options(skip_tenant_filter=True)
                     .filter_by(owner_type="platform")
                     .order_by(Document.created_at.desc()).all())
        return render_template("platform/documents.html", form=form, documents=documents)
