"""UPI payments for operators and Hub1z, parcels, virtual office letters, renewal alerts and the installable app."""
import os
from datetime import date, timedelta
from decimal import Decimal

os.environ.setdefault("FLASK_ENV", "testing")

from dateutil.relativedelta import relativedelta

from app.cli import PERSONA_PASSWORD
from app.extensions import db
from app.models import (AlertNotice, BillingCycle, Company, Invoice, InvoiceStatus, Location, Operator, Parcel,
                        PaymentSubmission, PlanScope, PlanStatus, PlanType, PlatformInvoice, PlatformInvoiceStatus,
                        PlatformPaymentReport, PlatformProfile, PricingPlan, Subscription, SubscriptionStatus, User)
from app.services import alerts, upi
from tests.test_role_paths import APEX, DEMO, OTHER, OWNER_PASSWORD, _login, _seeded_app


def _client(app, host, email, password=PERSONA_PASSWORD):
    c = app.test_client()
    assert _login(c, host, email, password).status_code == 302, email
    return c


def _get(c, host, path):
    return c.get(path, headers={"Host": host})


def _post(c, host, path, data=None, **kw):
    return c.post(path, data=data or {}, headers={"Host": host}, **kw)


def _op(app, host):
    with app.app_context():
        return Operator.query.filter_by(primary_domain=host).one().id


def _set_upi(app, host, upi_id="demospace@okicici"):
    with app.app_context():
        op = Operator.query.filter_by(primary_domain=host).one()
        op.payment_upi_id, op.payment_gpay, op.payment_bank_details = upi_id, "98400 11223", "HDFC A/c 001 IFSC HDFC0001"
        db.session.commit()


def _open_invoice(app, **owner):
    with app.app_context():
        for inv in Invoice.query.execution_options(skip_operator_filter=True).filter_by(**owner).all():
            if inv.status != InvoiceStatus.DRAFT and inv.balance_due > 0:
                return inv.id, inv.number
    raise AssertionError("no open invoice in the seed")


def _user_id(app, email):
    with app.app_context():
        return User.query.execution_options(skip_operator_filter=True).filter_by(email=email).one().id


# ------------------------------------------------------------------ UPI --

def test_upi_link_is_well_formed():
    link = upi.upi_uri("demo@okicici", "Demo Space LLP", Decimal("17700"), "Invoice INV-7")
    assert link == "upi://pay?pa=demo@okicici&pn=Demo%20Space%20LLP&am=17700.00&cu=INR&tn=Invoice%20INV-7"
    assert upi.upi_uri(None, "x", 1, "y") is None
    assert upi.vpa_of("", "98400 11223", "pay@ybl") == "pay@ybl"


def test_company_pays_by_upi_qr_and_reports_the_payment():
    app, _ = _seeded_app()
    _set_upi(app, DEMO)
    with app.app_context():
        acme = Company.query.execution_options(skip_operator_filter=True).filter_by(name="Acme Co").one().id
    invoice_id, number = _open_invoice(app, company_id=acme)
    c = _client(app, DEMO, "admin@acmeco.com")
    page = _get(c, DEMO, "/company/invoices").data.decode()
    assert f"/company/invoices/{invoice_id}/upi.png" in page and "upi://pay?pa=demospace@okicici" in page
    assert "demospace@okicici" in page and "Coming soon" in page and "Report payment" in page
    png = _get(c, DEMO, f"/company/invoices/{invoice_id}/upi.png")
    assert png.status_code == 200 and png.mimetype == "image/png" and png.data[:4] == b"\x89PNG"

    r = _post(c, DEMO, f"/company/invoices/{invoice_id}/payments",
              {"amount": "100.00", "paid_on": date.today().isoformat(), "reference": "UTR123"})
    assert r.status_code == 302
    with app.app_context():
        s = PaymentSubmission.query.execution_options(skip_operator_filter=True).filter_by(invoice_id=invoice_id).one()
        assert s.company_id == acme and s.user_id is None and s.reference == "UTR123"
    assert "Payment reported" in _get(c, DEMO, "/company/invoices").data.decode()
    owner = _client(app, DEMO, "owner@demospace.com")
    assert b"Payment to confirm" in _get(owner, DEMO, "/admin/invoices").data


def test_no_upi_id_means_no_qr_but_the_other_details_still_show():
    app, _ = _seeded_app()
    _set_upi(app, DEMO, upi_id="")
    with app.app_context():
        op = Operator.query.filter_by(primary_domain=DEMO).one()
        op.payment_gpay = "98400 11223"
        db.session.commit()
        acme = Company.query.execution_options(skip_operator_filter=True).filter_by(name="Acme Co").one().id
    invoice_id, _ = _open_invoice(app, company_id=acme)
    c = _client(app, DEMO, "admin@acmeco.com")
    page = _get(c, DEMO, "/company/invoices").data.decode()
    assert "UPI QR not set up yet" in page and "98400 11223" in page
    assert _get(c, DEMO, f"/company/invoices/{invoice_id}/upi.png").status_code == 404


def test_individual_gets_invoices_and_pays_by_upi():
    app, _ = _seeded_app()
    _set_upi(app, DEMO)
    ivy = _user_id(app, "individual@demospace.com")
    invoice_id, _ = _open_invoice(app, user_id=ivy)
    c = _client(app, DEMO, "individual@demospace.com")
    page = _get(c, DEMO, "/me/invoices").data.decode()
    assert "Invoices &amp; payments" in page and f"/me/invoices/{invoice_id}/upi.png" in page
    assert _get(c, DEMO, f"/me/invoices/{invoice_id}/upi.png").mimetype == "image/png"
    assert _get(c, DEMO, f"/me/invoices/{invoice_id}/pdf").data[:5] == b"%PDF-"
    assert _post(c, DEMO, f"/me/invoices/{invoice_id}/payments",
                 {"amount": "10", "paid_on": date.today().isoformat()}).status_code == 302
    with app.app_context():
        s = PaymentSubmission.query.execution_options(skip_operator_filter=True).filter_by(invoice_id=invoice_id).one()
        assert s.user_id == ivy and s.company_id is None
    assert b"/me/invoices" in _get(c, DEMO, "/me/").data

    employee = _client(app, DEMO, "employee@acmeco.com")
    assert _get(employee, DEMO, "/me/invoices").status_code == 403
    assert b"/me/invoices" not in _get(employee, DEMO, "/me/").data
    with app.app_context():
        acme = Company.query.execution_options(skip_operator_filter=True).filter_by(name="Acme Co").one().id
    acme_invoice, _ = _open_invoice(app, company_id=acme)
    assert _get(c, DEMO, f"/me/invoices/{acme_invoice}/pdf").status_code == 404


def test_operator_pays_hub1z_by_upi_and_platform_confirms():
    app, _ = _seeded_app()
    demo_id, other_id = _op(app, DEMO), _op(app, OTHER)
    with app.app_context():
        for op_id, number in ((demo_id, "HUB-1"), (other_id, "HUB-2")):
            db.session.add(PlatformInvoice(operator_id=op_id, number=number, period_start=date(2026, 10, 1),
                                           period_end=date(2026, 10, 31), due_date=date(2026, 11, 10),
                                           amount=Decimal("4999"), status=PlatformInvoiceStatus.ISSUED))
        db.session.commit()
        ids = {i.number: i.id for i in PlatformInvoice.query.all()}

    platform = _client(app, APEX, "admin@hub1z.com", OWNER_PASSWORD)
    assert b"Operators cannot pay you yet" in _get(platform, APEX, "/platform/finance").data
    r = _post(platform, APEX, "/platform/payment-details", {"legal_name": "Hub1z Technologies Private Limited",
                                                            "upi_id": "hub1z@icici", "bank_details": "ICICI 123"})
    assert r.status_code == 302

    owner = _client(app, DEMO, "owner@demospace.com")
    page = _get(owner, DEMO, "/admin/hub1z-billing").data.decode()
    assert "hub1z@icici" in page and "HUB-1" in page and "HUB-2" not in page
    assert _get(owner, DEMO, f"/admin/hub1z-billing/invoices/{ids['HUB-1']}/upi.png").mimetype == "image/png"
    assert _get(owner, DEMO, f"/admin/hub1z-billing/invoices/{ids['HUB-2']}/upi.png").status_code == 404
    assert _post(owner, DEMO, f"/admin/hub1z-billing/invoices/{ids['HUB-2']}/report",
                 {"amount": "4999", "paid_on": date.today().isoformat()}).status_code == 404
    assert _post(owner, DEMO, f"/admin/hub1z-billing/invoices/{ids['HUB-1']}/report",
                 {"amount": "4999", "paid_on": date.today().isoformat(), "reference": "UTR9"}).status_code == 302

    finance = _get(platform, APEX, "/platform/finance").data.decode()
    assert "UTR9" in finance and "Demo Space" in finance
    assert b'<span class="h-nav-badge">1</span>' in _get(platform, APEX, "/platform/finance").data
    with app.app_context():
        report_id = PlatformPaymentReport.query.one().id
    assert _post(platform, APEX, f"/platform/finance/payment-reports/{report_id}/reject").status_code == 302
    with app.app_context():
        assert PlatformPaymentReport.query.one().status == "pending"  # a rejection needs a reason
    _post(platform, APEX, f"/platform/finance/payment-reports/{report_id}/accept")
    with app.app_context():
        assert PlatformPaymentReport.query.one().status == "accepted"
        assert db.session.get(PlatformInvoice, ids["HUB-1"]).status == PlatformInvoiceStatus.PAID
        assert PlatformProfile.get().upi_id == "hub1z@icici"
    pdf = _get(owner, DEMO, f"/admin/hub1z-billing/invoices/{ids['HUB-1']}.pdf")
    assert pdf.data[:5] == b"%PDF-"


# -------------------------------------------------------------- parcels --

def test_parcel_is_logged_announced_shown_and_handed_over():
    app, _ = _seeded_app()
    employee_id = _user_id(app, "employee@acmeco.com")
    owner = _client(app, DEMO, "owner@demospace.com")
    r = _post(owner, DEMO, "/admin/parcels/new", {"recipient": f"user:{employee_id}", "kind": "parcel",
                                                  "carrier": "Blue Dart", "reference": "AWB777", "notify": "1"})
    assert r.status_code == 302
    with app.app_context():
        parcel = Parcel.query.execution_options(skip_operator_filter=True).one()
        assert parcel.notified_at is not None and parcel.company_id is not None and len(parcel.pickup_code) == 6
        code, parcel_id = parcel.pickup_code, parcel.id
    assert b"AWB777" in _get(owner, DEMO, "/admin/parcels").data

    employee = _client(app, DEMO, "employee@acmeco.com")
    assert code.encode() in _get(employee, DEMO, "/me/parcels").data
    assert code.encode() in _get(employee, DEMO, "/me/").data
    company_admin = _client(app, DEMO, "admin@acmeco.com")
    assert code.encode() in _get(company_admin, DEMO, "/company/parcels").data
    individual = _client(app, DEMO, "individual@demospace.com")
    assert code.encode() not in _get(individual, DEMO, "/me/parcels").data
    other = _client(app, OTHER, "owner@otherspace.com")
    assert b"AWB777" not in _get(other, OTHER, "/admin/parcels").data
    assert _post(other, OTHER, f"/admin/parcels/{parcel_id}/collect").status_code == 404

    _post(owner, DEMO, f"/admin/parcels/{parcel_id}/collect", {"code": "000000" if code != "000000" else "111111"})
    with app.app_context():
        assert db.session.get(Parcel, parcel_id).status == "waiting"
    _post(owner, DEMO, f"/admin/parcels/{parcel_id}/collect", {"code": code, "collected_by": "Front desk for Ravi"})
    with app.app_context():
        p = db.session.get(Parcel, parcel_id)
        assert p.status == "collected" and p.collected_by == "Front desk for Ravi"


def test_a_company_addressed_parcel_and_a_bad_recipient():
    app, _ = _seeded_app()
    with app.app_context():
        acme = Company.query.execution_options(skip_operator_filter=True).filter_by(name="Acme Co").one().id
        other_company = Company.query.execution_options(skip_operator_filter=True).filter(
            Company.operator_id == _op(app, OTHER)).first()
    owner = _client(app, DEMO, "owner@demospace.com")
    _post(owner, DEMO, "/admin/parcels/new", {"recipient": f"company:{acme}", "kind": "letter"})
    if other_company is not None:
        _post(owner, DEMO, "/admin/parcels/new", {"recipient": f"company:{other_company.id}", "kind": "letter"})
    _post(owner, DEMO, "/admin/parcels/new", {"recipient": "nobody", "kind": "letter"})
    with app.app_context():
        rows = Parcel.query.execution_options(skip_operator_filter=True).all()
        assert len(rows) == 1 and rows[0].company_id == acme and rows[0].user_id is None
    company_admin = _client(app, DEMO, "admin@acmeco.com")
    assert b"Letter" in _get(company_admin, DEMO, "/company/parcels").data


# ------------------------------------------------------- virtual office --

def _virtual_office(app, company_name="Acme Co"):
    with app.app_context():
        op = Operator.query.filter_by(primary_domain=DEMO).one()
        loc = Location.query.execution_options(skip_operator_filter=True).filter_by(operator_id=op.id).first()
        op.primary_location_id = loc.id
        company = Company.query.execution_options(skip_operator_filter=True).filter_by(name=company_name).one()
        plan = PricingPlan(operator_id=op.id, name="Virtual Office Basic", scope=PlanScope.COMPANY_STANDARD,
                           plan_type=PlanType.VIRTUAL_OFFICE, billing_cycle=BillingCycle.MONTHLY,
                           base_price=Decimal("1999"), status=PlanStatus.ACTIVE, is_active=True)
        db.session.add(plan)
        db.session.flush()
        sub = Subscription(operator_id=op.id, plan_id=plan.id, company_id=company.id, quantity=1,
                           unit_price=plan.base_price, start_date=date.today(), status=SubscriptionStatus.ACTIVE)
        db.session.add(sub)
        db.session.commit()
        return sub.id, loc.address_line1


def test_virtual_office_client_downloads_the_address_letter():
    app, _ = _seeded_app()
    sub_id, street = _virtual_office(app)
    company_admin = _client(app, DEMO, "admin@acmeco.com")
    dash = _get(company_admin, DEMO, "/company/").data.decode()
    assert "Virtual office" in dash and f"/company/subscriptions/{sub_id}/address-letter.pdf" in dash
    pdf = _get(company_admin, DEMO, f"/company/subscriptions/{sub_id}/address-letter.pdf")
    assert pdf.status_code == 200 and pdf.data[:5] == b"%PDF-"
    owner = _client(app, DEMO, "owner@demospace.com")
    assert _get(owner, DEMO, f"/admin/subscriptions/{sub_id}/address-letter.pdf").data[:5] == b"%PDF-"
    with app.app_context():
        desk = Subscription.query.execution_options(skip_operator_filter=True).filter(
            Subscription.id != sub_id, Subscription.company_id.isnot(None)).first().id
    assert _get(company_admin, DEMO, f"/company/subscriptions/{desk}/address-letter.pdf").status_code == 404
    other = _client(app, OTHER, "owner@otherspace.com")
    assert _get(other, OTHER, f"/admin/subscriptions/{sub_id}/address-letter.pdf").status_code == 404
    assert b"virtual_office" in _get(owner, DEMO, "/admin/plans/new").data


# --------------------------------------------------------------- alerts --

def test_alerts_list_renewals_and_overdue_and_email_each_item_once():
    app, _ = _seeded_app()
    with app.app_context():
        acme = Company.query.execution_options(skip_operator_filter=True).filter_by(name="Acme Co").one()
        sub = Subscription.query.execution_options(skip_operator_filter=True).filter_by(company_id=acme.id).first()
        sub.start_date = date.today() - relativedelta(months=sub.term_months) + timedelta(days=20)
        db.session.commit()
        who = acme.name
    owner = _client(app, DEMO, "owner@demospace.com")
    page = _get(owner, DEMO, "/admin/alerts").data.decode()
    assert f"{who}: agreement ends in 20 days" in page and "overdue" in page
    assert "Needs attention" in _get(owner, DEMO, "/admin/").data.decode()
    company_admin = _client(app, DEMO, "admin@acmeco.com")
    assert "Renewal due in 20 days" in _get(company_admin, DEMO, "/company/").data.decode()

    with app.app_context():
        first = alerts.run_alert_emails()
        sent = AlertNotice.query.execution_options(skip_operator_filter=True).count()
        assert first["digests"] >= 1 and first["customer"] >= 1 and sent >= 2
        again = alerts.run_alert_emails()
        assert again == {"digests": 0, "customer": 0}
        assert AlertNotice.query.execution_options(skip_operator_filter=True).count() == sent


# --------------------------------------------------------- phone app --

def test_each_site_installs_as_its_own_app():
    app, _ = _seeded_app()
    c = app.test_client()
    m = _get(c, DEMO, "/manifest.webmanifest")
    assert m.mimetype == "application/manifest+json"
    data = m.get_json(force=True)
    assert data["name"] == "Demo Space" and data["start_url"] == "/auth/post-login" and data["display"] == "standalone"
    assert data["icons"][0]["src"] == "/app-icon-192.png" and any(s["url"] == "/checkin/pass" for s in data["shortcuts"])
    icon = _get(c, DEMO, "/app-icon-192.png")
    assert icon.mimetype == "image/png" and icon.data[:4] == b"\x89PNG"
    assert _get(c, APEX, "/manifest.webmanifest").get_json(force=True)["name"] == "Hub1z"
    sw = _get(c, DEMO, "/sw.js")
    assert sw.mimetype == "application/javascript" and sw.headers["Service-Worker-Allowed"] == "/"
    assert b"You are offline" in _get(c, DEMO, "/offline").data
    login = _get(c, DEMO, "/auth/login").data
    assert b'rel="manifest"' in login and b"/app-icon-180.png" in login and b'type="image/svg+xml"' not in login
    employee = _client(app, DEMO, "employee@acmeco.com")
    assert b"data-install-app" in _get(employee, DEMO, "/me/").data
