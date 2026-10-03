"""Download links on the document lists: scoped to the caller, local files from disk, cloud files by short-lived signed link."""
import io
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from flask_login import login_user, logout_user

os.environ.setdefault("FLASK_ENV", "testing")

from app.extensions import db
from app.models import Company, CompanyDocument, Document, DocumentKind, Operator, User, UserRole
from app.services.operator_quotas import QuotaExceeded
from app.services.storage import S3Backend, storage_service
from tests.test_download_isolation import _app, _client
from tests.test_role_paths import APEX, DEMO, OTHER, OWNER_PASSWORD


def _documents(app, tmp_path):
    """One file each for the demo workspace, Acme, an expense receipt, the other workspace and the platform."""
    with app.app_context():
        everything = {"skip_operator_filter": True}
        demo = Operator.query.filter_by(slug="demo").one().id
        other = Operator.query.filter_by(slug="other").one().id
        acme = Company.query.execution_options(**everything).filter_by(name="Acme Co").one().id
        specs = [("workspace", demo, "operator", f"operators/{demo}/documents/workspace.pdf", b"workspace file"),
                 ("company", demo, "company", f"operators/{demo}/companies/{acme}/kyc.pdf", b"company file"),
                 ("receipt", demo, "expense", f"operators/{demo}/expenses/receipt.pdf", b"receipt file"),
                 ("other", other, "operator", f"operators/{other}/documents/theirs.pdf", b"other file"),
                 ("platform", None, "platform", "platform/documents/internal.pdf", b"platform file")]
        ids = {"acme": acme}
        for name, operator_id, owner_type, key, content in specs:
            path = Path(tmp_path) / key
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            doc = Document(operator_id=operator_id, kind=DocumentKind.KYC, owner_type=owner_type, owner_id=operator_id,
                           filename=f"{name}.pdf", content_type="application/pdf", size_bytes=len(content),
                           storage_backend="local", storage_key=key)
            db.session.add(doc)
            db.session.flush()
            if owner_type == "company":
                db.session.add(CompanyDocument(operator_id=operator_id, company_id=acme, document_id=doc.id))
            ids[name] = doc.id
        db.session.commit()
    return ids


def test_each_document_list_links_to_a_scoped_download(tmp_path):
    app = _app(tmp_path)
    ids = _documents(app, tmp_path)

    owner = _client(app, DEMO, "owner@demospace.com")
    page = owner.get("/admin/documents", headers={"Host": DEMO}).get_data(as_text=True)
    assert f"/admin/documents/{ids['workspace']}/download" in page and "hub1z-platform-documents" not in page
    company_page = owner.get(f"/admin/companies/{ids['acme']}/documents", headers={"Host": DEMO}).get_data(as_text=True)
    assert f"/admin/documents/{ids['company']}/download" in company_page

    for name, content in (("workspace", b"workspace file"), ("company", b"company file"), ("receipt", b"receipt file")):
        response = owner.get(f"/admin/documents/{ids[name]}/download", headers={"Host": DEMO})
        assert response.status_code == 200 and response.data == content, name
        assert response.headers["Content-Disposition"].startswith("attachment") and f"{name}.pdf" in response.headers["Content-Disposition"]
    assert [owner.get(f"/admin/documents/{ids[name]}/download", headers={"Host": DEMO}).status_code
            for name in ("other", "platform")] == [404, 404]

    other = _client(app, OTHER, "owner@otherspace.com")
    assert other.get(f"/admin/documents/{ids['workspace']}/download", headers={"Host": OTHER}).status_code == 404
    assert other.get(f"/admin/documents/{ids['other']}/download", headers={"Host": OTHER}).status_code == 200

    company_admin = _client(app, DEMO, "admin@acmeco.com")
    assert company_admin.get(f"/admin/documents/{ids['company']}/download", headers={"Host": DEMO}).status_code == 403
    assert app.test_client().get(f"/admin/documents/{ids['workspace']}/download", headers={"Host": DEMO}).status_code in (302, 401)


def test_platform_documents_download_only_for_staff_with_the_documents_grant(tmp_path):
    app = _app(tmp_path)
    ids = _documents(app, tmp_path)
    with app.app_context():
        for email, grants in (("docs-manager@hub1z.com", ["documents"]), ("leads-manager@hub1z.com", ["leads"])):
            manager = User(email=email, full_name=email, role=UserRole.PLATFORM_MANAGER, is_active=True)
            manager.set_password("ManagerPass123!")
            manager.set_platform_permissions(grants)
            db.session.add(manager)
        db.session.commit()

    owner = _client(app, APEX, "admin@hub1z.com", OWNER_PASSWORD)
    assert f"/platform/documents/{ids['platform']}/download" in owner.get("/platform/documents", headers={"Host": APEX}).get_data(as_text=True)
    response = owner.get(f"/platform/documents/{ids['platform']}/download", headers={"Host": APEX})
    assert response.status_code == 200 and response.data == b"platform file"
    assert [owner.get(f"/platform/documents/{ids[name]}/download", headers={"Host": APEX}).status_code
            for name in ("workspace", "other")] == [404, 404]

    allowed = _client(app, APEX, "docs-manager@hub1z.com", "ManagerPass123!")
    assert allowed.get(f"/platform/documents/{ids['platform']}/download", headers={"Host": APEX}).status_code == 200
    denied = _client(app, APEX, "leads-manager@hub1z.com", "ManagerPass123!")
    assert denied.get(f"/platform/documents/{ids['platform']}/download", headers={"Host": APEX}).status_code == 403


def test_cloud_documents_redirect_to_a_short_signed_link(tmp_path, monkeypatch):
    app = _app(tmp_path)
    ids = _documents(app, tmp_path)
    with app.app_context():
        for doc in Document.query.execution_options(skip_operator_filter=True).all():
            doc.storage_backend, doc.storage_bucket = "s3", f"bucket-for-{doc.owner_type}"
        db.session.commit()
    calls = []

    def fake_signed_url(key, ttl_seconds=None, scope="operator", bucket=None, filename=None):
        calls.append((key, ttl_seconds, scope, bucket, filename))
        return "https://signed.example/link"

    monkeypatch.setattr(storage_service, "signed_url", fake_signed_url)
    owner = _client(app, DEMO, "owner@demospace.com")
    response = owner.get(f"/admin/documents/{ids['workspace']}/download", headers={"Host": DEMO})
    assert response.status_code == 302 and response.headers["Location"] == "https://signed.example/link"
    assert calls[-1][1:] == (300, "operator", "bucket-for-operator", "workspace.pdf")

    platform = _client(app, APEX, "admin@hub1z.com", OWNER_PASSWORD)
    platform.get(f"/platform/documents/{ids['platform']}/download", headers={"Host": APEX})
    assert calls[-1][1:] == (300, "platform", "bucket-for-platform", "platform.pdf")


def test_s3_link_forces_a_download_with_a_safe_filename():
    captured = {}
    backend = S3Backend.__new__(S3Backend)
    backend.bucket, backend.url_ttl = "bucket", 3600
    backend.client = SimpleNamespace(generate_presigned_url=lambda operation, Params, ExpiresIn: captured.update(
        operation=operation, params=Params, ttl=ExpiresIn) or "https://signed.example/link")
    backend.get_url("documents/operators/1/documents/a.pdf", 300, 'a\r\nSet-Cookie: x".pdf')
    assert captured["ttl"] == 300
    assert captured["params"]["ResponseContentDisposition"] == "attachment; filename*=UTF-8''a%0D%0ASet-Cookie%3A%20x%22.pdf"


def _upload(client, host, path, kind, tag, name="scan.pdf"):
    return client.post(path, data={"kind": kind, "tag": tag, "file": (io.BytesIO(b"%PDF-1.4 test"), name)},
                       headers={"Host": host}, content_type="multipart/form-data")


def test_documents_take_a_tag_that_is_required_for_other_and_searchable(tmp_path):
    app = _app(tmp_path)
    owner = _client(app, DEMO, "owner@demospace.com")
    refused = _upload(owner, DEMO, "/admin/documents", "other", "  ")
    assert refused.status_code == 200 and b"Add a tag or short description" in refused.data
    with app.app_context():
        assert Document.query.count() == 0

    assert _upload(owner, DEMO, "/admin/documents", "other", "Fire safety certificate 2026", "a.pdf").status_code == 302
    assert _upload(owner, DEMO, "/admin/documents", "kyc", "", "b.pdf").status_code == 302
    page = owner.get("/admin/documents", headers={"Host": DEMO}).get_data(as_text=True)
    assert "Fire safety certificate 2026" in page and "a.pdf" in page and "b.pdf" in page
    found = owner.get("/admin/documents?q=FIRE", headers={"Host": DEMO}).get_data(as_text=True)
    assert "a.pdf" in found and "b.pdf" not in found
    assert "b.pdf" in owner.get("/admin/documents?q=b.pdf", headers={"Host": DEMO}).get_data(as_text=True)
    assert "match your search" in owner.get("/admin/documents?q=%25", headers={"Host": DEMO}).get_data(as_text=True)

    with app.app_context():
        acme = Company.query.execution_options(skip_operator_filter=True).filter_by(name="Acme Co").one().id
    assert _upload(owner, DEMO, f"/admin/companies/{acme}/documents", "other", "Signed lease addendum").status_code == 302
    company_page = owner.get(f"/admin/companies/{acme}/documents?q=lease", headers={"Host": DEMO}).get_data(as_text=True)
    assert "Signed lease addendum" in company_page
    assert "Signed lease addendum" not in owner.get(f"/admin/companies/{acme}/documents?q=zzz", headers={"Host": DEMO}).get_data(as_text=True)

    platform = _client(app, APEX, "admin@hub1z.com", OWNER_PASSWORD)
    assert _upload(platform, APEX, "/platform/documents", "other", "").status_code == 200
    assert _upload(platform, APEX, "/platform/documents", "other", "Company registration").status_code == 302
    assert "Company registration" in platform.get("/platform/documents?q=registration", headers={"Host": APEX}).get_data(as_text=True)


def test_only_platform_staff_can_map_a_custom_domain_without_white_label(tmp_path):
    app = _app(tmp_path)
    with app.test_request_context("/"):
        everything = {"skip_operator_filter": True}
        staff = User.query.execution_options(**everything).filter_by(email="admin@hub1z.com").one()
        login_user(staff)
        Operator.query.filter_by(slug="demo").one().custom_domain = "demo-space.example.com"
        db.session.commit()
        assert Operator.query.filter_by(slug="demo").one().custom_domain == "demo-space.example.com"
        logout_user()

        owner = User.query.execution_options(**everything).filter_by(email="owner@otherspace.com").one()
        login_user(owner)
        Operator.query.filter_by(slug="other").one().custom_domain = "other-space.example.com"
        with pytest.raises(QuotaExceeded):
            db.session.commit()
        db.session.rollback()
