"""Operator lifecycle emails (welcome, upgrade) and the on-screen preview."""
import os
from datetime import date

os.environ.setdefault("FLASK_ENV", "testing")

import pytest

from app import create_app
from app.extensions import db
from app.models import Operator, OperatorStatus, PricingTier, TierStatus, User, UserRole
from app.services import mail_service, operator_billing, operator_emails
from tests.test_role_paths import APEX, _seeded_app


@pytest.fixture()
def sent(monkeypatch):
    calls = []
    monkeypatch.setattr(mail_service, "send", lambda subject, recipient, template, **ctx: calls.append(
        {"subject": subject, "to": recipient, "template": template, "ctx": ctx}))
    return calls


def _bare_app():
    app = create_app({"SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:", "WTF_CSRF_ENABLED": False,
                      "MAIL_SUPPRESS_SEND": True, "STORAGE_BACKEND": "local",
                      "LOCAL_STORAGE_DIR": "./var/test-uploads", "PLATFORM_BASE_DOMAIN": "localhost",
                      "RATELIMIT_ENABLED": False})
    with app.app_context():
        db.create_all()
    return app


SIGNUP = {"business_name": "Lotus Works", "country_code": "IN", "slug": "lotusworks",
          "admin_full_name": "Priya Raman", "admin_email": "priya@lotus.example", "password": "LotusPass123!",
          "confirm": "LotusPass123!"}


def test_self_serve_signup_sends_a_welcome_email_with_plan_and_workspace_address(sent):
    app = _bare_app()
    r = app.test_client().post("/auth/register/operator", data=SIGNUP, headers={"Host": APEX})
    assert r.status_code == 302
    mail = [m for m in sent if m["template"] == "operator_welcome"]
    assert len(mail) == 1 and mail[0]["to"] == "priya@lotus.example"
    ctx = mail[0]["ctx"]
    assert ctx["operator"].primary_domain == "lotusworks.localhost" and ctx["plan_label"] == "Free trial"
    assert ctx["trial_days"] >= 1 and ctx["login_url"].endswith("/auth/login") and ctx["trial_ends"]


def test_invited_operator_gets_the_welcome_email_after_setting_a_password(sent):
    app = _bare_app()
    with app.app_context():
        op = Operator(slug="invited", name="Invited Space", primary_domain="invited.localhost")
        db.session.add(op)
        db.session.flush()
        user = User(operator_id=op.id, email="owner@invited.example", full_name="Ira Owner",
                    role=UserRole.SUPER_ADMIN, is_active=False)
        user.set_password("placeholder-secret")
        db.session.add(user)
        db.session.commit()
        token = mail_service.make_token(user.id, "platform-operator-invite")
    r = app.test_client().post(f"/platform/operators/accept/{token}", headers={"Host": APEX},
                               data={"password": "NewPass12345!", "confirm": "NewPass12345!"})
    assert r.status_code == 302
    welcome = [m for m in sent if m["template"] == "operator_welcome"]
    assert len(welcome) == 1 and welcome[0]["to"] == "owner@invited.example"
    assert welcome[0]["ctx"]["operator"].name == "Invited Space"


def _paid_tier():
    tier = PricingTier(key="growth_t", name="Growth", monthly_price=9999, status=TierStatus.ACTIVE, is_active=True,
                       sort_order=20, description="Multiple locations and reports.", max_locations=3,
                       storage_mb=2048)
    higher = PricingTier(key="scale_t", name="Business", monthly_price=19999, status=TierStatus.ACTIVE,
                         is_active=True, sort_order=30, max_locations=10, storage_mb=None)
    db.session.add_all([tier, higher])
    db.session.flush()
    return tier


def _trial_operator():
    op = Operator(slug="trialco", name="Trial Co", primary_domain="trialco.localhost", status=OperatorStatus.TRIAL)
    db.session.add(op)
    db.session.flush()
    owner = User(operator_id=op.id, email="boss@trial.example", full_name="Boss", role=UserRole.SUPER_ADMIN,
                 is_active=True)
    owner.set_password("x-secret-123")
    db.session.add(owner)
    operator_billing.start_trial(op)
    db.session.commit()
    return op


def test_first_payment_sends_the_upgrade_email_once_after_commit(sent):
    app = _bare_app()
    with app.app_context():
        tier = _paid_tier()
        op = _trial_operator()
        invoice = operator_billing.request_plan(op, tier)
        db.session.commit()
        assert [m for m in sent if m["template"] == "operator_upgraded"] == []
        operator_billing.confirm_payment(invoice, invoice.amount, "upi", reference="UTR1")
        assert [m for m in sent if m["template"] == "operator_upgraded"] == []      # not before commit
        db.session.commit()
        upgrades = [m for m in sent if m["template"] == "operator_upgraded"]
        assert len(upgrades) == 1 and upgrades[0]["to"] == "boss@trial.example"
        ctx = upgrades[0]["ctx"]
        assert ctx["tier_name"] == "Growth" and ctx["invoice_number"] == invoice.number
        assert ctx["higher_tiers"][0]["name"] == "Business"
        assert op.status == OperatorStatus.ACTIVE


def test_no_upgrade_email_when_the_payment_transaction_rolls_back(sent):
    app = _bare_app()
    with app.app_context():
        tier = _paid_tier()
        op = _trial_operator()
        invoice = operator_billing.request_plan(op, tier)
        db.session.commit()
        operator_billing.confirm_payment(invoice, invoice.amount, "upi", reference="UTR2")
        db.session.rollback()
        db.session.commit()
        assert [m for m in sent if m["template"] == "operator_upgraded"] == []


def test_a_later_plan_change_does_not_send_the_first_upgrade_email_again(sent):
    app = _bare_app()
    with app.app_context():
        tier = _paid_tier()
        op = _trial_operator()
        first = operator_billing.request_plan(op, tier)
        operator_billing.confirm_payment(first, first.amount, "upi", reference="A")
        db.session.commit()
        sent.clear()
        bigger = PricingTier.query.filter_by(key="scale_t").one()
        second = operator_billing.request_plan(op, bigger)
        operator_billing.confirm_payment(second, second.amount, "upi", reference="B")
        db.session.commit()
    assert [m for m in sent if m["template"] == "operator_upgraded"] == []


def test_preview_page_shows_all_three_emails_on_screen_only(sent):
    app = create_app({"SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:", "WTF_CSRF_ENABLED": False, "DEBUG": True,
                      "MAIL_SUPPRESS_SEND": True, "STORAGE_BACKEND": "local",
                      "LOCAL_STORAGE_DIR": "./var/test-uploads", "PLATFORM_BASE_DOMAIN": "localhost",
                      "RATELIMIT_ENABLED": False})
    with app.app_context():
        db.create_all()
    page = app.test_client().get("/ui-preview/emails", headers={"Host": APEX})
    assert page.status_code == 200
    html = page.data.decode()
    for text in ("Set my password", "lotusworks.hub1z.com", "Free trial", "Congratulations", "When you grow",
                 "Whenever you need more room"):
        assert text in html, text
    assert sent == []


def test_emails_render_without_higher_plans_and_without_trial_dates():
    app = _bare_app()
    with app.test_request_context("/"):
        from flask import render_template
        from types import SimpleNamespace
        op = SimpleNamespace(name="X", slug="x", primary_domain="x.hub1z.com", plan_tier="starter")
        user = SimpleNamespace(full_name="A B", email="a@b.example")
        html = render_template("emails/operator_welcome.html", user=user, operator=op, plan_label="Free plan",
                               login_url="https://x.hub1z.com/auth/login", higher_tiers=[], trial_ends=None,
                               trial_tier_name=None, trial_days=14)
        assert "When you grow" not in html and "Free until" not in html and "Free plan" in html
