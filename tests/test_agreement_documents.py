"""Withdrawing notice, the agreement document (PDF + signed copy), and individuals' subscriptions."""
import os
os.environ.setdefault("FLASK_ENV", "testing")

from datetime import date
from decimal import Decimal
from io import BytesIO

import pytest

from app import create_app
from app.extensions import db
from app.models import (
    Document, DocumentKind, Invoice, InvoiceStatus, Subscription, SubscriptionStatus, User, UserRole,
)
from app.services import billing_service as bs
from app.services import contract_service
from tests.test_billing_agreements import _login, _seed, _sub


def _app(tmp_path):
    app = create_app({"SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:", "WTF_CSRF_ENABLED": False,
                      "MAIL_SUPPRESS_SEND": True, "STORAGE_BACKEND": "local",
                      "LOCAL_STORAGE_DIR": str(tmp_path)})
    with app.app_context():
        db.create_all()
    return app


# ------------------------------------------------------ withdraw notice --

def test_withdrawing_notice_voids_the_unpaid_exit_invoice(tmp_path):
    app = _app(tmp_path)
    ids = _seed(app)
    with app.app_context():
        sub = _sub(ids)
        result = bs.give_notice(sub, date(2026, 2, 1))
        inv = result["early_exit_invoice"]
        db.session.commit()
        out = bs.withdraw_notice(sub, date(2026, 2, 3))
        db.session.commit()
        assert out["voided"] == 1
        assert (sub.notice_given_on, sub.terminate_on) == (None, None)
        assert db.session.get(Invoice, inv.id).status == InvoiceStatus.VOID
        bs.give_notice(sub, date(2026, 2, 5))                          # notice can be given again
        with pytest.raises(bs.BillingError):
            bs.give_notice(sub, date(2026, 2, 6))


def test_a_paid_exit_charge_blocks_withdrawal(tmp_path):
    app = _app(tmp_path)
    ids = _seed(app)
    with app.app_context():
        sub = _sub(ids)
        inv = bs.give_notice(sub, date(2026, 2, 1))["early_exit_invoice"]
        inv.amount_paid, inv.status = Decimal("100"), InvoiceStatus.PARTIAL
        db.session.commit()
        with pytest.raises(bs.BillingError):
            bs.withdraw_notice(sub, date(2026, 2, 3))
        assert sub.terminate_on is not None


def test_withdrawing_restores_a_forfeited_deposit_each_time(tmp_path):
    app = _app(tmp_path)
    ids = _seed(app)
    with app.app_context():
        sub = _sub(ids, early_exit_rule="forfeit_deposit")
        bs.record_deposit(sub, "received", 66000, date(2026, 1, 1))
        for day in (1, 10):
            bs.give_notice(sub, date(2026, 2, day))
            assert bs.deposit_balance(sub) == 0
            assert bs.withdraw_notice(sub, date(2026, 2, day + 1))["restored"] == Decimal("66000.00")
            assert bs.deposit_balance(sub) == Decimal("66000.00")


def test_nothing_to_withdraw_is_an_error(tmp_path):
    app = _app(tmp_path)
    ids = _seed(app)
    with app.app_context():
        with pytest.raises(bs.BillingError):
            bs.withdraw_notice(_sub(ids), date(2026, 2, 3))


def test_withdraw_notice_button(tmp_path):
    app = _app(tmp_path)
    ids = _seed(app)
    with app.app_context():
        sub_id = _sub(ids).id
    c = app.test_client()
    _login(c)
    assert c.post(f"/admin/subscriptions/{sub_id}/notice", data={"notice_date": "2026-02-01"}).status_code == 302
    page = c.get(f"/admin/subscriptions/{sub_id}/agreement").data
    assert b"Withdraw notice" in page
    assert c.post(f"/admin/subscriptions/{sub_id}/notice/withdraw").status_code == 302
    with app.app_context():
        assert db.session.get(Subscription, sub_id).terminate_on is None
    assert b"Withdraw notice" not in c.get(f"/admin/subscriptions/{sub_id}/agreement").data


# ---------------------------------------------------- agreement document --

def test_contract_wording_follows_the_agreed_terms(tmp_path):
    app = _app(tmp_path)
    ids = _seed(app)
    with app.app_context():
        sub = _sub(ids, company="local", late_fee_mode="per_day", late_fee_value=Decimal("100"),
                   late_fee_grace_days=2, notice_months=2)
        ctx = contract_service.build_context(sub)
        assert ctx["monthly_total"] == "Rs. 25,960.00" and ctx["gst_kind"] == "CGST and SGST"
        assert ctx["party"]["gstin"] == "33BBBBB1111B1Z5" and ctx["operator"]["gstin"] == "33AAAAA0000A1Z5"
        assert ctx["deposit"] == "Rs. 66,000.00" and ctx["late"].startswith("Rs. 100.00 for each day")
        far = _sub(ids, company="far")
        assert contract_service.build_context(far)["gst_kind"] == "IGST"
        from flask import render_template
        with app.test_request_context():
            html = render_template("admin/contracts/agreement.html", **ctx)
    assert "Workspace Agreement" in html and "Local Co" in html and "2 months" in html
    assert "DRAFT" not in html


def test_generate_download_and_sign(tmp_path):
    app = _app(tmp_path)
    ids = _seed(app)
    with app.app_context():
        sub_id = _sub(ids).id
    c = app.test_client()
    _login(c)

    assert c.get(f"/admin/subscriptions/{sub_id}/contract/preview").data.startswith(b"%PDF")
    for version in (1, 2):
        assert c.post(f"/admin/subscriptions/{sub_id}/contract").status_code == 302
    with app.app_context():
        docs = Document.query.filter_by(owner_type="subscription", owner_id=sub_id).order_by(Document.id).all()
        assert [d.filename for d in docs] == ["agreement-v1.pdf", "agreement-v2.pdf"]
        assert all(d.kind == DocumentKind.CONTRACT and d.size_bytes > 500 for d in docs)
        first = docs[0].id
    pdf = c.get(f"/admin/documents/{first}/download")
    assert pdf.status_code == 200 and pdf.data.startswith(b"%PDF")

    r = c.post(f"/admin/subscriptions/{sub_id}/signed-copy",
               data={"file": (BytesIO(b"%PDF-1.4 signed by both"), "scan.pdf")}, content_type="multipart/form-data")
    assert r.status_code == 302
    with app.app_context():
        sub = db.session.get(Subscription, sub_id)
        signed = db.session.get(Document, sub.agreement_document_id)
        assert signed.filename == "signed-scan.pdf"
        signed_id = signed.id
    page = c.get(f"/admin/subscriptions/{sub_id}/agreement").data
    assert b"Signed copy" in page and b"agreement-v2.pdf" in page
    assert c.get(f"/admin/documents/{signed_id}/download").data.startswith(b"%PDF-1.4 signed")

    bad = c.post(f"/admin/subscriptions/{sub_id}/signed-copy",
                 data={"file": (BytesIO(b"x"), "virus.exe")}, content_type="multipart/form-data")
    assert bad.status_code == 302
    with app.app_context():
        assert Document.query.filter_by(owner_type="subscription", owner_id=sub_id).count() == 3


def test_only_agreement_documents_can_be_downloaded_here(tmp_path):
    app = _app(tmp_path)
    ids = _seed(app)
    with app.app_context():
        other = Document(operator_id=ids["op"], kind=DocumentKind.KYC, owner_type="company", owner_id=ids["local"],
                         filename="kyc.pdf", size_bytes=1, storage_backend="local", storage_key="x/kyc.pdf")
        db.session.add(other)
        db.session.commit()
        doc_id = other.id
    c = app.test_client()
    _login(c)
    assert c.get(f"/admin/documents/{doc_id}/download").status_code == 404


# -------------------------------------------------------- individuals --

def _individual(ids, email="ivy@example.com"):
    u = User(operator_id=ids["op"], email=email, full_name="Ivy Individual", role=UserRole.INDIVIDUAL, is_active=True)
    u.set_password("IvyPass123!")
    db.session.add(u)
    db.session.commit()
    return u.id


def test_operator_can_subscribe_an_individual_and_see_the_agreement(tmp_path):
    app = _app(tmp_path)
    ids = _seed(app)
    with app.app_context():
        uid = _individual(ids)
    c = app.test_client()
    _login(c)
    page = c.get("/admin/individuals")
    assert page.status_code == 200 and b"Ivy Individual" in page.data and b"Add subscription" in page.data
    assert c.get(f"/admin/individuals/{uid}/subscriptions/new").status_code == 200
    r = c.post(f"/admin/individuals/{uid}/subscriptions/new",
               data={"plan_id": ids["plan"], "quantity": 1, "start_date": "2026-01-01", "deposit_months": 1})
    assert r.status_code == 302 and r.headers["Location"].endswith("/admin/individuals")
    with app.app_context():
        sub = Subscription.query.one()
        assert (sub.user_id, sub.company_id, sub.deposit_amount) == (uid, None, Decimal("22000.00"))
        dep = Invoice.query.one()
        assert (dep.user_id, dep.company_id, dep.total_amount) == (uid, None, Decimal("22000.00"))
        sub_id = sub.id
        made = bs.run_monthly_billing(today=date(2026, 1, 1))
        assert len(made) == 1 and made[0].user_id == uid
        assert made[0].igst_amount == 0 and made[0].cgst_amount == Decimal("1980.00")   # local sale
    agreement = c.get(f"/admin/subscriptions/{sub_id}/agreement")
    assert agreement.status_code == 200 and b"Ivy Individual" in agreement.data
    assert c.post(f"/admin/subscriptions/{sub_id}/contract").status_code == 302
    assert b"Ivy Individual" in c.get("/admin/individuals").data


def test_individual_subscription_can_be_cancelled_and_others_are_not_listed(tmp_path):
    app = _app(tmp_path)
    ids = _seed(app)
    with app.app_context():
        uid = _individual(ids)
        sub = _sub(ids)                                                    # a company subscription
        company_sub_id = sub.id
    c = app.test_client()
    _login(c)
    c.post(f"/admin/individuals/{uid}/subscriptions/new",
           data={"plan_id": ids["plan"], "quantity": 1, "start_date": "2026-01-01"})
    with app.app_context():
        sub_id = Subscription.query.filter_by(user_id=uid).one().id
    assert c.post(f"/admin/individuals/{uid}/subscriptions/{company_sub_id}/cancel").status_code == 404
    assert c.post(f"/admin/individuals/{uid}/subscriptions/{sub_id}/cancel").status_code == 302
    with app.app_context():
        assert db.session.get(Subscription, sub_id).status == SubscriptionStatus.CANCELLED
    company_admin = User(operator_id=ids["op"], email="ca@local.example", full_name="CA", is_active=True,
                         role=UserRole.COMPANY_ADMIN, company_id=ids["local"])
    company_admin.set_password("CaPass123!")
    with app.app_context():
        db.session.add(company_admin)
        db.session.commit()
    other = app.test_client()
    other.post("/auth/login", data={"email": "ca@local.example", "password": "CaPass123!"})
    assert other.get("/admin/individuals").status_code == 403


# ------------------------------------------------------------ seed data --

def _seeded(tmp_path, *args):
    from app.cli import seed_personas_cmd
    app = create_app({"SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:", "WTF_CSRF_ENABLED": False,
                      "MAIL_SUPPRESS_SEND": True, "STORAGE_BACKEND": "local", "LOCAL_STORAGE_DIR": str(tmp_path),
                      "PLATFORM_BASE_DOMAIN": "localhost", "RATELIMIT_ENABLED": False})
    with app.app_context():
        db.create_all()
    result = app.test_cli_runner().invoke(seed_personas_cmd, list(args))
    assert result.exit_code == 0, result.output
    return app, result.output


def _login_as(app, email, password):
    client = app.test_client()
    client.post("/auth/login", data={"email": email, "password": password}, headers={"Host": "demo.localhost"})
    return client


def test_sample_data_shows_every_billing_scenario(tmp_path):
    app, out = _seeded(tmp_path, "--password", "Sample-Pass-9x!")
    assert "Sample-Pass-9x!" in out and "DemoPass123!" not in out
    with app.app_context():
        from app.models import Company, InvoiceLineItem
        subs = Subscription.query.all()
        assert len(subs) == 3
        acme = Company.query.filter_by(name="Acme Co").one()
        acme_sub = next(s for s in subs if s.company_id == acme.id)
        assert bs.deposit_balance(acme_sub) == Decimal("225000.00")          # 3 months x 5 seats x 15,000
        assert bs.deposit_balance(next(s for s in subs if s.user_id)) == 0   # Ivy's deposit invoice is unpaid
        assert InvoiceLineItem.query.filter_by(line_type="late_fee").count() == 1
        far = Invoice.query.filter(Invoice.buyer_state == "27", Invoice.tax_amount > 0).first()
        assert far.igst_amount == far.tax_amount and far.cgst_amount == 0
        local = Invoice.query.filter(Invoice.buyer_state == "29", Invoice.tax_amount > 0).first()
        assert local.igst_amount == 0 and local.cgst_amount == local.sgst_amount > 0
        sub_ids = [s.id for s in subs]
        far_id = far.id

    owner = _login_as(app, "owner@demospace.com", "Sample-Pass-9x!")
    host = {"Host": "demo.localhost"}
    for path in ("/admin/individuals", "/admin/billing/settings", "/admin/invoices", "/admin/companies"):
        assert owner.get(path, headers=host).status_code == 200, path
    for sid in sub_ids:
        assert owner.get(f"/admin/subscriptions/{sid}/agreement", headers=host).status_code == 200
    assert owner.get(f"/admin/invoices/{far_id}", headers=host).status_code == 200
    assert owner.get(f"/admin/invoices/{far_id}/pdf", headers=host).data.startswith(b"%PDF")

    company = _login_as(app, "admin@acmeco.com", "Sample-Pass-9x!")
    assert company.get("/company/invoices", headers=host).status_code == 200
    assert company.get("/company/", headers=host).status_code == 200
    member = _login_as(app, "individual@demospace.com", "Sample-Pass-9x!")
    assert member.get("/me/", headers=host).status_code == 200


def test_seeding_twice_does_not_duplicate_the_sample_data(tmp_path):
    from app.cli import seed_personas_cmd
    app, _ = _seeded(tmp_path)
    result = app.test_cli_runner().invoke(seed_personas_cmd)
    assert result.exit_code == 0, result.output
    with app.app_context():
        assert Subscription.query.count() == 3


