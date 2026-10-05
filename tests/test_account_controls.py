import os

os.environ.setdefault("FLASK_ENV", "testing")

from app.extensions import db
from app.models import User
from tests.test_release_upi_parcels_alerts import DEMO, _client, _get, _post, _seeded_app
from tests.test_role_paths import _login, APEX, OWNER_PASSWORD
from app.cli import PERSONA_PASSWORD
from urllib.parse import urlparse
from email.utils import parseaddr


def test_deactivation_blocks_login_and_existing_session():
    app, _ = _seeded_app()
    employee = _client(app, DEMO, "employee@acmeco.com")
    owner = _client(app, DEMO, "admin@acmeco.com")
    with app.app_context():
        user_id = User.query.execution_options(skip_operator_filter=True).filter_by(email="employee@acmeco.com").one().id
    assert _post(owner, DEMO, f"/company/employees/{user_id}/deactivate").status_code == 302
    assert _get(employee, DEMO, "/me/").status_code in (302, 401)
    login = _login(app.test_client(), DEMO, "employee@acmeco.com", PERSONA_PASSWORD)
    assert login.status_code == 200 and b'Invalid email or password' in login.data


def test_self_profile_and_company_admin_edit_are_available():
    app, _ = _seeded_app()
    employee = _client(app, DEMO, "employee@acmeco.com")
    assert _post(employee, DEMO, "/auth/profile", {"full_name": "Updated Employee", "phone": "9876543210"}).status_code == 302
    with app.app_context():
        user = User.query.execution_options(skip_operator_filter=True).filter_by(email="employee@acmeco.com").one()
        assert user.full_name == "Updated Employee" and user.phone == "9876543210"
        admin_id = User.query.execution_options(skip_operator_filter=True).filter_by(email="admin@acmeco.com").one().id
    company_admin = _client(app, DEMO, "admin@acmeco.com")
    assert _get(company_admin, DEMO, f"/company/employees/{admin_id}/edit").status_code == 200
    assert f'/company/employees/{admin_id}/edit'.encode() in _get(company_admin, DEMO, "/company/employees").data


def test_resend_replaces_invite_and_revoke_blocks_acceptance(monkeypatch):
    app, _ = _seeded_app()
    sent = []
    monkeypatch.setattr("app.services.mail_service.send", lambda **context: sent.append(context))
    admin = _client(app, DEMO, "admin@acmeco.com")
    assert _post(admin, DEMO, "/company/employees/new", {"full_name": "Pending", "email": "pending@acme.com", "seat_allocation_id": "0"}).status_code == 302
    first_path = urlparse(sent[-1]["accept_url"]).path
    with app.app_context():
        user_id = User.query.execution_options(skip_operator_filter=True).filter_by(email="pending@acme.com").one().id
    assert _post(admin, DEMO, f"/company/employees/{user_id}/resend").status_code == 302
    new_path = urlparse(sent[-1]["accept_url"]).path
    guest = app.test_client()
    assert _get(guest, DEMO, first_path).status_code == 302
    assert _get(guest, DEMO, new_path).status_code == 200
    assert _post(admin, DEMO, f"/company/employees/{user_id}/deactivate").status_code == 302
    assert _post(guest, DEMO, new_path, {"password": "NewPassword123!", "confirm": "NewPassword123!"}).status_code == 302
    with app.app_context():
        assert not db.session.get(User, user_id).is_active
        assert db.session.get(User, user_id).invite_revoked


def test_operator_member_edit_deactivate_and_company_archive():
    from app.models import Company, CompanyStatus
    app, _ = _seeded_app()
    owner = _client(app, DEMO, "owner@demospace.com")
    with app.app_context():
        individual_id = User.query.execution_options(skip_operator_filter=True).filter_by(email="individual@demospace.com").one().id
        company_id = Company.query.execution_options(skip_operator_filter=True).filter_by(name="Acme Co").one().id
    assert _post(owner, DEMO, f"/admin/individuals/{individual_id}/edit", {"full_name": "Updated Individual", "email": "individual@demospace.com", "phone": "1234567890"}).status_code == 302
    assert _post(owner, DEMO, f"/admin/individuals/{individual_id}/deactivate").status_code == 302
    assert b'Updated Individual' in _get(owner, DEMO, "/admin/individuals").data
    assert _post(owner, DEMO, f"/admin/companies/{company_id}/archive").status_code == 302
    with app.app_context():
        company = db.session.get(Company, company_id)
        assert company.status == CompanyStatus.CHURNED
        assert all(not user.is_active and user.invite_revoked for user in company.users)
    assert _post(owner, DEMO, f"/admin/companies/{company_id}/restore").status_code == 302
    with app.app_context():
        assert db.session.get(Company, company_id).status == CompanyStatus.ACTIVE
        assert all(user.is_active for user in db.session.get(Company, company_id).users)


def test_suspended_company_cannot_use_existing_session():
    from app.models import Company, CompanyStatus
    app, _ = _seeded_app()
    employee = _client(app, DEMO, "employee@acmeco.com")
    with app.app_context():
        company = Company.query.execution_options(skip_operator_filter=True).filter_by(name="Acme Co").one()
        company.status = CompanyStatus.SUSPENDED
        db.session.commit()
    assert _get(employee, DEMO, "/me/").status_code in (302, 401)


def test_invitation_sender_is_friendly_and_logo_is_inline(monkeypatch):
    from app.models import Company
    from app.services import mail_service
    app, _ = _seeded_app()
    app.config.update(MAIL_SUPPRESS_SEND=False, MAIL_DEFAULT_SENDER="support@hub1z.com", MAIL_REDIRECT_TO="")
    sent = []
    monkeypatch.setattr("app.services.mail_service.mail.send", lambda message: sent.append(message))
    with app.test_request_context(base_url=f"http://{DEMO}"):
        user = User.query.execution_options(skip_operator_filter=True).filter_by(email="employee@acmeco.com").one()
        mail_service.send("Invite", user.email, "employee_invite", user=user, company=user.company,
                          accept_url="https://demo.hub1z.com/invite/test", ttl_days=7)
    message = sent[0]
    assert parseaddr(message.sender) == ("Acme Co on Hub1z", "support@hub1z.com")
    assert "Powered by Hub1z" in message.body
    assert 'cid:hub1z-mark' in message.html
    assert message.attachments[0].headers["Content-ID"] == "<hub1z-mark>"


def test_platform_can_replace_operator_admin_email_and_invalidates_old_access(monkeypatch):
    from app.services import mail_service
    app, _ = _seeded_app()
    departing_admin = _client(app, DEMO, "owner@demospace.com")
    sent = []
    monkeypatch.setattr("app.services.mail_service.send", lambda **context: sent.append(context))
    with app.app_context():
        admin = User.query.execution_options(skip_operator_filter=True).filter_by(email="owner@demospace.com").one()
        admin_id, operator_id = admin.id, admin.operator_id
        old_token = mail_service.make_token(admin.id, "password-reset")
    platform = _client(app, APEX, "admin@hub1z.com", OWNER_PASSWORD)
    response = _post(platform, APEX, f"/platform/operators/{operator_id}/admins/{admin_id}/edit",
                     {"full_name": "New Owner", "email": "replacement@demo.com", "phone": "9876543210"})
    assert response.status_code == 302
    assert sent[-1]["recipient"] == "replacement@demo.com"
    assert _get(departing_admin, DEMO, "/admin/").status_code in (302, 401)
    assert urlparse(sent[-1]["reset_url"]).hostname == DEMO
    with app.app_context():
        admin = db.session.get(User, admin_id)
        assert admin.email == "replacement@demo.com" and not admin.check_password(PERSONA_PASSWORD)
        assert mail_service.read_token(old_token, "password-reset", 7200) is None
    guest = app.test_client()
    reset_path = urlparse(sent[-1]["reset_url"]).path
    response = _post(guest, DEMO, reset_path, {"password": "NewOwnerPass123!", "confirm": "NewOwnerPass123!"})
    assert response.status_code == 302
    assert _login(guest, DEMO, "replacement@demo.com", "NewOwnerPass123!").status_code == 302
    assert _get(guest, DEMO, "/admin/").status_code == 200


def test_direct_operator_provisioning_starts_trial_without_approval():
    from app.models import Operator, OperatorStatus, OperatorSubscription, PricingTier
    app, _ = _seeded_app()
    with app.app_context():
        db.session.add(PricingTier(key="starter", name="Starter", is_active=True))
        db.session.commit()
    platform = _client(app, APEX, "admin@hub1z.com", OWNER_PASSWORD)
    response = _post(platform, APEX, "/platform/operators/new", {
        "slug": "provisioned", "name": "Provisioned Space", "admin_name": "Admin",
        "admin_email": "admin@provisioned.com", "admin_password": "AdminPass123!",
        "status": "trial", "plan_tier": "starter", "brand_color": "#007f78",
        "currency_code": "INR", "country_code": "IN", "locale": "en_IN", "number_grouping": "indian",
        "timezone": "Asia/Kolkata", "date_format": "%d-%b-%Y", "datetime_format": "%d-%b-%Y %H:%M",
        "time_format": "%H:%M", "default_tax_rate": "18", "tax_label": "GST", "invoice_prefix": "INV"})
    assert response.status_code == 302
    with app.app_context():
        operator = Operator.query.filter_by(slug="provisioned").one()
        assert operator.status == OperatorStatus.TRIAL and operator.trial_ends_at is not None
        assert OperatorSubscription.query.filter_by(operator_id=operator.id).one().status == "trial"
    page = _get(platform, APEX, "/platform/operators")
    assert b'Pending approval' not in page.data and b'/approve' not in page.data