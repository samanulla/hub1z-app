import os

os.environ.setdefault("FLASK_ENV", "testing")

from app.extensions import db
from app.models import Company, CompanyDocument, Document, DocumentKind, Operator, Invoice
from flask import render_template
from app.services.pdf_docs import rs
from tests.test_release_upi_parcels_alerts import DEMO, _client, _get, _post, _seeded_app


def test_company_profile_optional_details_persist():
    app, _ = _seeded_app()
    client = _client(app, DEMO, "admin@acmeco.com")
    response = _post(client, DEMO, "/company/profile", {
        "name": "Acme Co", "legal_name": "Acme Legal LLP", "billing_email": "billing@acme.com",
        "company_type": "LLP", "contact_name": "Acme Contact", "address_line1": "10 Main Road",
        "city": "Chennai", "state": "Tamil Nadu", "pin_code": "600020", "cin_llpin": "LLP-123",
    })
    assert response.status_code == 302
    with app.app_context():
        company = Company.query.execution_options(skip_operator_filter=True).filter_by(name="Acme Co").one()
        assert company.profile_details["company_type"] == "LLP"
        assert company.profile_details["contact_name"] == "Acme Contact"
        assert company.billing_address == "10 Main Road, Chennai, Tamil Nadu, 600020"
    page = _get(client, DEMO, "/company/profile")
    assert page.status_code == 200 and b'Acme Contact' in page.data
    assert _get(client, DEMO, "/company/documents").status_code == 200
    with app.test_request_context(base_url=f"http://{DEMO}"):
        company = Company.query.execution_options(skip_operator_filter=True).filter_by(name="Acme Co").one()
        invoice = Invoice.query.execution_options(skip_operator_filter=True).filter_by(company_id=company.id).first()
        rendered = render_template("admin/invoices/pdf.html", invoice=invoice, rs=rs)
        assert "Acme Legal LLP" in rendered and "10 Main Road, Chennai" in rendered


def test_company_documents_only_link_own_documents():
    app, _ = _seeded_app()
    with app.app_context():
        company = Company.query.execution_options(skip_operator_filter=True).filter_by(name="Acme Co").one()
        own = Document(operator_id=company.operator_id, filename="contract.pdf", kind=DocumentKind.CONTRACT,
                       owner_type="company", owner_id=company.id, storage_backend="local", storage_key="contract.pdf")
        other = Operator.query.filter_by(slug="other").one()
        foreign = Document(operator_id=other.id, filename="private.pdf", storage_backend="local", storage_key="private.pdf")
        db.session.add_all([own, foreign])
        db.session.flush()
        db.session.add(CompanyDocument(operator_id=company.operator_id, company_id=company.id, document_id=own.id))
        db.session.commit()
        own_id, foreign_id = own.id, foreign.id
    client = _client(app, DEMO, "admin@acmeco.com")
    page = _get(client, DEMO, "/company/documents")
    assert page.status_code == 200 and b'contract.pdf' in page.data
    assert f'/company/documents/{own_id}/download'.encode() in page.data
    assert _get(client, DEMO, f"/company/documents/{foreign_id}/download").status_code == 404


def test_operator_profile_optional_details_persist():
    app, _ = _seeded_app()
    owner = _client(app, DEMO, "owner@demospace.com")
    response = _post(owner, DEMO, "/admin/settings", {
        "name": "Demo Space", "company_legal_name": "Demo Legal LLP", "company_type": "LLP",
        "contact_name": "Workspace Owner", "billing_email": "billing@demo.com", "bank_name": "Demo Bank",
        "payment_bank_account_name": "Demo Legal LLP", "payment_bank_account_number": "1234567890",
        "payment_bank_ifsc_or_routing": "DEMO0000123", "primary_location_id": "0", "offers_meeting_rooms": "y",
    })
    assert response.status_code == 302
    with app.app_context():
        operator = Operator.query.filter_by(slug="demo").one()
        assert operator.company_legal_name == "Demo Legal LLP"
        assert operator.profile_details["contact_name"] == "Workspace Owner"
        assert operator.profile_details["bank_name"] == "Demo Bank"
        assert operator.payment_bank_account_name == "Demo Legal LLP"
        assert "1234567890" in operator.payment_bank_details and "DEMO0000123" in operator.payment_bank_details
        from app.services.billing_service import billing_snapshot_for_operator
        operator.profile_details = {**operator.profile_details, "address_line1": "5 Business Road", "city": "Chennai"}
        snapshot = billing_snapshot_for_operator(operator)
        assert snapshot["billing_address"] == "5 Business Road" and snapshot["billing_city"] == "Chennai"
    response = _get(owner, DEMO, "/admin/settings")
    assert response.status_code == 200 and b'Workspace Owner' in response.data