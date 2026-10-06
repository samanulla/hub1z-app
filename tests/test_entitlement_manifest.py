"""Draft-only pricing manifest creation; no customer-facing activation."""
import os

os.environ.setdefault("FLASK_ENV", "testing")

from app import create_app
from app.extensions import db
from app.models import (EntitlementOfferGrant, EntitlementOfferVersion, PlatformProfile,
                        PricingTier, TenantPlanBinding)
from app.services.entitlement_manifest import (BASE_CAPABILITIES, GIB, GROWTH_CAPABILITIES,
                                               ensure_manifest_drafts)
from app.services.pricing_page import public_catalog, public_tiers


def _app():
    app = create_app({"SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:", "WTF_CSRF_ENABLED": False,
                      "ENTITLEMENTS_SHADOW_ENABLED": False,
                      "ENTITLEMENTS_ENFORCEMENT_ENABLED": False})
    with app.app_context():
        db.create_all()
        PlatformProfile.get()
        db.session.commit()
    return app


def test_manifest_creates_only_unpublished_offers_and_no_tenant_bindings():
    app = _app()
    with app.app_context():
        offers = ensure_manifest_drafts()
        db.session.commit()

        assert len(offers) == 8
        assert all(offer["status"] == "draft" and not offer["publicly_listed"] for offer in offers)
        assert TenantPlanBinding.query.count() == 0
        assert PricingTier.query.count() == 0
        assert PlatformProfile.get().pricing_page_public is False
        assert public_tiers() == []
        assert public_catalog() is None

        second_run = ensure_manifest_drafts()
        assert [(row["offer_key"], row["id"]) for row in second_run] == [
            (row["offer_key"], row["id"]) for row in offers]
        assert EntitlementOfferVersion.query.count() == 8
        assert TenantPlanBinding.query.count() == 0


def test_plan_drafts_have_explicit_allowances_without_all_features():
    app = _app()
    with app.app_context():
        ensure_manifest_drafts()
        db.session.commit()

        expected = {
            "starter_v2": (2999, 50, 1, 3, 5 * GIB, 250),
            "growth_v2": (7999, 150, 3, None, 25 * GIB, None),
            "scale_v1": (19999, 400, 8, None, 100 * GIB, None),
            "enterprise_v1": (44999, 1000, 15, None, None, None),
        }
        for key, values in expected.items():
            offer = EntitlementOfferVersion.query.filter_by(offer_key=key).one()
            terms = offer.terms_snapshot
            grants = {grant.entitlement_key: grant for grant in EntitlementOfferGrant.query.filter_by(
                offer_version_id=offer.id).all()}
            assert tuple((offer.base_price, terms["included_seats"], terms["included_locations"],
                          grants["staff_accounts"].numeric_value,
                          grants.get("document_storage_bytes").numeric_value if grants.get("document_storage_bytes") else None,
                          grants["open_manual_leads"].numeric_value)
                         ) == values
            assert "all_features" not in terms
            assert "gst_einvoicing" not in grants and "api_webhooks" not in grants
            assert set(BASE_CAPABILITIES) <= set(grants)
            if key in ("growth_v2", "scale_v1", "enterprise_v1"):
                assert set(GROWTH_CAPABILITIES) <= set(grants)
        scale = EntitlementOfferVersion.query.filter_by(offer_key="scale_v1").one()
        scale_grants = {grant.entitlement_key for grant in EntitlementOfferGrant.query.filter_by(
            offer_version_id=scale.id).all()}
        assert "white_label" in scale_grants and "network_reports" in scale_grants
        assert scale.terms_snapshot["future_inclusions_when_built"] == ["gst_einvoicing", "api_webhooks"]
        enterprise = EntitlementOfferVersion.query.filter_by(offer_key="enterprise_v1").one()
        assert enterprise.terms_snapshot["public_feature_list"] is False


def test_manifest_prices_preserve_overage_ladder_and_annual_terms():
    app = _app()
    with app.app_context():
        ensure_manifest_drafts()
        db.session.commit()
        offers = {offer.offer_key: offer for offer in EntitlementOfferVersion.query.all()
                  if offer.kind == "base_plan"}
        assert offers["starter_v2"].terms_snapshot["annual_price"] == 29990
        assert offers["growth_v2"].terms_snapshot["annual_price"] == 79990
        assert offers["scale_v1"].terms_snapshot["annual_price"] == 199990
        assert 2999 + (150 - 50) * 55 > 7999
        assert 7999 + (400 - 150) * 49 > 19999
        assert 19999 + (1000 - 400) * 45 > 44999


def test_addon_and_service_drafts_keep_holds_and_scope_in_metadata():
    app = _app()
    with app.app_context():
        ensure_manifest_drafts()
        db.session.commit()

        storage = EntitlementOfferVersion.query.filter_by(offer_key="extra_storage_v1").one()
        storage_grant = EntitlementOfferGrant.query.filter_by(offer_version_id=storage.id).one()
        assert storage.base_price == 149 and storage_grant.numeric_value == 5 * GIB
        white_label = EntitlementOfferVersion.query.filter_by(offer_key="white_label_v1").one()
        assert white_label.base_price == 2499
        assert white_label.terms_snapshot["trial_eligible"] is False
        growth = EntitlementOfferVersion.query.filter_by(offer_key="growth_v2").one()
        growth_grants = {grant.entitlement_key for grant in EntitlementOfferGrant.query.filter_by(
            offer_version_id=growth.id).all()}
        assert {"people_analytics", "booking_heatmap"} <= growth_grants
        office = EntitlementOfferVersion.query.filter_by(offer_key="virtual_office_v1").one()
        assert office.terms_snapshot["hold"] is True
        assert EntitlementOfferGrant.query.filter_by(offer_version_id=office.id).count() == 0
        onboarding = EntitlementOfferVersion.query.filter_by(offer_key="assisted_onboarding_v1").one()
        assert onboarding.kind == "service" and onboarding.billing_period == "one_time"
        assert onboarding.terms_snapshot["fulfillment_workflow_built"] is False


def test_manifest_cli_reports_unpublished_drafts():
    app = _app()
    result = app.test_cli_runner().invoke(args=["seed-entitlement-drafts"])
    assert result.exit_code == 0, result.output
    assert "Created/verified 8 draft offer(s)" in result.output
    assert "status=draft publicly_listed=False" in result.output
    with app.app_context():
        assert EntitlementOfferVersion.query.count() == 8
        assert TenantPlanBinding.query.count() == 0
