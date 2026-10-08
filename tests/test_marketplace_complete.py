"""Marketplace photos, directions, virtual office enquiries, commission invoices and partner onboarding."""
import io
import os
import re
from datetime import date, datetime
from decimal import Decimal

os.environ.setdefault("FLASK_ENV", "testing")

import pytest

from app.cli import PERSONA_PASSWORD
from app.extensions import db
from app.models import (
    CommissionLedgerEntry, Lead, MarketplaceBooking, MarketplaceCustomer, MarketplaceListing, MarketplaceListingPhoto,
    MarketplacePartnerApplication, Operator, OperatorMarketplaceTerms, PlatformInvoice, User,
)
from app.services import mail_service
from app.services import marketplace as mk
from app.services import marketplace_commission as commission
from tests.test_marketplace_public import (
    PRIVATE_ADDRESS, SECRET_DOOR, SPACES, _book, _code, _signin, _world,
)
from tests.test_role_paths import APEX, DEMO, OTHER, OWNER_PASSWORD, _login

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


def _owner(app, host=DEMO, email="owner@demospace.com", password=PERSONA_PASSWORD):
    c = app.test_client()
    assert _login(c, host, email, password).status_code == 302
    return c


def test_operator_photos_show_publicly_and_only_for_live_listings():
    app, ids = _world()
    owner = _owner(app)
    h = {"Host": DEMO}
    ok = owner.post(f"/admin/marketplace/listings/{ids['live']}/photos", headers=h, content_type="multipart/form-data",
                    data={"photos": (io.BytesIO(PNG), "room.png")})
    assert ok.status_code == 302
    owner.post(f"/admin/marketplace/listings/{ids['live']}/photos", headers=h, content_type="multipart/form-data",
               data={"photos": (io.BytesIO(b"not an image"), "fake.png")})
    owner.post(f"/admin/marketplace/listings/{ids['draft']}/photos", headers=h, content_type="multipart/form-data",
               data={"photos": (io.BytesIO(PNG), "draft.png")})
    with app.app_context():
        photos = MarketplaceListingPhoto.query.execution_options(skip_operator_filter=True).all()
        assert len(photos) == 2
        live_photo = [p.id for p in photos if p.listing_id == ids["live"]][0]
        draft_photo = [p.id for p in photos if p.listing_id == ids["draft"]][0]
    c = app.test_client()
    page = c.get(f"/marketplace/l/{ids['live']}", headers={"Host": SPACES}).data.decode()
    assert f"/marketplace/photo/{live_photo}" in page
    assert c.get(f"/marketplace/photo/{live_photo}", headers={"Host": SPACES}).mimetype == "image/png"
    assert c.get(f"/marketplace/photo/{draft_photo}", headers={"Host": SPACES}).status_code == 404
    assert c.get(f"/marketplace/photo/{live_photo}", headers={"Host": DEMO}).status_code == 404

    other = _owner(app, OTHER, "owner@otherspace.com")
    assert other.post(f"/admin/marketplace/photos/{live_photo}/delete", headers={"Host": OTHER}).status_code == 404
    assert owner.post(f"/admin/marketplace/photos/{live_photo}/delete", headers=h).status_code == 302
    assert c.get(f"/marketplace/photo/{live_photo}", headers={"Host": SPACES}).status_code == 404


def test_photos_can_be_hidden_by_the_operator():
    app, ids = _world()
    owner = _owner(app)
    owner.post(f"/admin/marketplace/listings/{ids['live']}/photos", headers={"Host": DEMO},
               content_type="multipart/form-data", data={"photos": (io.BytesIO(PNG), "room.png")})
    with app.app_context():
        pid = MarketplaceListingPhoto.query.execution_options(skip_operator_filter=True).one().id
        row = db.session.get(MarketplaceListing, ids["live"])
        row.visibility = {"photos": False}
        db.session.commit()
    assert app.test_client().get(f"/marketplace/photo/{pid}", headers={"Host": SPACES}).status_code == 404


def test_directions_link_appears_only_after_the_booking_is_confirmed():
    app, ids = _world()
    c = _signin(app.test_client())
    listing_page = c.get(f"/marketplace/l/{ids['live']}", headers={"Host": SPACES}).data.decode()
    assert "google.com/maps" in listing_page and PRIVATE_ADDRESS not in listing_page
    held = _code(_book(c, ids["live"], method="manual_upi"))
    assert "google.com/maps" not in c.get(f"/marketplace/b/{held}", headers={"Host": SPACES}).data.decode()
    confirmed = _code(_book(c, ids["live"], method="pay_at_venue", date_offset=5))
    page = c.get(f"/marketplace/b/{confirmed}", headers={"Host": SPACES}).data.decode()
    assert "Open in Google Maps" in page and "google.com/maps/search" in page and SECRET_DOOR in page


def test_virtual_office_is_an_enquiry_that_lands_in_the_operators_leads_only():
    app, ids = _world()
    with app.app_context():
        base = db.session.get(MarketplaceListing, ids["live"])
        vo = MarketplaceListing(operator_id=base.operator_id, location_id=base.location_id,
                                resource_type="virtual_office", title="Business address plan", status="live",
                                price=1500, approval_mode="request")
        db.session.add(vo)
        db.session.commit()
        vo_id, op_id = vo.id, base.operator_id
    c = app.test_client()
    page = c.get(f"/marketplace/l/{vo_id}", headers={"Host": SPACES}).data.decode()
    assert "Send enquiry" in page and "Book now" not in page
    assert "Business address plan" in c.get("/marketplace/?kind=virtual_office", headers={"Host": SPACES}).data.decode()
    r = c.post(f"/marketplace/l/{vo_id}/enquire", headers={"Host": SPACES},
               data={"name": "Ravi K", "email": "ravi@example.com", "company": "RK Traders", "message": "Need GST address"})
    assert r.status_code == 302
    with app.app_context():
        lead = Lead.query.execution_options(skip_operator_filter=True).filter_by(email="ravi@example.com").one()
        assert lead.operator_id == op_id and lead.source == "Hub1z Marketplace"
    owner, other = _owner(app), _owner(app, OTHER, "owner@otherspace.com")
    assert b"Ravi K" in owner.get("/admin/leads", headers={"Host": DEMO}).data
    assert b"Ravi K" not in other.get("/admin/leads", headers={"Host": OTHER}).data
    with app.app_context():
        from datetime import timedelta
        customer = MarketplaceCustomer(email="vo@example.com", full_name="VO")
        db.session.add(customer)
        db.session.flush()
        start = datetime.utcnow() + timedelta(days=3)
        with pytest.raises(mk.MarketplaceError, match="enquiry"):
            mk.create_booking(listing=db.session.get(MarketplaceListing, vo_id), customer=customer, start=start,
                              end=start + timedelta(hours=1), idempotency_key="x", payment_method="pay_at_venue")


def test_commission_accrues_invoices_with_gst_once_and_reverses_on_cancellation():
    app, ids = _world()
    c = _signin(app.test_client())
    code = _code(_book(c, ids["live"]))                      # 2h x Rs 500 = Rs 1000, 10% commission
    with app.app_context():
        entries = CommissionLedgerEntry.query.execution_options(skip_operator_filter=True).all()
        assert [e.amount for e in entries] == [Decimal("100.00")]
        month = commission.month_start(date.today())
        made = commission.generate_invoices(commission.next_month(month))
        assert len(made) == 1 and made[0].kind == "commission" and made[0].subtotal == Decimal("100.00")
        assert made[0].amount == Decimal("118.00")
        assert commission.generate_invoices(commission.next_month(month)) == []
        assert entries[0].invoiced_in == made[0].number

    owner = _owner(app)
    page = owner.get("/admin/marketplace/commission", headers={"Host": DEMO}).data.decode()
    assert "Commission" in page and code in page
    c.post(f"/marketplace/b/{code}/cancel", headers={"Host": SPACES})
    with app.app_context():
        total = sum(e.amount for e in CommissionLedgerEntry.query.execution_options(skip_operator_filter=True).all())
        assert total == Decimal("0.00")
        assert commission.generate_invoices(commission.next_month(commission.month_start(date.today()))) == []


def test_platform_approves_workspaces_and_sets_the_commission_rate():
    app, ids = _world()
    platform = _owner(app, APEX, "admin@hub1z.com", OWNER_PASSWORD)
    assert platform.get("/platform/marketplace", headers={"Host": APEX}).status_code == 200
    with app.app_context():
        demo_id = Operator.query.execution_options(skip_operator_filter=True).filter_by(primary_domain=DEMO).one().id
    platform.post(f"/platform/marketplace/operators/{demo_id}", data={"approved": "1", "commission_pct": "9"},
                  headers={"Host": APEX})
    with app.app_context():
        terms = OperatorMarketplaceTerms.query.execution_options(skip_operator_filter=True).filter_by(
            operator_id=demo_id).one()
        assert terms.kyc_approved and terms.commission_pct == Decimal("9.00")
    platform.post(f"/platform/marketplace/operators/{demo_id}", data={"commission_pct": "9"}, headers={"Host": APEX})
    with app.app_context():
        assert not OperatorMarketplaceTerms.query.execution_options(skip_operator_filter=True).filter_by(
            operator_id=demo_id).one().kyc_approved
    assert app.test_client().get("/platform/marketplace", headers={"Host": APEX}).status_code == 302


APPLICATION = {"business_name": "Lotus Corner Works", "contact_name": "Meera S", "email": "meera@lotus.example",
               "phone": "9000000001", "address_line1": "5 Beach Road", "city": "Kochi", "state": "Kerala",
               "postal_code": "682001", "gstin": "32AAACL1234F1Z5", "pan": "AAACL1234F", "upi_id": "lotus@okaxis",
               "agree": "1"}


def test_external_workspace_applies_is_approved_and_gets_a_limited_workspace():
    app, ids = _world()
    guest = app.test_client()
    assert guest.get("/marketplace/list-your-space", headers={"Host": SPACES}).status_code == 200
    bad = guest.post("/marketplace/list-your-space", headers={"Host": SPACES}, data={**APPLICATION, "gstin": "BAD"})
    assert bad.status_code == 200 and b"GSTIN" in bad.data
    ok = guest.post("/marketplace/list-your-space", headers={"Host": SPACES}, data=APPLICATION)
    assert ok.status_code == 200 and b"Application received" in ok.data
    again = guest.post("/marketplace/list-your-space", headers={"Host": SPACES}, data=APPLICATION)
    assert b"already have an application" in again.data
    with app.app_context():
        application = MarketplacePartnerApplication.query.one()
        app_id = application.id
        lead = Lead.query.execution_options(skip_operator_filter=True).filter_by(source="Marketplace partner").one()
        assert lead.operator_id is None and lead.company_name == "Lotus Corner Works"

    platform = _owner(app, APEX, "admin@hub1z.com", OWNER_PASSWORD)
    assert b"Lotus Corner Works" in platform.get("/platform/marketplace", headers={"Host": APEX}).data
    r = platform.post(f"/platform/marketplace/applications/{app_id}/approve", data={"commission_pct": "13"},
                      headers={"Host": APEX})
    assert r.status_code == 302
    with app.app_context():
        operator = Operator.query.execution_options(skip_operator_filter=True).filter_by(
            name="Lotus Corner Works").one()
        assert operator.plan_tier == "marketplace_partner" and operator.status.value == "active"
        assert operator.trial_ends_at is None and operator.gstin == "32AAACL1234F1Z5"
        terms = OperatorMarketplaceTerms.query.execution_options(skip_operator_filter=True).filter_by(
            operator_id=operator.id).one()
        assert terms.kyc_approved and not terms.enabled and terms.commission_pct == Decimal("13.00")
        owner_user = User.query.execution_options(skip_operator_filter=True).filter_by(email="meera@lotus.example").one()
        assert not owner_user.is_active
        token = mail_service.make_token(owner_user.id, "platform-operator-invite")
        host = operator.primary_domain
    done = guest.post(f"/platform/operators/accept/{token}", headers={"Host": APEX},
                      data={"password": "PartnerPass123!", "confirm": "PartnerPass123!"})
    assert done.status_code == 302
    with app.app_context():
        assert Operator.query.execution_options(skip_operator_filter=True).filter_by(
            name="Lotus Corner Works").one().trial_ends_at is None
    partner = app.test_client()
    assert _login(partner, host, "meera@lotus.example", "PartnerPass123!").status_code == 302
    landing = partner.get("/admin/", headers={"Host": host})
    assert landing.status_code == 302 and "/admin/marketplace" in landing.headers["Location"]
    page = partner.get("/admin/marketplace", headers={"Host": host}).data.decode()
    assert "Marketplace" in page and "/admin/people" not in page and "/admin/reports" not in page
    assert "Hub1z invoices" in page and "trial" not in page.lower()


def test_search_cards_show_hours_open_days_locality_and_filter_by_locality():
    app, ids = _world()
    with app.app_context():
        row = db.session.get(MarketplaceListing, ids["live"])
        row.availability_windows = [{"days": [0, 1, 2, 3, 4], "from": "08:00", "to": "20:00"}]
        row.location.locality = "Adyar"
        db.session.commit()
    c = app.test_client()
    page = c.get("/marketplace/", headers={"Host": SPACES}).data.decode()
    assert "08:00 AM - 08:00 PM" in page and "Adyar" in page and 'class="on">M' in page
    assert 'class="">S' in page and "Book now" in page
    assert "Demo Boardroom" in c.get("/marketplace/?locality=adyar", headers={"Host": SPACES}).data.decode()
    assert "Demo Boardroom" not in c.get("/marketplace/?locality=Velachery", headers={"Host": SPACES}).data.decode()
