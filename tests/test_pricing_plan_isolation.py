"""Regression tests found during a full-flow code review:

1. A Company, Custom plan negotiated for one company must never be visible
   or subscribable by another company in the same workspace.
2. A Company, Custom plan must never appear on the operator's public,
   unauthenticated marketing site.
3. An Enterprise platform tier with no monthly price and no negotiated base
   price must not crash the platform billing page.
"""
import os
from datetime import date
from decimal import Decimal

os.environ.setdefault("FLASK_ENV", "testing")

from app import create_app
from app.extensions import db
from app.models import (
    BillingCycle, BillingUnit, Company, CompanyStatus, LocationScope,
    OperatorSubscription, PlanScope, PlanStatus, PlanType, PricingPlan,
    PricingTier, SubscriptionChangeRequest, Operator, OperatorStatus, TierStatus,
    User, UserRole,
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


def _login(client, email, password, host):
    return client.post("/auth/login", data={"email": email, "password": password},
                       headers={"Host": host})


def test_company_cannot_see_or_request_other_companys_custom_plan():
    app = _app()
    host = "isoco.hub1z.com"
    with app.app_context():
        operator = Operator(slug="isoco", name="Iso Co Workspace", primary_domain=host,
                        status=OperatorStatus.ACTIVE)
        db.session.add(operator); db.session.flush()
        company_a = Company(operator_id=operator.id, name="Company A", billing_email="a@example.com",
                            status=CompanyStatus.ACTIVE)
        company_b = Company(operator_id=operator.id, name="Company B", billing_email="b@example.com",
                            status=CompanyStatus.ACTIVE)
        db.session.add_all([company_a, company_b]); db.session.flush()
        admin_a = User(operator_id=operator.id, email="admin-a@example.com", full_name="Admin A",
                      role=UserRole.COMPANY_ADMIN, company_id=company_a.id, is_active=True)
        admin_a.set_password("AdminAPass123!")
        db.session.add(admin_a)
        standard_plan = PricingPlan(
            operator_id=operator.id, name="Standard Company Plan", scope=PlanScope.COMPANY_STANDARD,
            plan_type=PlanType.DEDICATED_DESK, billing_unit=BillingUnit.PER_SEAT,
            billing_cycle=BillingCycle.MONTHLY, base_price=Decimal("1000"),
            location_scope=LocationScope.ALL, status=PlanStatus.ACTIVE, is_active=True,
        )
        custom_plan_b = PricingPlan(
            operator_id=operator.id, name="Northwind Custom Deal", scope=PlanScope.COMPANY_CUSTOM,
            company_id=company_b.id, plan_type=PlanType.DEDICATED_DESK,
            billing_unit=BillingUnit.PER_SEAT, billing_cycle=BillingCycle.MONTHLY,
            base_price=Decimal("5000"), location_scope=LocationScope.ALL,
            status=PlanStatus.ACTIVE, is_active=True,
        )
        db.session.add_all([standard_plan, custom_plan_b])
        db.session.commit()
        custom_plan_b_id = custom_plan_b.id
        company_a_id = company_a.id

    client = app.test_client()
    _login(client, "admin-a@example.com", "AdminAPass123!", host)

    page = client.get("/company/plans", headers={"Host": host})
    assert page.status_code == 200
    assert b"Standard Company Plan" in page.data
    assert b"Northwind Custom Deal" not in page.data

    response = client.post("/company/plans", data={
        "plan_id": custom_plan_b_id, "quantity": 5,
    }, headers={"Host": host}, follow_redirects=False)
    assert response.status_code == 200  # rejected by form validation, not accepted (302)

    with app.app_context():
        leaked = SubscriptionChangeRequest.query.filter_by(
            company_id=company_a_id, requested_plan_id=custom_plan_b_id,
        ).first()
        assert leaked is None


def test_public_membership_page_excludes_company_custom_plan():
    app = _app()
    host = "publicco.hub1z.com"
    with app.app_context():
        operator = Operator(slug="publicco", name="Public Co Workspace", primary_domain=host,
                        status=OperatorStatus.ACTIVE)
        db.session.add(operator); db.session.flush()
        company = Company(operator_id=operator.id, name="Only Company", billing_email="c@example.com",
                          status=CompanyStatus.ACTIVE)
        db.session.add(company); db.session.flush()
        db.session.add(PricingPlan(
            operator_id=operator.id, name="Public Standard Plan", scope=PlanScope.COMPANY_STANDARD,
            plan_type=PlanType.HOT_DESK, billing_unit=BillingUnit.PER_SEAT,
            billing_cycle=BillingCycle.MONTHLY, base_price=Decimal("500"),
            location_scope=LocationScope.ALL, status=PlanStatus.ACTIVE, is_active=True,
        ))
        db.session.add(PricingPlan(
            operator_id=operator.id, name="Private Negotiated Deal", scope=PlanScope.COMPANY_CUSTOM,
            company_id=company.id, plan_type=PlanType.DEDICATED_DESK,
            billing_unit=BillingUnit.PER_SEAT, billing_cycle=BillingCycle.MONTHLY,
            base_price=Decimal("9999"), location_scope=LocationScope.ALL,
            status=PlanStatus.ACTIVE, is_active=True,
        ))
        db.session.commit()

    client = app.test_client()
    response = client.get("/membership", headers={"Host": host})
    assert response.status_code == 200
    assert b"Public Standard Plan" in response.data
    assert b"Private Negotiated Deal" not in response.data


def test_enterprise_tier_without_negotiated_price_does_not_crash_billing():
    app = _app()
    with app.app_context():
        operator = Operator(slug="entco", name="Enterprise Co", primary_domain="entco.hub1z.com",
                        status=OperatorStatus.ACTIVE, plan_tier="enterprise")
        owner = User(email="owner2@hub1z.com", full_name="Owner", role=UserRole.PLATFORM_OWNER, is_active=True)
        owner.set_password("OwnerPass123!")
        enterprise = PricingTier(key="enterprise", name="Enterprise", monthly_price=None,
                                 annual_price=None, status=TierStatus.ACTIVE, is_active=True,
                                 max_locations=None, included_active_contracted_seats=None)
        db.session.add_all([operator, owner, enterprise])
        db.session.commit()
        operator_id = operator.id
        enterprise_id = enterprise.id

    client = app.test_client()
    _login(client, "owner2@hub1z.com", "OwnerPass123!", "hub1z.com")

    save = client.post(f"/platform/billing/{operator_id}/subscription", data={
        "tier_id": enterprise_id, "billing_cycle": "monthly",
        "additional_free_seats": "0", "additional_free_locations": "0",
        "discount_amount": "0", "premium_modules_amount": "0",
        "implementation_charge": "0", "tax_rate": "0",
    }, headers={"Host": "hub1z.com"}, follow_redirects=False)
    assert save.status_code == 302

    with app.app_context():
        subscription = OperatorSubscription.query.filter_by(operator_id=operator_id).one()
        assert subscription.pricing_snapshot is not None
        assert '"monthly_price": null' in subscription.pricing_snapshot

    billing_page = client.get("/platform/billing", headers={"Host": "hub1z.com"})
    assert billing_page.status_code == 200
