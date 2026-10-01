"""PDF documents for invoices, receipts and credit notes (company, operator and Platform billing), and the menu layout."""
import os
from datetime import date, datetime
from decimal import Decimal

os.environ.setdefault("FLASK_ENV", "testing")

from app.cli import PERSONA_PASSWORD
from app.extensions import db
from app.models import (Company, CreditNote, CreditNoteStatus, Invoice, InvoiceStatus, Operator, Payment,
                        PlatformCreditNote, PlatformInvoice, PlatformInvoiceStatus, PlatformRefund)
from tests.test_role_paths import APEX, DEMO, OTHER, OWNER_PASSWORD, _login, _seeded_app


def _client(app, host, email, password):
    c = app.test_client()
    assert _login(c, host, email, password).status_code == 302, email
    return c


def _get(c, host, path):
    return c.get(path, headers={"Host": host})


def _operator_id(app, host):
    with app.app_context():
        return Operator.query.filter_by(primary_domain=host).one().id


def _acme_ids(app):
    """(company id, an issued invoice id with a payment, that payment's id)."""
    with app.app_context():
        company = Company.query.execution_options(skip_operator_filter=True).filter_by(name="Acme Co").first()
        for inv in Invoice.query.execution_options(skip_operator_filter=True).filter_by(company_id=company.id).all():
            if inv.status != InvoiceStatus.DRAFT and inv.payments:
                return company.id, inv.id, inv.payments[0].id
    raise AssertionError("seed has no paid Acme invoice")


def _is_pdf(r):
    return r.status_code == 200 and r.mimetype == "application/pdf" and r.data[:5] == b"%PDF-"


def test_company_admin_can_view_invoice_receipt_and_credit_note_pdfs():
    app, _ = _seeded_app()
    company_id, invoice_id, payment_id = _acme_ids(app)
    with app.app_context():
        db.session.add(CreditNote(operator_id=_operator_id(app, DEMO), number="CN-T-1", company_id=company_id,
                                  invoice_id=invoice_id, amount=Decimal("500"), reason="Goodwill",
                                  status=CreditNoteStatus.ISSUED, issued_at=datetime.utcnow()))
        db.session.add(CreditNote(operator_id=_operator_id(app, DEMO), number="CN-T-2", company_id=company_id,
                                  amount=Decimal("100"), reason="Cancelled one", status=CreditNoteStatus.CANCELLED))
        db.session.commit()
        note_id = CreditNote.query.execution_options(skip_operator_filter=True).filter_by(number="CN-T-1").one().id
        cancelled_id = CreditNote.query.execution_options(skip_operator_filter=True).filter_by(number="CN-T-2").one().id

    c = _client(app, DEMO, "admin@acmeco.com", PERSONA_PASSWORD)
    page = _get(c, DEMO, "/company/invoices").data.decode()
    for needle in (f"/company/invoices/{invoice_id}/pdf", f"/company/payments/{payment_id}/receipt.pdf",
                   f"/company/credit-notes/{note_id}/pdf", "View PDF", "Payments received", "Credit notes"):
        assert needle in page, needle
    assert f"/company/credit-notes/{cancelled_id}/pdf" not in page

    assert _is_pdf(_get(c, DEMO, f"/company/invoices/{invoice_id}/pdf"))
    assert _is_pdf(_get(c, DEMO, f"/company/payments/{payment_id}/receipt.pdf"))
    assert _is_pdf(_get(c, DEMO, f"/company/credit-notes/{note_id}/pdf"))
    assert _get(c, DEMO, f"/company/credit-notes/{cancelled_id}/pdf").status_code == 404
    download = _get(c, DEMO, f"/company/invoices/{invoice_id}/pdf?download=1")
    assert "attachment" in download.headers["Content-Disposition"]


def test_documents_stay_inside_the_right_company_and_operator():
    app, _ = _seeded_app()
    _, invoice_id, payment_id = _acme_ids(app)
    employee = _client(app, DEMO, "employee@acmeco.com", PERSONA_PASSWORD)
    assert _get(employee, DEMO, f"/company/invoices/{invoice_id}/pdf").status_code == 403
    other = _client(app, OTHER, "owner@otherspace.com", PERSONA_PASSWORD)
    assert _get(other, OTHER, f"/admin/invoices/{invoice_id}/pdf").status_code == 404
    assert _get(other, OTHER, f"/admin/payments/{payment_id}/receipt.pdf").status_code == 404


def test_operator_back_office_links_to_the_same_documents():
    app, _ = _seeded_app()
    _, invoice_id, payment_id = _acme_ids(app)
    owner = _client(app, DEMO, "owner@demospace.com", PERSONA_PASSWORD)
    assert b"View PDF" in _get(owner, DEMO, "/admin/invoices").data
    detail = _get(owner, DEMO, f"/admin/invoices/{invoice_id}").data.decode()
    assert f"/admin/payments/{payment_id}/receipt.pdf" in detail and "View PDF" in detail
    assert _is_pdf(_get(owner, DEMO, f"/admin/invoices/{invoice_id}/pdf"))
    receipt = _get(owner, DEMO, f"/admin/payments/{payment_id}/receipt.pdf")
    assert _is_pdf(receipt)


def test_operator_sees_only_its_own_hub1z_invoices_with_pdfs_and_platform_staff_can_open_them_too():
    app, _ = _seeded_app()
    demo_id, other_id = _operator_id(app, DEMO), _operator_id(app, OTHER)
    with app.app_context():
        for op_id, number in ((demo_id, "HUB-T-DEMO"), (other_id, "HUB-T-OTHER")):
            inv = PlatformInvoice(operator_id=op_id, number=number, period_start=date(2026, 10, 1),
                                  period_end=date(2026, 10, 31), due_date=date(2026, 11, 10), amount=Decimal("4999"),
                                  status=PlatformInvoiceStatus.ISSUED)
            db.session.add(inv)
            db.session.flush()
            db.session.add(PlatformCreditNote(operator_id=op_id, invoice_id=inv.id, number=f"{number}-CN",
                                              amount=Decimal("500"), reason="Goodwill", issued_at=datetime.utcnow()))
            db.session.add(PlatformRefund(operator_id=op_id, invoice_id=inv.id, number=f"{number}-RF",
                                          amount=Decimal("250"), reason="Overpaid", processed_at=datetime.utcnow()))
        db.session.commit()
        ids = {i.number: i.id for i in PlatformInvoice.query.all()}
        note_ids = {n.number: n.id for n in PlatformCreditNote.query.all()}
        refund_ids = {r.number: r.id for r in PlatformRefund.query.all()}

    owner = _client(app, DEMO, "owner@demospace.com", PERSONA_PASSWORD)
    page = _get(owner, DEMO, "/admin/hub1z-billing").data.decode()
    assert "HUB-T-DEMO" in page and "HUB-T-OTHER" not in page and "Credit notes" in page and "Refunds" in page
    mine = _get(owner, DEMO, f"/admin/hub1z-billing/invoices/{ids['HUB-T-DEMO']}.pdf")
    assert _is_pdf(mine)
    assert _is_pdf(_get(owner, DEMO, f"/admin/hub1z-billing/credit-notes/{note_ids['HUB-T-DEMO-CN']}.pdf"))
    assert _is_pdf(_get(owner, DEMO, f"/admin/hub1z-billing/refunds/{refund_ids['HUB-T-DEMO-RF']}.pdf"))
    assert _get(owner, DEMO, f"/admin/hub1z-billing/invoices/{ids['HUB-T-OTHER']}.pdf").status_code == 404
    assert _get(owner, DEMO, f"/admin/hub1z-billing/credit-notes/{note_ids['HUB-T-OTHER-CN']}.pdf").status_code == 404
    company_admin = _client(app, DEMO, "admin@acmeco.com", PERSONA_PASSWORD)
    assert _get(company_admin, DEMO, "/admin/hub1z-billing").status_code == 403

    platform = _client(app, APEX, "admin@hub1z.com", OWNER_PASSWORD)
    finance = _get(platform, APEX, "/platform/finance").data.decode()
    assert f"/platform/finance/invoices/{ids['HUB-T-DEMO']}/pdf" in finance
    assert _is_pdf(_get(platform, APEX, f"/platform/finance/invoices/{ids['HUB-T-OTHER']}/pdf"))
    assert _is_pdf(_get(platform, APEX, f"/platform/finance/credit-notes/{note_ids['HUB-T-DEMO-CN']}/pdf"))
    assert _is_pdf(_get(platform, APEX, f"/platform/finance/refunds/{refund_ids['HUB-T-DEMO-RF']}/pdf"))


def test_check_in_qr_leads_the_menu_and_the_top_bar_for_everyone_who_can_use_it():
    app, _ = _seeded_app()
    for email, landing in (("owner@demospace.com", "/admin/"), ("admin@acmeco.com", "/company/"),
                           ("employee@acmeco.com", "/me/"), ("individual@demospace.com", "/me/")):
        c = _client(app, DEMO, email, PERSONA_PASSWORD)
        html = _get(c, DEMO, landing).data
        assert b"h-top-checkin" in html, email
        assert html.index(b"h-nav-cta") < html.index(b'class="h-nav-label"'), email  # above the first menu group
        assert html.count(b'href="/checkin/pass"') >= 2, email  # menu and top bar
    platform = _client(app, APEX, "admin@hub1z.com", OWNER_PASSWORD)
    assert b"h-top-checkin" not in _get(platform, APEX, "/platform/").data


def test_book_and_calendar_sit_with_the_workspace_items_and_community_is_its_own_group():
    app, _ = _seeded_app()
    company_admin = _client(app, DEMO, "admin@acmeco.com", PERSONA_PASSWORD)
    html = _get(company_admin, DEMO, "/company/").data
    group = html.index(b">People &amp; workspace<")
    assert group < html.index(b">Book<") < html.index(b">Calendar<") < html.index(b">People<")
    assert b"Book &amp; community" not in html
    assert html.index(b">Plan &amp; billing<") < html.index(b">Community<") < html.index(b">Member directory<")
    assert b">Support tickets<" in html and b">Guest passes<" in html

    for email in ("employee@acmeco.com", "individual@demospace.com"):
        c = _client(app, DEMO, email, PERSONA_PASSWORD)
        html = _get(c, DEMO, "/me/").data
        assert html.index(b">My space<") < html.index(b">Book<") < html.index(b">Calendar<") < html.index(b">Community<"), email
        assert b">Announcements<" in html and b">Guest passes<" in html

    owner = _client(app, DEMO, "owner@demospace.com", PERSONA_PASSWORD)
    html = _get(owner, DEMO, "/admin/").data
    assert html.index(b">Workspace<") < html.index(b">Book<") < html.index(b">Locations &amp; seats<")
    assert b"Book &amp; community" not in html and b">Hub1z invoices<" in html
    assert html.index(b">Community<") < html.index(b">Lockers<") and b">Reception<" in html
    assert b">Hub1z invoices<" not in _get(company_admin, DEMO, "/company/").data
