"""Hub1 SaaS pricing is based on contracted seats, not physical inventory."""
import os
from datetime import date
from decimal import Decimal

os.environ.setdefault("FLASK_ENV", "testing")

from app import create_app
from app.extensions import db
from app.models import (
    BillingCycle, Company, CompanyStatus, PlanType, PricingPlan, PricingTier,
    Subscription, SubscriptionStatus, Operator, OperatorStatus, TierStatus, User, UserRole,
)
from app.services.platform_pricing import subscription_pricing


def _app():
    app = create_app({"SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:", "WTF_CSRF_ENABLED": False,
                      "MAIL_SUPPRESS_SEND": True, "STORAGE_BACKEND": "local",
                      "LOCAL_STORAGE_DIR": "./var/test-uploads"})
    with app.app_context():
        db.create_all()
    return app


def test_starter_contract_overage_recommends_growth():
    app = _app()
    with app.app_context():
        operator = Operator(slug="operator", name="Operator", primary_domain="operator.hub1z.com",
                        status=OperatorStatus.ACTIVE, plan_tier="starter")
        owner = User(email="owner@hub1z.com", full_name="Owner", role=UserRole.PLATFORM_OWNER, is_active=True)
        owner.set_password("OwnerPass123!")
        starter = PricingTier(key="starter", name="Starter", monthly_price=Decimal("100"),
                              max_locations=1, included_active_contracted_seats=50,
                              additional_seat_rate=Decimal("5"), status=TierStatus.ACTIVE, is_active=True)
        growth = PricingTier(key="growth", name="Growth", monthly_price=Decimal("240"),
                             max_locations=3, included_active_contracted_seats=150,
                             status=TierStatus.ACTIVE, is_active=True)
        db.session.add_all([operator, owner, starter, growth])
        db.session.flush()
        company = Company(operator_id=operator.id, name="Northwind", billing_email="billing@example.com",
                          status=CompanyStatus.ACTIVE)
        plan = PricingPlan(operator_id=operator.id, name="Contracted", plan_type=PlanType.DEDICATED_DESK,
                           billing_cycle=BillingCycle.MONTHLY, base_price=0)
        db.session.add_all([company, plan])
        db.session.flush()
        db.session.add(Subscription(operator_id=operator.id, company_id=company.id, plan_id=plan.id,
                                    quantity=80, unit_price=0, start_date=date.today(),
                                    status=SubscriptionStatus.ACTIVE))
        db.session.commit()

        pricing = subscription_pricing(operator, starter)
        assert pricing["active_contracted_seats"] == 80
        assert pricing["additional_seats"] == 30
        assert pricing["seat_overage"] == Decimal("150")
        assert pricing["total"] == Decimal("250")

    client = app.test_client()
    client.post("/auth/login", data={"email": "owner@hub1z.com", "password": "OwnerPass123!"},
                headers={"Host": "hub1z.com"})
    response = client.get("/platform/billing", headers={"Host": "hub1z.com"})
    assert response.status_code == 200
    assert b"Consider Growth" in response.data