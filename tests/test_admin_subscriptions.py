"""Companies request subscription changes; workspace operators approve them."""
import os
os.environ.setdefault("FLASK_ENV", "testing")

from app import create_app
from app.extensions import db
from app.models import (
    User, UserRole, Operator, OperatorStatus, Company, CompanyStatus,
    PricingPlan, PlanScope, PlanType, BillingCycle, Subscription, SubscriptionChangeRequest,
    SubscriptionRequestStatus, SubscriptionStatus,
)


def _app():
    app = create_app({"SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
                      "WTF_CSRF_ENABLED": False,
                      "MAIL_SUPPRESS_SEND": True,
                      "STORAGE_BACKEND": "local",
                      "LOCAL_STORAGE_DIR": "./var/test-uploads"})
    with app.app_context():
        db.create_all()
    return app


def _seed(app):
    with app.app_context():
        t = Operator(slug="adyarspace", name="Adyar Space", primary_domain="adyarspace.hub1z.com",
                  status=OperatorStatus.ACTIVE)
        db.session.add(t); db.session.flush()
        admin = User(operator_id=t.id, email="admin@adyarspace.com", full_name="Admin",
                    role=UserRole.SUPER_ADMIN, is_active=True)
        admin.set_password("AdminPass123!")
        db.session.add(admin)
        company = Company(operator_id=t.id, name="Acme", billing_email="b@acme.example",
                          status=CompanyStatus.ACTIVE, max_employees=10)
        db.session.add(company); db.session.flush()
        ca = User(operator_id=t.id, email="jane@acme.example", full_name="Jane",
                 role=UserRole.COMPANY_ADMIN, company_id=company.id, is_active=True)
        ca.set_password("JanePass123!")
        db.session.add(ca)
        plan = PricingPlan(operator_id=t.id, name="Dedicated Desk", scope=PlanScope.COMPANY_STANDARD,
                           plan_type=PlanType.DEDICATED_DESK,
                           billing_cycle=BillingCycle.MONTHLY, base_price=22000,
                           included_meeting_credits=20, max_locations=1)
        db.session.add(plan); db.session.commit()
        return company.id, plan.id


def _login(client, email, password):
    return client.post("/auth/login", data={"email": email, "password": password})


def test_company_admin_can_request_but_not_self_subscribe():
    app = _app()
    company_id, plan_id = _seed(app)
    c = app.test_client()
    _login(c, "jane@acme.example", "JanePass123!")

    r = c.get("/company/plans")
    assert r.status_code == 200
    assert b"Request change" in r.data

    r = c.post("/company/plans", data={"plan_id": plan_id, "quantity": 5,
                                        "company_message": "Please review."}, follow_redirects=False)
    assert r.status_code == 302
    with app.app_context():
        assert Subscription.query.filter_by(company_id=company_id).first() is None
        request = SubscriptionChangeRequest.query.filter_by(company_id=company_id).one()
        assert request.status == SubscriptionRequestStatus.PENDING


def test_operator_admin_can_create_subscription_for_company():
    app = _app()
    company_id, plan_id = _seed(app)
    c = app.test_client()
    _login(c, "admin@adyarspace.com", "AdminPass123!")

    r = c.post(f"/admin/companies/{company_id}/subscriptions/new", data={
        "plan_id": plan_id, "quantity": 5, "start_date": "2026-01-01",
    }, follow_redirects=False)
    assert r.status_code == 302

    with app.app_context():
        sub = Subscription.query.filter_by(company_id=company_id).first()
        assert sub is not None
        assert sub.quantity == 5
        assert sub.status == SubscriptionStatus.ACTIVE
        assert sub.meeting_credits_balance == 100  # 20 credits * 5 seats


def test_company_admin_cannot_create_subscription_via_admin_route():
    app = _app()
    company_id, plan_id = _seed(app)
    c = app.test_client()
    _login(c, "jane@acme.example", "JanePass123!")
    r = c.get(f"/admin/companies/{company_id}/subscriptions/new")
    assert r.status_code == 403


def test_operator_admin_can_cancel_subscription():
    app = _app()
    company_id, plan_id = _seed(app)
    c = app.test_client()
    _login(c, "admin@adyarspace.com", "AdminPass123!")
    c.post(f"/admin/companies/{company_id}/subscriptions/new", data={
        "plan_id": plan_id, "quantity": 2, "start_date": "2026-01-01",
    })
    with app.app_context():
        sub_id = Subscription.query.filter_by(company_id=company_id).first().id

    r = c.post(f"/admin/companies/{company_id}/subscriptions/{sub_id}/cancel", follow_redirects=False)
    assert r.status_code == 302
    with app.app_context():
        sub = db.session.get(Subscription, sub_id)
        assert sub.status == SubscriptionStatus.CANCELLED
        assert sub.end_date is not None


def test_company_detail_page_shows_subscriptions():
    app = _app()
    company_id, plan_id = _seed(app)
    c = app.test_client()
    _login(c, "admin@adyarspace.com", "AdminPass123!")
    c.post(f"/admin/companies/{company_id}/subscriptions/new", data={
        "plan_id": plan_id, "quantity": 3, "start_date": "2026-01-01",
    })
    r = c.get(f"/admin/companies/{company_id}")
    assert r.status_code == 200
    assert b"Dedicated Desk" in r.data
