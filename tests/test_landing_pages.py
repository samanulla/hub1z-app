"""The platform apex (no operator resolved) and an operator's own domain must show
different homepages: the apex pitches hub1z itself to prospective coworking
operators (with live pricing tiers); an operator's own domain shows its
hospitality-branded page for its own members/companies. Previously both used
the same template, so an operator's page pitched visitors to become a competing
operator, and the apex page's "become an operator" CTA linked to a
workspace-lookup form instead of the free-trial signup."""
import os
os.environ.setdefault("FLASK_ENV", "testing")

from app import create_app
from app.extensions import db
from app.models import (
    Operator, OperatorStatus, PricingTier, PlatformProfile, TierStatus, PricingPlan, PlanType, BillingCycle, Location,
)


def _app(pricing_public=True):
    app = create_app({"SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
                      "WTF_CSRF_ENABLED": False,
                      "MAIL_SUPPRESS_SEND": True,
                      "STORAGE_BACKEND": "local",
                      "LOCAL_STORAGE_DIR": "./var/test-uploads"})
    with app.app_context():
        db.create_all()
        db.session.add(PricingTier(key="starter", name="Starter", monthly_price=4999, is_active=True,
                                   status=TierStatus.ACTIVE, is_public=True, max_locations=1,
                                   max_staff_users=3, max_open_leads=100, storage_mb=500,
                                   description="Get running quickly.", sort_order=10))
        db.session.add(PricingTier(key="enterprise", name="Enterprise", monthly_price=None, is_active=True,
                                   status=TierStatus.ACTIVE, is_public=True, contact_sales=True,
                                   all_features=True, sort_order=30))
        db.session.add(PricingTier(key="draft", name="Secret Draft", monthly_price=1, is_active=False,
                                   status=TierStatus.DRAFT, is_public=True, sort_order=40))
        db.session.add(PricingTier(key="internal", name="Internal Plan", monthly_price=2, is_active=True,
                                   status=TierStatus.ACTIVE, is_public=False, sort_order=50))
        profile = PlatformProfile()
        profile.pricing_page_public = pricing_public
        db.session.add(profile)
        db.session.commit()
    return app


def test_apex_shows_platform_pitch_with_live_pricing_tiers():
    app = _app()
    c = app.test_client()
    r = c.get("/", headers={"Host": "localhost"})
    assert r.status_code == 200
    assert b"Run your coworking" in r.data
    assert b"Starter" in r.data and b"Enterprise" in r.data
    assert b"4,999" in r.data  # Indian-grouped currency via the money filter
    assert b"Custom" in r.data  # Enterprise has no monthly_price
    assert b"Secret Draft" not in r.data and b"Internal Plan" not in r.data
    assert b"14-day free trial" in r.data  # trial length comes from settings, not a blank


def test_pricing_page_lists_limits_and_hides_unpublished_tiers():
    app = _app()
    r = app.test_client().get("/pricing", headers={"Host": "localhost"})
    page = r.data.decode()
    assert r.status_code == 200
    assert "Up to 100 open leads" in page and "500 MB document storage" in page
    assert "Contact sales" in page and "Every feature included" in page
    assert "Secret Draft" not in page and "Internal Plan" not in page


def test_pricing_is_hidden_until_platform_admin_switches_it_on():
    app = _app(pricing_public=False)
    c = app.test_client()
    for path in ("/", "/pricing"):
        page = c.get(path, headers={"Host": "localhost"}).data.decode()
        assert "Pricing is being prepared" in page
        assert "4,999" not in page


def test_trial_length_follows_platform_settings():
    app = _app()
    with app.app_context():
        PlatformProfile.get().trial_days = 21
        db.session.commit()
    page = app.test_client().get("/", headers={"Host": "localhost"}).data.decode()
    assert "21-day free trial" in page


def test_apex_start_trial_cta_points_to_register_operator_not_pick_workspace():
    app = _app()
    c = app.test_client()
    r = c.get("/", headers={"Host": "localhost"})
    assert b'href="/auth/register/operator"' in r.data
    # the old broken CTA must not be the primary call to action on the hero/CTA bands
    assert r.data.count(b"Start free trial") >= 2


def test_operator_domain_shows_its_own_page_not_the_apex_pitch():
    app = _app()
    with app.app_context():
        db.session.add(Operator(slug="adyarspace", name="Adyar Space",
                              primary_domain="adyarspace.hub1z.com", status=OperatorStatus.ACTIVE))
        db.session.commit()

    c = app.test_client()
    r = c.get("/", headers={"Host": "adyarspace.hub1z.com"})
    assert r.status_code == 200
    assert b"Adyar Space" in r.data
    assert b"Run your coworking" not in r.data
    assert b"Operator" not in r.data  # the recruit-an-operator card must not leak here


def test_unmatched_real_domain_resolves_to_no_operator_even_when_one_exists():
    """The production-correctness bug this session's testing exposed: any
    unmatched Host used to fall back to the first operator, so visiting the
    platform's own real apex domain (hub1z.com) would incorrectly show a
    operator's page if one existed. Only bare localhost/127.0.0.1 should get
    that dev-convenience fallback."""
    app = _app()
    with app.app_context():
        db.session.add(Operator(slug="adyarspace", name="Adyar Space",
                              primary_domain="adyarspace.hub1z.com", status=OperatorStatus.ACTIVE))
        db.session.commit()

    c = app.test_client()
    r = c.get("/", headers={"Host": "hub1z.com"})  # the platform's real apex, unmatched by design
    assert b"Run your coworking" in r.data
    assert b"Adyar Space" not in r.data

    # bare localhost still gets the dev-convenience fallback to the first operator
    r2 = c.get("/", headers={"Host": "localhost"})
    assert b"Adyar Space" in r2.data


def test_operator_domain_who_its_for_has_two_doors_not_three():
    """The old 'Operator' recruiting card must not appear on an operator's own site."""
    app = _app()
    with app.app_context():
        db.session.add(Operator(slug="adyarspace", name="Adyar Space",
                              primary_domain="adyarspace.hub1z.com", status=OperatorStatus.ACTIVE))
        db.session.commit()
    c = app.test_client()
    r = c.get("/", headers={"Host": "adyarspace.hub1z.com"})
    assert b"Two doors" in r.data
    assert b"Three doors" not in r.data


def test_platform_feature_and_pricing_pages_are_public():
    app = _app()
    c = app.test_client()
    assert c.get("/features", headers={"Host": "hub1z.com"}).status_code == 200
    pricing = c.get("/pricing", headers={"Host": "hub1z.com"})
    assert pricing.status_code == 200
    assert b"Starter" in pricing.data


def test_operator_microsite_exposes_spaces_membership_and_availability():
    app = _app()
    with app.app_context():
        operator = Operator(slug="adyarspace", name="Adyar Space",
                        primary_domain="adyarspace.hub1z.com", status=OperatorStatus.ACTIVE)
        db.session.add(operator)
        db.session.flush()
        db.session.add(Location(
            operator_id=operator.id, name="Main Office", code="MAIN",
            address_line1="1 Main Street", city="Bengaluru", country="IN",
        ))
        db.session.add(PricingPlan(
            operator_id=operator.id, name="Hot Desk", plan_type=PlanType.HOT_DESK,
            billing_cycle=BillingCycle.MONTHLY, base_price=12000,
        ))
        db.session.commit()

    c = app.test_client()
    headers = {"Host": "adyarspace.hub1z.com"}
    assert b"Main Office" in c.get("/spaces", headers=headers).data
    assert b"Hot Desk" in c.get("/membership", headers=headers).data
    assert c.get("/availability", headers=headers).status_code == 200


def test_operator_signup_applies_country_defaults():
    app = _app()
    c = app.test_client()
    response = c.post("/auth/register/operator", data={
        "business_name": "Chennai Works",
        "slug": "chennai-works",
        "country_code": "IN",
        "admin_full_name": "Alex Operator",
        "admin_email": "alex@chennai.example",
        "password": "Password123!",
        "confirm": "Password123!",
    }, headers={"Host": "hub1z.com"}, follow_redirects=False)
    assert response.status_code == 302
    with app.app_context():
        operator = Operator.query.filter_by(slug="chennai-works").one()
        assert operator.country_code == "IN"
        assert (operator.currency_code, operator.currency_symbol) == ("INR", "₹")
        assert operator.timezone == "Asia/Kolkata"


def test_operator_signup_is_india_only_for_now():
    app = _app()
    response = app.test_client().post("/auth/register/operator", data={
        "business_name": "London Works", "slug": "london-works", "country_code": "GB",
        "admin_full_name": "Alex Operator", "admin_email": "alex@london.example",
        "password": "Password123!", "confirm": "Password123!",
    }, headers={"Host": "hub1z.com"}, follow_redirects=False)
    assert response.status_code == 200
    with app.app_context():
        assert Operator.query.filter_by(slug="london-works").first() is None
