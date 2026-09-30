"""Company requests remain pending until the workspace operator approves them."""
import os
from datetime import date
from decimal import Decimal

os.environ.setdefault("FLASK_ENV", "testing")

from app import create_app
from app.extensions import db
from app.models import (
    BillingCycle, Company, CompanyStatus, Floor, Invoice, InvoiceStatus, Location,
    Payment, PaymentSubmission, PaymentSubmissionStatus, PlanScope, PlanType, PricingPlan,
    Seat, SeatAllocation, SeatType,
    Subscription, SubscriptionChangeRequest, SubscriptionRequestStatus,
    SubscriptionStatus, Operator, OperatorStatus, User, UserRole,
)


def _app():
    app = create_app({
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "WTF_CSRF_ENABLED": False,
        "MAIL_SUPPRESS_SEND": True,
        "STORAGE_BACKEND": "local",
        "LOCAL_STORAGE_DIR": "./var/test-uploads",
    })
    with app.app_context():
        db.create_all()
    return app


def _seed(app):
    with app.app_context():
        operator = Operator(slug="workspace", name="Workspace", primary_domain="workspace.hub1z.com",
                        status=OperatorStatus.ACTIVE, payment_upi_id="workspace@upi")
        db.session.add(operator)
        db.session.flush()
        op_admin = User(operator_id=operator.id, email="operator@example.com", full_name="Operator",
                        role=UserRole.SUPER_ADMIN, is_active=True)
        op_admin.set_password("OperatorPass123!")
        company = Company(operator_id=operator.id, name="Acme", billing_email="billing@acme.example",
                          status=CompanyStatus.ACTIVE, max_employees=10)
        db.session.add_all([op_admin, company])
        db.session.flush()
        company_admin = User(operator_id=operator.id, email="admin@acme.example", full_name="Company Admin",
                             role=UserRole.COMPANY_ADMIN, company_id=company.id, is_active=True)
        company_admin.set_password("CompanyPass123!")
        employee = User(operator_id=operator.id, email="employee@acme.example", full_name="Employee",
                role=UserRole.EMPLOYEE, company_id=company.id, is_active=True)
        employee.set_password("EmployeePass123!")
        basic = PricingPlan(operator_id=operator.id, name="Basic", scope=PlanScope.COMPANY_STANDARD,
                            plan_type=PlanType.HOT_DESK,
                            billing_cycle=BillingCycle.MONTHLY, base_price=Decimal("1000"),
                            included_meeting_credits=2)
        growth = PricingPlan(operator_id=operator.id, name="Growth", scope=PlanScope.COMPANY_STANDARD,
                             plan_type=PlanType.DEDICATED_DESK,
                             billing_cycle=BillingCycle.MONTHLY, base_price=Decimal("2000"),
                             included_meeting_credits=5)
        db.session.add_all([company_admin, employee, basic, growth])
        db.session.flush()
        location = Location(operator_id=operator.id, name="HQ", code="HQ", address_line1="1 Main Street",
                    city="Chennai", country="IN", timezone="Asia/Kolkata")
        db.session.add(location)
        db.session.flush()
        floor = Floor(operator_id=operator.id, location_id=location.id, level=1, name="First floor")
        db.session.add(floor)
        db.session.flush()
        seat = Seat(operator_id=operator.id, location_id=location.id, floor_id=floor.id,
                code="HQ-DD-01", seat_type=SeatType.DEDICATED_DESK)
        db.session.add(seat)
        subscription = Subscription(operator_id=operator.id, company_id=company.id, plan_id=basic.id,
                                    quantity=2, unit_price=basic.base_price, start_date=date.today(),
                                    status=SubscriptionStatus.ACTIVE)
        invoice = Invoice(operator_id=operator.id, number="INV-TEST-1", company_id=company.id,
                          period_start=date.today(), period_end=date.today(), due_date=date.today(),
                          subtotal=Decimal("1000"), total_amount=Decimal("1000"),
                          amount_paid=Decimal("0"), status=InvoiceStatus.ISSUED)
        db.session.add_all([subscription, invoice])
        db.session.commit()
        return company.id, growth.id, invoice.id


def _login(client, email, password):
    return client.post("/auth/login", data={"email": email, "password": password})


def test_operator_approves_company_subscription_request():
    app = _app()
    company_id, growth_id, _ = _seed(app)

    company_client = app.test_client()
    _login(company_client, "admin@acme.example", "CompanyPass123!")
    response = company_client.post("/company/plans", data={
        "plan_id": growth_id, "quantity": 4, "company_message": "Need room for new hires.",
    }, follow_redirects=False)
    assert response.status_code == 302

    with app.app_context():
        change = SubscriptionChangeRequest.query.filter_by(company_id=company_id).one()
        assert change.status == SubscriptionRequestStatus.PENDING
        change_id = change.id

    operator_client = app.test_client()
    _login(operator_client, "operator@example.com", "OperatorPass123!")
    response = operator_client.post(
        f"/admin/companies/{company_id}/subscription-requests/{change_id}/approve",
        data={"operator_message": "Approved for next billing cycle."}, follow_redirects=False,
    )
    assert response.status_code == 302

    with app.app_context():
        change = db.session.get(SubscriptionChangeRequest, change_id)
        subscription = Subscription.query.filter_by(company_id=company_id).one()
        assert change.status == SubscriptionRequestStatus.APPROVED
        assert change.operator_message == "Approved for next billing cycle."
        assert subscription.plan_id == growth_id
        assert subscription.quantity == 4


def test_operator_denies_company_subscription_request_with_message():
    app = _app()
    company_id, growth_id, _ = _seed(app)

    company_client = app.test_client()
    _login(company_client, "admin@acme.example", "CompanyPass123!")
    company_client.post("/company/plans", data={
        "plan_id": growth_id, "quantity": 9, "company_message": "Need more capacity.",
    })
    with app.app_context():
        change_id = SubscriptionChangeRequest.query.filter_by(company_id=company_id).one().id

    operator_client = app.test_client()
    _login(operator_client, "operator@example.com", "OperatorPass123!")
    response = operator_client.post(
        f"/admin/companies/{company_id}/subscription-requests/{change_id}/deny",
        data={"operator_message": "Capacity is unavailable this month."}, follow_redirects=False,
    )
    assert response.status_code == 302

    with app.app_context():
        change = db.session.get(SubscriptionChangeRequest, change_id)
        assert change.status == SubscriptionRequestStatus.DENIED
        assert change.operator_message == "Capacity is unavailable this month."


def test_operator_accepts_company_payment_report():
    app = _app()
    _, _, invoice_id = _seed(app)

    company_client = app.test_client()
    _login(company_client, "admin@acme.example", "CompanyPass123!")
    response = company_client.post(f"/company/invoices/{invoice_id}/payments", data={
        "amount": "1000.00", "paid_on": date.today().isoformat(),
        "reference": "UTR-123", "notes": "Paid via UPI.",
    }, follow_redirects=False)
    assert response.status_code == 302

    with app.app_context():
        submission = PaymentSubmission.query.filter_by(invoice_id=invoice_id).one()
        assert submission.status == PaymentSubmissionStatus.PENDING
        submission_id = submission.id

    operator_client = app.test_client()
    _login(operator_client, "operator@example.com", "OperatorPass123!")
    response = operator_client.post(
        f"/admin/payment-submissions/{submission_id}/accept",
        data={"operator_message": "Payment matched."}, follow_redirects=False,
    )
    assert response.status_code == 302

    with app.app_context():
        invoice = db.session.get(Invoice, invoice_id)
        submission = db.session.get(PaymentSubmission, submission_id)
        assert submission.status == PaymentSubmissionStatus.ACCEPTED
        assert invoice.status == InvoiceStatus.PAID
        assert invoice.amount_paid == Decimal("1000.00")
        assert Payment.query.filter_by(invoice_id=invoice_id, reference="UTR-123").count() == 1


def test_company_admin_allocates_available_seat_to_employee():
    app = _app()
    company_id, _, _ = _seed(app)
    with app.app_context():
        seat_id = Seat.query.filter_by(code="HQ-DD-01").one().id
        employee_id = User.query.filter_by(email="employee@acme.example").one().id

    company_client = app.test_client()
    _login(company_client, "admin@acme.example", "CompanyPass123!")
    page = company_client.get("/company/employees/new")
    assert page.status_code == 200
    assert b"Assigned seat (optional)" in page.data

    response = company_client.post("/company/allocations/new", data={
        "seat_id": seat_id, "employee_id": employee_id,
    }, follow_redirects=False)
    assert response.status_code == 302

    with app.app_context():
        allocation = SeatAllocation.query.filter_by(company_id=company_id, seat_id=seat_id).one()
        assert allocation.user_id == employee_id