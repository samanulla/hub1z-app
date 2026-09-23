"""The platform apex (no tenant resolved) and a tenant's own domain must show
different homepages: the apex pitches hub1z itself to prospective coworking
operators (with live pricing tiers); a tenant's own domain shows its
hospitality-branded page for its own members/companies. Previously both used
the same template, so a tenant's page pitched visitors to become a competing
operator, and the apex page's "become an operator" CTA linked to a
workspace-lookup form instead of the free-trial signup."""
import os
os.environ.setdefault("FLASK_ENV", "testing")

from app import create_app
from app.extensions import db
from app.models import Tenant, TenantStatus, PricingTier


def _app():
    app = create_app({"SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
                      "WTF_CSRF_ENABLED": False,
                      "MAIL_SUPPRESS_SEND": True,
                      "STORAGE_BACKEND": "local",
                      "LOCAL_STORAGE_DIR": "./var/test-uploads"})
    with app.app_context():
        db.create_all()
        db.session.add(PricingTier(key="starter", name="Starter", monthly_price=4999, is_active=True,
                                   max_locations=1, max_seats=30, max_private_offices=3, max_rooms=2))
        db.session.add(PricingTier(key="enterprise", name="Enterprise", monthly_price=None, is_active=True))
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


def test_apex_start_trial_cta_points_to_register_tenant_not_pick_workspace():
    app = _app()
    c = app.test_client()
    r = c.get("/", headers={"Host": "localhost"})
    assert b'href="/auth/register/tenant"' in r.data
    # the old broken CTA must not be the primary call to action on the hero/CTA bands
    assert r.data.count(b"Start free trial") >= 2


def test_tenant_domain_shows_its_own_page_not_the_apex_pitch():
    app = _app()
    with app.app_context():
        db.session.add(Tenant(slug="adyarspace", name="Adyar Space",
                              primary_domain="adyarspace.hub1z.com", status=TenantStatus.ACTIVE))
        db.session.commit()

    c = app.test_client()
    r = c.get("/", headers={"Host": "adyarspace.hub1z.com"})
    assert r.status_code == 200
    assert b"Adyar Space" in r.data
    assert b"Run your coworking" not in r.data
    assert b"Operator" not in r.data  # the recruit-an-operator card must not leak here


def test_unmatched_real_domain_resolves_to_no_tenant_even_when_one_exists():
    """The production-correctness bug this session's testing exposed: any
    unmatched Host used to fall back to the first tenant, so visiting the
    platform's own real apex domain (hub1z.com) would incorrectly show a
    tenant's page if one existed. Only bare localhost/127.0.0.1 should get
    that dev-convenience fallback."""
    app = _app()
    with app.app_context():
        db.session.add(Tenant(slug="adyarspace", name="Adyar Space",
                              primary_domain="adyarspace.hub1z.com", status=TenantStatus.ACTIVE))
        db.session.commit()

    c = app.test_client()
    r = c.get("/", headers={"Host": "hub1z.com"})  # the platform's real apex, unmatched by design
    assert b"Run your coworking" in r.data
    assert b"Adyar Space" not in r.data

    # bare localhost still gets the dev-convenience fallback to the first tenant
    r2 = c.get("/", headers={"Host": "localhost"})
    assert b"Adyar Space" in r2.data


def test_tenant_domain_who_its_for_has_two_doors_not_three():
    """The old 'Operator' recruiting card must not appear on a tenant's own site."""
    app = _app()
    with app.app_context():
        db.session.add(Tenant(slug="adyarspace", name="Adyar Space",
                              primary_domain="adyarspace.hub1z.com", status=TenantStatus.ACTIVE))
        db.session.commit()
    c = app.test_client()
    r = c.get("/", headers={"Host": "adyarspace.hub1z.com"})
    assert b"Two doors" in r.data
    assert b"Three doors" not in r.data
