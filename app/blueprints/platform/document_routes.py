"""Platform-owned document storage."""
from __future__ import annotations

from flask import render_template, redirect, url_for, flash, request
from flask_login import current_user
from sqlalchemy import or_

from ...extensions import db
from ...models import Document, DocumentKind
from ...services import audit_service
from ...services.storage import storage_service
from ...utils.decorators import platform_permission_required
from ..admin.forms import DocumentUploadForm


def register_document_routes(bp):
    @bp.route("/documents", methods=["GET", "POST"])
    @platform_permission_required("documents")
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
                operator_id=None,
                kind=DocumentKind(form.kind.data),
                owner_type="platform",
                owner_id=current_user.id,
                filename=f.filename,
                tag=(form.tag.data or "").strip() or None,
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
        q = (request.args.get("q") or "").strip()
        query = (Document.query.execution_options(skip_operator_filter=True)
                 .filter_by(owner_type="platform"))
        if q:
            query = query.filter(or_(Document.filename.icontains(q, autoescape=True), Document.tag.icontains(q, autoescape=True)))
        documents = query.order_by(Document.created_at.desc()).all()
        return render_template("platform/documents.html", form=form, documents=documents, q=q)

    @bp.route("/documents/<int:doc_id>/download")
    @platform_permission_required("documents")
    def platform_document_download(doc_id: int):
        doc = (Document.query.execution_options(skip_operator_filter=True)
               .filter_by(id=doc_id, owner_type="platform", operator_id=None).first_or_404())
        audit_service.record("document.downloaded", "document", doc.id, {"owner_type": "platform"})
        return storage_service.download(doc, scope="platform")
