"""Operator profile part 2: owner or director, representative authority, KYC documents, paid-plan gate."""
import io
import os

os.environ.setdefault("FLASK_ENV", "testing")

from app.cli import PERSONA_PASSWORD
from app.extensions import db
from app.models import Document, Operator, PlatformInvoice, PricingTier, TierStatus
from app.services import owner_details
from tests.test_role_paths import APEX, DEMO, _login, _seeded_app

PAGE = "/admin/settings/owner"
OWNER = {"owner_setup_role": "owner_director", "owner_name": "Ravi Menon", "owner_designation": "Director",
         "owner_mobile": "9876543210", "owner_email": "ravi@demospace.com", "owner_pan": "ABCDE1234F"}


def _file(name="doc.pdf"):
    return (io.BytesIO(b"%PDF-1.4 test"), name)


def _client():
    app, _ = _seeded_app()
    c = app.test_client()
    assert _login(c, DEMO, "owner@demospace.com", PERSONA_PASSWORD).status_code == 302
    return app, c


def _post(c, data, files=True):
    payload = dict(data)
    if files:
        payload.update(pan_file=_file("pan.pdf"), id_file=_file("id.pdf"))
    return c.post(PAGE, data=payload, headers={"Host": DEMO}, content_type="multipart/form-data")


def _status(app):
    with app.app_context():
        return owner_details.status(Operator.query.filter_by(slug="demo").one())


def _paid_tier(app):
    with app.app_context():
        tier = PricingTier(key="paid_t", name="Paid T", monthly_price=4999, status=TierStatus.ACTIVE,
                           is_active=True, sort_order=40)
        db.session.add(tier)
        db.session.commit()
        return tier.id


def test_page_renders_all_sections_and_starts_incomplete():
    app, c = _client()
    page = c.get(PAGE, headers={"Host": DEMO})
    assert page.status_code == 200
    html = page.data.decode()
    for text in ("Who is setting up", "full name", "PAN card", "ID proof"):
        assert text in html, text
    assert _status(app)["complete"] is False


def test_owner_with_details_and_documents_is_complete():
    app, c = _client()
    assert _post(c, OWNER).status_code == 302
    assert _status(app)["complete"] is True
    with app.app_context():
        tags = {d.tag for d in Document.query.filter_by(owner_type="operator").all()}
        assert {"owner_pan_card", "owner_id_proof"} <= tags


def test_missing_documents_keep_it_incomplete():
    app, c = _client()
    _post(c, OWNER, files=False)
    assert _status(app)["complete"] is False


def test_representative_needs_declaration_and_authorisation_letter():
    app, c = _client()
    rep = {**OWNER, "owner_setup_role": "representative", "rep_designation": "Finance manager"}
    _post(c, rep)
    assert _status(app)["complete"] is False
    _post(c, {**rep, "rep_declaration": "y"})
    assert _status(app)["complete"] is False                     # still no authorisation letter
    c.post(PAGE, data={**rep, "rep_declaration": "y", "auth_file": _file("letter.pdf")},
           headers={"Host": DEMO}, content_type="multipart/form-data")
    assert _status(app)["complete"] is True


def test_bad_mobile_and_pan_are_rejected():
    app, c = _client()
    r = _post(c, {**OWNER, "owner_mobile": "12345", "owner_pan": "nope"})
    assert r.status_code == 200
    assert b"10-digit" in r.data and b"ABCDE1234F" in r.data
    assert _status(app)["complete"] is False


def test_paid_plan_is_blocked_until_owner_details_are_complete():
    app, c = _client()
    tier_id = _paid_tier(app)
    r = c.post("/admin/hub1z-billing/plans", data={"tier_id": tier_id, "cycle": "monthly"}, headers={"Host": DEMO})
    assert r.status_code == 302 and r.headers["Location"].endswith(PAGE)
    with app.app_context():
        assert PlatformInvoice.query.count() == 0
    _post(c, OWNER)
    r = c.post("/admin/hub1z-billing/plans", data={"tier_id": tier_id, "cycle": "monthly"}, headers={"Host": DEMO})
    assert r.status_code == 302 and not r.headers["Location"].endswith(PAGE)
    with app.app_context():
        assert PlatformInvoice.query.count() == 1


def test_only_the_operator_owner_can_open_the_page():
    app, _ = _seeded_app()
    c = app.test_client()
    _login(c, DEMO, "admin@acmeco.com", PERSONA_PASSWORD)
    assert c.get(PAGE, headers={"Host": DEMO}).status_code in (302, 403)
    anon = app.test_client()
    assert anon.get(PAGE, headers={"Host": DEMO}).status_code in (302, 401)
