"""First-run polish: slug availability, platform operator edit, guide on the dashboard, emails and form help."""
import os
import re

os.environ.setdefault("FLASK_ENV", "testing")

from app import create_app
from app.extensions import db
from app.models import Location, Operator, OperatorStatus, User, UserRole
from app.services import mail_service, operator_emails
from app.services.operator_billing import start_trial
from tests.test_operator_emails import _bare_app, sent  # noqa: F401  (sent is a fixture)
from tests.test_role_paths import APEX, DEMO, _login, _seeded_app

PASSWORD = "NewPass12345!"


def _new_workspace(app, slug="newco"):
    with app.app_context():
        op = Operator(slug=slug, name="Newco Spaces", primary_domain=f"{slug}.localhost", status=OperatorStatus.TRIAL)
        db.session.add(op)
        db.session.flush()
        user = User(operator_id=op.id, email=f"boss@{slug}.example", full_name="Boss", role=UserRole.SUPER_ADMIN,
                    is_active=True)
        user.set_password(PASSWORD)
        db.session.add(user)
        start_trial(op)
        db.session.commit()
        return op.id, user.email


def _client(app, slug="newco"):
    _, email = _new_workspace(app, slug)
    c = app.test_client()
    assert _login(c, f"{slug}.localhost", email, PASSWORD).status_code == 302
    return c, f"{slug}.localhost"


# ---------------------------------------------------------------- slug availability

def test_slug_check_reports_available_taken_reserved_and_invalid():
    app, _ = _seeded_app()
    c = app.test_client()
    get = lambda s: c.get(f"/auth/slug-check?slug={s}", headers={"Host": APEX}).get_json()
    assert get("fresh-space") == {"available": True, "message": "Available: fresh-space.localhost"}
    assert get("demo")["available"] is False and "taken" in get("demo")["message"]
    assert get("admin")["available"] is False
    assert get("Bad_Slug!")["available"] is False
    assert get("ab")["available"] is False


def test_slug_check_ignores_the_current_operator_only_for_platform_owner():
    app, _ = _seeded_app()
    with app.app_context():
        demo_id = Operator.query.filter_by(slug="demo").one().id
    anon = app.test_client()
    assert anon.get(f"/auth/slug-check?slug=demo&exclude_id={demo_id}", headers={"Host": APEX}).get_json()["available"] is False
    owner = app.test_client()
    assert _login(owner, APEX, "admin@hub1z.com", "ChangeMe123!").status_code == 302
    assert owner.get(f"/auth/slug-check?slug=demo&exclude_id={demo_id}", headers={"Host": APEX}).get_json()["available"] is True


# ---------------------------------------------------------------- platform operator edit

def _edit_payload(op, **over):
    data = {"slug": op.slug, "name": op.name, "brand_color": "#0f766e", "plan_tier": op.plan_tier or "starter",
            "status": op.status.value, "currency_code": "INR", "country_code": "IN", "locale": "en_IN",
            "number_grouping": "indian", "timezone": "Asia/Kolkata", "date_format": "%d-%b-%Y",
            "datetime_format": "%d-%b-%Y %H:%M", "time_format": "%H:%M", "primary_domain": op.primary_domain or "",
            "custom_domain": ""}
    data.update(over)
    return data


def _platform_client(app):
    c = app.test_client()
    assert _login(c, APEX, "admin@hub1z.com", "ChangeMe123!").status_code == 302
    return c


def test_editing_an_operator_with_a_blank_custom_domain_does_not_clash_with_others():
    app, _ = _seeded_app()
    with app.app_context():
        other = Operator.query.filter_by(slug="other").one()
        other.custom_domain = ""          # legacy blank value that used to collide
        demo = Operator.query.filter_by(slug="demo").one()
        db.session.commit()
        payload = _edit_payload(demo, name="Demo Renamed")
        demo_id = demo.id
    r = _platform_client(app).post(f"/platform/operators/{demo_id}/edit", data=payload, headers={"Host": APEX})
    assert r.status_code == 302, r.get_data(as_text=True)[:400]
    with app.app_context():
        demo = Operator.query.filter_by(slug="demo").one()
        assert demo.name == "Demo Renamed" and demo.custom_domain is None


def test_editing_to_a_taken_slug_shows_an_error_instead_of_failing():
    app, _ = _seeded_app()
    with app.app_context():
        demo = Operator.query.filter_by(slug="demo").one()
        payload = _edit_payload(demo, slug="other")
        demo_id = demo.id
    r = _platform_client(app).post(f"/platform/operators/{demo_id}/edit", data=payload, headers={"Host": APEX})
    assert r.status_code == 200 and b"already taken" in r.data


def test_changing_the_slug_moves_the_default_workspace_address():
    app, _ = _seeded_app()
    with app.app_context():
        demo = Operator.query.filter_by(slug="demo").one()
        payload = _edit_payload(demo, slug="demo-two")
        demo_id = demo.id
    r = _platform_client(app).post(f"/platform/operators/{demo_id}/edit", data=payload, headers={"Host": APEX})
    assert r.status_code == 302
    with app.app_context():
        assert db.session.get(Operator, demo_id).primary_domain == "demo-two.localhost"


# ---------------------------------------------------------------- password set -> sign in

def test_sign_in_page_confirms_the_password_was_set():
    app = _bare_app()
    page = app.test_client().get("/auth/login?notice=password-set", headers={"Host": APEX})
    assert b"Your password is set" in page.data
    assert b"Your password is set" not in app.test_client().get("/auth/login", headers={"Host": APEX}).data


def test_accepting_an_invite_sends_the_owner_to_the_sign_in_page_with_the_confirmation():
    app = _bare_app()
    with app.app_context():
        op = Operator(slug="invited2", name="Invited Two", primary_domain="invited2.localhost")
        db.session.add(op)
        db.session.flush()
        user = User(operator_id=op.id, email="o@invited2.example", full_name="Ira", role=UserRole.SUPER_ADMIN,
                    is_active=False)
        user.set_password("placeholder-secret")
        db.session.add(user)
        db.session.commit()
        token = mail_service.make_token(user.id, "platform-operator-invite")
    r = app.test_client().post(f"/platform/operators/accept/{token}", headers={"Host": APEX},
                               data={"password": PASSWORD, "confirm": PASSWORD})
    assert r.status_code == 302 and r.headers["Location"].endswith("/auth/login?notice=password-set")


# ---------------------------------------------------------------- first-run guide

def test_new_workspace_sees_the_guide_until_the_first_location_exists():
    app = _bare_app()
    c, host = _client(app)
    html = c.get("/admin/", headers={"Host": host}).get_data(as_text=True)
    assert "Add your first location" in html and "Newco Spaces overview" in html
    assert "change it any time" in html and "All clear" not in html
    with app.app_context():
        op = Operator.query.filter_by(slug="newco").one()
        db.session.add(Location(operator_id=op.id, name="Main", code="MAIN", address_line1="1 High Street",
                                city="Chennai"))
        db.session.commit()
    html = c.get("/admin/", headers={"Host": host}).get_data(as_text=True)
    assert "Next: Add your seats and meeting rooms" in html and "Add meeting rooms" in html


def test_closing_the_guide_hides_it_for_the_session_only():
    app = _bare_app()
    c, host = _client(app)
    assert c.post("/admin/onboarding/dismiss", data={"step": "location"}, headers={"Host": host}).status_code == 302
    html = c.get("/admin/", headers={"Host": host}).get_data(as_text=True)
    assert "Add your first location" not in html or "Welcome. Let" not in html
    assert "All clear" in html
    again = app.test_client()
    _login(again, host, "boss@newco.example", PASSWORD)
    assert "Welcome. Let" in again.get("/admin/", headers={"Host": host}).get_data(as_text=True)


def test_established_workspace_has_no_guide_banner():
    app, _ = _seeded_app()
    c = app.test_client()
    _login(c, DEMO, "owner@demospace.com", "DemoPass123!")
    html = c.get("/admin/", headers={"Host": DEMO}).get_data(as_text=True)
    assert "Welcome. Let" not in html


# ---------------------------------------------------------------- emails and form help

def test_emails_open_with_the_logo_and_dear():
    app = _bare_app()
    with app.test_request_context("/"):
        from flask import render_template
        for name in ("platform_operator_invite", "operator_welcome", "operator_upgraded"):
            pass
        for e in operator_emails.sample_emails():
            assert "hub1z-logo-tagline-small.png" in e["html"], e["key"]
            assert "Dear Priya Raman," in e["html"] and "Dear Priya Raman," in e["text"], e["key"]


def test_real_email_carries_the_logo_as_an_inline_image():
    app = _bare_app()
    app.config["MAIL_SUPPRESS_SEND"] = False
    captured = []
    from app.extensions import mail
    with app.test_request_context("/"), mail.record_messages() as outbox:
        from types import SimpleNamespace
        mail_service.send("Hi", "x@y.example", "operator_welcome",
                          user=SimpleNamespace(full_name="A B", email="x@y.example"),
                          operator=SimpleNamespace(name="X", slug="x", primary_domain="x.hub1z.com", plan_tier="s"),
                          plan_label="Free trial", login_url="https://x.hub1z.com/auth/login", higher_tiers=[],
                          trial_ends=None, trial_tier_name=None, trial_days=14, operator_name="Hub1z")
        captured.extend(outbox)
    assert "cid:hub1z-logo" in captured[0].html
    assert any(a.headers.get("Content-ID") == "<hub1z-logo>" for a in captured[0].attachments)


def test_plan_form_has_tooltips_on_seat_fields():
    app, _ = _seeded_app()
    c = app.test_client()
    _login(c, DEMO, "owner@demospace.com", "DemoPass123!")
    html = c.get("/admin/plans/new", headers={"Host": DEMO}).get_data(as_text=True)
    assert html.count('data-bs-toggle="tooltip"') >= 2 and "Included seat quantity" in html


def test_workspace_card_lists_pricing_plans_before_locations():
    app, _ = _seeded_app()
    c = app.test_client()
    _login(c, DEMO, "owner@demospace.com", "DemoPass123!")
    html = c.get("/admin/", headers={"Host": DEMO}).get_data(as_text=True)
    assert html.index("Pricing plans") < html.index("Locations, floors, seats, rooms")
