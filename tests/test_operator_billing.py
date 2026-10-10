"""Payment-confirmed operator subscriptions and retained trial access."""
import json
import os
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

os.environ.setdefault("FLASK_ENV", "testing")

from app import create_app
from app.extensions import db
from app.models import (Operator, OperatorAddon, OperatorStatus, OperatorSubscription, PlatformInvoice,
                        PlatformInvoiceStatus, PlatformPayment, PlatformProfile, PricingTier, TierStatus)
from app.services.catalog import DEFAULT_TIERS, LOCKABLE_CODES, ensure_catalog
from app.services.entitlements import has_feature
from app.services import operator_billing as billing


@pytest.fixture
def scenario():
    app = create_app({"SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:", "WTF_CSRF_ENABLED": False,
                      "MAIL_SUPPRESS_SEND": True, "STORAGE_BACKEND": "local", "LOCAL_STORAGE_DIR": "./var/test-uploads"})
    with app.app_context():
        db.create_all()
        ensure_catalog()
        from app.models import PlatformModule
        db.session.add_all(PricingTier(**values) for values in DEFAULT_TIERS)
        db.session.flush()
        growth = PricingTier.query.filter_by(key="growth").one()
        growth.module_catalog = PlatformModule.query.filter(PlatformModule.code.in_(LOCKABLE_CODES)).all()
        operator = Operator(slug="billing", name="Billing", primary_domain="billing.hub1z.com", gst_state="29",
                            status=OperatorStatus.TRIAL, trial_ends_at=datetime.utcnow() - timedelta(days=1))
        db.session.add(operator)
        profile = PlatformProfile.get()
        profile.gst_state = "29"
        for key, price in (("starter", 1000), ("growth", 2000)):
            tier = PricingTier.query.filter_by(key=key).one()
            tier.monthly_price = price
            tier.status = TierStatus.ACTIVE
            tier.is_active = True
        db.session.commit()
        yield app, operator
        db.session.remove()
        db.drop_all()


def test_invoice_partial_payment_and_activation(scenario):
    app, operator = scenario
    starter = PricingTier.query.filter_by(key="starter").one()
    invoice = billing.request_plan(operator, starter)
    assert invoice.due_date == date.today()
    assert invoice.subtotal == Decimal("1000")
    assert invoice.cgst == invoice.sgst == Decimal("90")
    assert invoice.igst == 0
    assert operator.plan_tier == "starter"
    assert has_feature(operator, "payroll")
    assert billing.request_plan(operator, starter).id == invoice.id
    billing.confirm_payment(invoice, 500, "upi")
    assert invoice.status == PlatformInvoiceStatus.ISSUED
    assert has_feature(operator, "payroll")
    billing.confirm_payment(invoice, 680, "bank", "REF123")
    db.session.commit()
    assert invoice.status == PlatformInvoiceStatus.PAID
    assert operator.status == OperatorStatus.ACTIVE
    assert not has_feature(operator, "payroll")
    assert has_feature(operator, "bookings")
    assert billing.payment_total(invoice) == Decimal("1180")
    billing.confirm_payment(invoice, 680, "bank")
    assert PlatformPayment.query.count() == 2


def test_prorated_upgrade_keeps_renewal_date(scenario):
    app, operator = scenario
    today = date.today()
    starter = PricingTier.query.filter_by(key="starter").one()
    invoice = billing.request_plan(operator, starter, today=today - timedelta(days=10))
    billing.confirm_payment(invoice, invoice.amount, "cash")
    subscription = OperatorSubscription.query.one()
    renewal_date = subscription.current_period_end
    growth = PricingTier.query.filter_by(key="growth").one()
    upgrade = billing.request_plan(operator, growth, today=today)
    remaining = (renewal_date - today).days + 1
    period_days = (renewal_date - subscription.current_period_start).days + 1
    assert upgrade.kind == "upgrade"
    assert upgrade.subtotal == billing.money(Decimal(1000) * remaining / period_days)
    assert operator.plan_tier == "starter"
    billing.confirm_payment(upgrade, upgrade.amount, "gpay")
    assert operator.plan_tier == "growth"
    assert subscription.current_period_end == renewal_date
    assert has_feature(operator, "payroll")


def test_scheduled_downgrade_and_paid_renewal(scenario):
    app, operator = scenario
    growth = PricingTier.query.filter_by(key="growth").one()
    invoice = billing.request_plan(operator, growth)
    billing.confirm_payment(invoice, invoice.amount, "cash")
    subscription = OperatorSubscription.query.one()
    original_end = subscription.current_period_end
    starter = PricingTier.query.filter_by(key="starter").one()
    assert billing.request_plan(operator, starter) is None
    assert operator.plan_tier == "growth"
    assert subscription.scheduled_tier_id == starter.id
    assert billing.run_jobs(today=original_end - timedelta(days=6)) == 1
    assert billing.run_jobs(today=original_end - timedelta(days=6)) == 0
    renewal = PlatformInvoice.query.filter_by(kind="renewal").one()
    billing.confirm_payment(renewal, renewal.amount, "bank")
    assert operator.plan_tier == "growth"
    billing.run_jobs(today=original_end + timedelta(days=1))
    assert operator.plan_tier == "starter"
    assert subscription.current_period_start == original_end + timedelta(days=1)


def test_paid_addons_and_enterprise_not_free(scenario, monkeypatch):
    app, operator = scenario
    starter = PricingTier.query.filter_by(key="starter").one()
    invoice = billing.request_plan(operator, starter)
    billing.confirm_payment(invoice, invoice.amount, "cash")
    from app.models import PlatformModule
    module = PlatformModule.query.filter_by(code="extra_storage").one()
    module.monthly_price = 100
    addon_invoice = billing.request_addon(operator, module, quantity=2)
    assert not has_feature(operator, "extra_storage")
    billing.confirm_payment(addon_invoice, addon_invoice.amount, "upi")
    assert has_feature(operator, "extra_storage")
    assert OperatorAddon.query.one().quantity == 2
    monkeypatch.setattr("app.services.entitlements.storage_used", lambda operator_id: 600 * 1024 * 1024)
    billing.validate_capacity(operator, billing.snapshot(starter))
    addon = OperatorAddon.query.one()
    addon.cancel_at_period_end = True
    with pytest.raises(ValueError, match="storage"):
        billing.validate_capacity(operator, billing.snapshot(starter))
    addon.cancel_at_period_end = False
    enterprise = PricingTier.query.filter_by(key="enterprise").one()
    enterprise.status = TierStatus.ACTIVE
    subscription = OperatorSubscription.query.one()
    subscription.negotiated_base_price = 5000
    invoice = billing.request_plan(operator, enterprise)
    billing.confirm_payment(invoice, invoice.amount, "bank")
    assert has_feature(operator, "payroll")
    assert not has_feature(operator, "white_label")


def test_tier_included_addon_is_granted_without_purchase(scenario):
    app, operator = scenario
    from app.models import PlatformModule
    white_label = PlatformModule.query.filter_by(code="white_label").one()
    white_label.monthly_price = 500
    starter = PricingTier.query.filter_by(key="starter").one()
    invoice = billing.request_plan(operator, starter)
    billing.confirm_payment(invoice, invoice.amount, "cash")
    assert not has_feature(operator, "white_label")

    starter.module_catalog.append(white_label)
    db.session.flush()
    assert not has_feature(operator, "white_label"), "existing contracts keep their stored terms"

    subscription = OperatorSubscription.query.one()
    subscription.pricing_snapshot = json.dumps(billing.snapshot(starter, subscription))
    assert has_feature(operator, "white_label")
    with pytest.raises(ValueError, match="already included"):
        billing.request_addon(operator, white_label)


def test_payment_rejects_invalid_and_preserves_suspension(scenario):
    app, operator = scenario
    invoice = billing.request_plan(operator, PricingTier.query.filter_by(key="starter").one())
    for amount, method in ((-1, "bank"), (1, "gateway"), (invoice.amount + 1, "upi")):
        with pytest.raises(ValueError):
            billing.confirm_payment(invoice, amount, method)
    operator.status = OperatorStatus.SUSPENDED
    billing.confirm_payment(invoice, invoice.amount, "bank")
    assert operator.status == OperatorStatus.SUSPENDED


def test_igst_for_different_states_and_cycle_switch(scenario):
    app, operator = scenario
    operator.gst_state = "27"
    starter = PricingTier.query.filter_by(key="starter").one()
    invoice = billing.request_plan(operator, starter)
    assert invoice.igst == Decimal("180")
    assert invoice.cgst == invoice.sgst == 0
    billing.confirm_payment(invoice, invoice.amount, "cash")
    assert billing.request_plan(operator, starter, "annual") is None
    assert OperatorSubscription.query.one().scheduled_billing_cycle == "annual"


def _user(operator, role, email):
    from app.models import User
    user = User(operator_id=operator.id if operator else None, role=role, email=email, full_name=role.value,
                is_active=True)
    user.set_password("LocalTest123!")
    db.session.add(user)
    db.session.commit()
    return user


def _client(app, user, host="billing.hub1z.com"):
    from flask import g
    g.pop("_login_user", None)
    client = app.test_client()
    response = client.post("/auth/login", data={"email": user.email, "password": "LocalTest123!"},
                           headers={"Host": host})
    assert response.status_code == 302
    return client


@pytest.mark.parametrize("role", ["super_admin", "manager", "location_manager"])
def test_expired_trial_login_staff_banner_and_dismissal(scenario, role):
    from app.models import UserRole
    app, operator = scenario
    user = _user(operator, UserRole(role), f"{role}@hub1z.com")
    client = _client(app, user)
    headers = {"Host": "billing.hub1z.com"}
    response = client.get("/auth/change-password", headers=headers)
    assert b"data-billing-banner" in response.data
    assert b"Trial features and workspace access continue" in response.data
    client.post("/admin/hub1z-billing/banner/dismiss", data={"next": "/admin/attendance"}, headers=headers)
    assert b"data-billing-banner" not in client.get("/auth/change-password", headers=headers).data
    client.get("/auth/logout", headers=headers)
    client.post("/auth/login", data={"email": user.email, "password": "LocalTest123!"}, headers=headers)
    assert b"data-billing-banner" in client.get("/auth/change-password", headers=headers).data
    assert client.get("/admin/hub1z-billing/plans", headers=headers).status_code == (200 if role == "super_admin" else 403)


@pytest.mark.parametrize("role", ["company_admin", "employee", "individual"])
def test_customers_have_no_banner_or_plan_picker(scenario, role):
    from app.models import UserRole
    app, operator = scenario
    user = _user(operator, UserRole(role), f"{role}@hub1z.com")
    client = _client(app, user)
    headers = {"Host": "billing.hub1z.com"}
    assert b"data-billing-banner" not in client.get("/auth/change-password", headers=headers).data
    assert client.get("/admin/hub1z-billing/plans", headers=headers).status_code == 403


def test_owner_selection_and_platform_payment_routes(scenario, monkeypatch):
    from app.models import UserRole
    from app.services import owner_details
    monkeypatch.setattr(owner_details, "status", lambda operator: {"complete": True})
    app, operator = scenario
    owner = _user(operator, UserRole.SUPER_ADMIN, "owner@hub1z.com")
    platform = _user(None, UserRole.PLATFORM_OWNER, "platform@hub1z.com")
    client = _client(app, owner)
    headers = {"Host": "billing.hub1z.com"}
    tier = PricingTier.query.filter_by(key="starter").one()
    assert client.get("/admin/hub1z-billing/plans", headers=headers).status_code == 200
    client.post("/admin/hub1z-billing/plans", data={"tier_id": tier.id, "cycle": "monthly"}, headers=headers)
    invoice = PlatformInvoice.query.one()
    assert invoice.status == PlatformInvoiceStatus.ISSUED
    assert has_feature(operator, "payroll")
    platform_client = _client(app, platform, "hub1z.com")
    assert platform_client.get("/platform/finance", headers={"Host": "hub1z.com"}).status_code == 200
    response = platform_client.post(f"/platform/finance/invoices/{invoice.id}/payment", data={
        "amount": "500", "method": "bank", "reference": "LOCAL", "request_key": "a" * 32},
        headers={"Host": "hub1z.com"})
    assert response.status_code == 302
    assert invoice.status == PlatformInvoiceStatus.ISSUED
    from flask import g
    g.pop("_login_user", None)
    assert "680 outstanding" in client.get("/admin/hub1z-billing", headers=headers).get_data(as_text=True)
    g.pop("_login_user", None)
    platform_client.post(f"/platform/finance/invoices/{invoice.id}/payment", data={
        "amount": "680", "method": "bank", "request_key": "c" * 32}, headers={"Host": "hub1z.com"})
    assert invoice.status == PlatformInvoiceStatus.PAID
    g.pop("_login_user", None)
    assert client.get("/admin/payroll", headers=headers).status_code == 403
    assert client.get("/admin/attendance", headers=headers).status_code == 200
    assert client.get("/admin/leads/export.csv", headers=headers).status_code == 403
    for path in ("/admin/expenses", "/admin/reports/people", "/admin/reports/heatmap", "/admin/audit-log.csv",
                 "/admin/attendance/export.csv", "/admin/attendance/screen/1", "/admin/attendance/qr/1.png?rotating=1"):
        assert client.get(path, headers=headers).status_code == 403
    assert client.get("/admin/attendance/qr", headers=headers).status_code == 200


def test_partial_payment_idempotency_and_overage(scenario):
    from app.models import OperatorUsageSnapshot
    app, operator = scenario
    starter = PricingTier.query.filter_by(key="starter").one()
    starter.included_active_contracted_seats = 10
    starter.additional_seat_rate = 5
    invoice = billing.request_plan(operator, starter, today=date.today() - timedelta(days=40))
    billing.confirm_payment(invoice, 500, "cash", request_key="b" * 32)
    billing.confirm_payment(invoice, 500, "cash", request_key="b" * 32)
    assert billing.payment_total(invoice) == 500
    billing.confirm_payment(invoice, 680, "bank")
    subscription = OperatorSubscription.query.one()
    db.session.add(OperatorUsageSnapshot(operator_id=operator.id, recorded_on=subscription.current_period_end,
                                         active_contracted_seats=15, active_locations=1))
    db.session.commit()
    billing.run_jobs()
    billing.run_jobs()
    overage = PlatformInvoice.query.filter_by(kind="usage").one()
    assert overage.subtotal == 25
    assert overage.activation is None


def test_annual_plan_monthly_arrears_and_snapshot_freeze(scenario):
    from app.models import OperatorUsageSnapshot
    app, operator = scenario
    starter = PricingTier.query.filter_by(key="starter").one()
    starter.included_active_contracted_seats = 10
    starter.additional_seat_rate = 5
    invoice = billing.request_plan(operator, starter, "annual", today=date.today() - timedelta(days=45))
    billing.confirm_payment(invoice, invoice.amount, "cash")
    subscription = OperatorSubscription.query.one()
    end = subscription.current_period_start + timedelta(days=20)
    db.session.add(OperatorUsageSnapshot(operator_id=operator.id, recorded_on=end,
                                         active_contracted_seats=15, active_locations=1))
    starter.monthly_price = 9000
    db.session.commit()
    billing.run_jobs()
    assert PlatformInvoice.query.filter_by(kind="usage").one().subtotal == 25
    assert billing.base_price(billing.paid_terms(subscription), "annual") == 12000
    assert subscription.current_period_end > date.today()


def test_quotas_website_enquiry_and_paid_storage(scenario):
    import io
    from app.models import Lead, PlatformModule, UserRole
    from app.services.operator_quotas import QuotaExceeded
    from app.services.storage import storage_service
    from app.services.entitlements import storage_limit_mb
    app, operator = scenario
    starter = PricingTier.query.filter_by(key="starter").one()
    starter.max_staff_users = 1
    starter.max_open_leads = 1
    starter.storage_mb = 1
    invoice = billing.request_plan(operator, starter)
    billing.confirm_payment(invoice, invoice.amount, "cash")
    db.session.commit()
    _user(operator, UserRole.SUPER_ADMIN, "owner@billing.test")
    with pytest.raises(QuotaExceeded):
        _user(operator, UserRole.MANAGER, "manager@billing.test")
    db.session.rollback()
    db.session.add(Lead(operator_id=operator.id, name="Manual", source="Website"))
    db.session.commit()
    db.session.add(Lead(operator_id=operator.id, name="Public", is_website_enquiry=True))
    db.session.commit()
    db.session.add(Lead(operator_id=operator.id, name="Second manual"))
    with pytest.raises(QuotaExceeded):
        db.session.commit()
    db.session.rollback()
    response = app.test_client().post("/enquire", data={"name": "Website prospect", "email": "prospect@example.com"},
                                     headers={"Host": "billing.hub1z.com"})
    assert response.status_code == 302
    assert Lead.query.filter_by(is_website_enquiry=True).count() == 2
    with pytest.raises(QuotaExceeded):
        storage_service.upload(f"operators/{operator.id}/docs", "big.pdf", io.BytesIO(b"x" * (1024 * 1024 + 1)))
    module = PlatformModule.query.filter_by(code="extra_storage").one()
    module.monthly_price = 100
    addon_invoice = billing.request_addon(operator, module)
    billing.confirm_payment(addon_invoice, addon_invoice.amount, "bank")
    assert storage_limit_mb(operator) == 5121


def _paid_starter_with_addons(operator, units):
    from app.models import PlatformModule
    invoice = billing.request_plan(operator, PricingTier.query.filter_by(key="starter").one())
    billing.confirm_payment(invoice, invoice.amount, "cash")
    addons = {}
    for code, price in (("extra_storage", 100), ("white_label", 500), ("virtual_office", 300)):
        module = PlatformModule.query.filter_by(code=code).one()
        module.monthly_price = price
        addons[code] = module
    for code, quantity in units.items():
        addon_invoice = billing.request_addon(operator, addons[code], quantity)
        billing.confirm_payment(addon_invoice, addon_invoice.amount, "cash")
    return addons


def test_addon_units_reduce_cancel_and_keep_at_renewal(scenario):
    app, operator = scenario
    modules = _paid_starter_with_addons(operator, {"extra_storage": 3, "white_label": 1})
    end = OperatorSubscription.query.one().current_period_end
    assert billing.run_jobs(today=end - timedelta(days=6)) == 1
    renewal = PlatformInvoice.query.filter_by(kind="renewal").one()
    assert renewal.subtotal == Decimal("1800")
    storage = OperatorAddon.query.filter_by(module_id=modules["extra_storage"].id).one()
    white = OperatorAddon.query.filter_by(module_id=modules["white_label"].id).one()

    extra = billing.request_addon(operator, modules["virtual_office"], 1)
    billing.confirm_payment(extra, extra.amount, "cash")
    assert renewal.subtotal == Decimal("2100")

    billing.schedule_addon_renewal(operator, storage, 1)
    assert (storage.quantity, storage.renewing_quantity) == (3, 1)
    assert renewal.subtotal == Decimal("1900")
    billing.schedule_addon_renewal(operator, white, 0)
    assert white.cancel_at_period_end and renewal.subtotal == Decimal("1400")
    billing.schedule_addon_renewal(operator, white, None)
    assert not white.cancel_at_period_end and renewal.subtotal == Decimal("1900")
    billing.schedule_addon_renewal(operator, white, 0)
    assert renewal.amount == Decimal("1652.00") and len(renewal.activation["addons"]) == 2
    for units in (4, -1):
        with pytest.raises(ValueError, match="Choose between"):
            billing.schedule_addon_renewal(operator, storage, units)

    billing.confirm_payment(renewal, renewal.amount, "bank")
    with pytest.raises(ValueError, match="already paid"):
        billing.schedule_addon_renewal(operator, storage, None)
    billing.run_jobs(today=end + timedelta(days=1))
    assert (storage.quantity, storage.renewal_quantity, storage.paid_through) == (1, None, renewal.period_end)
    assert not white.active and not has_feature(operator, "white_label")
    assert has_feature(operator, "extra_storage")


def test_addon_renewal_routes_are_owner_only_and_operator_scoped(scenario):
    from app.models import Operator as OperatorModel, UserRole
    app, operator = scenario
    _paid_starter_with_addons(operator, {"extra_storage": 2})
    addon = OperatorAddon.query.one()
    other = OperatorModel(slug="other", name="Other", primary_domain="other.hub1z.com", status=OperatorStatus.TRIAL)
    db.session.add(other)
    db.session.commit()
    headers = {"Host": "billing.hub1z.com"}
    manager = _client(app, _user(operator, UserRole.MANAGER, "manager@hub1z.com"))
    assert manager.post(f"/admin/hub1z-billing/addons/{addon.id}/renewal", data={"change": "cancel"},
                        headers=headers).status_code == 403
    outsider = _client(app, _user(other, UserRole.SUPER_ADMIN, "owner@other.com"), "other.hub1z.com")
    assert outsider.post(f"/admin/hub1z-billing/addons/{addon.id}/renewal", data={"change": "cancel"},
                         headers={"Host": "other.hub1z.com"}).status_code == 404
    owner = _client(app, _user(operator, UserRole.SUPER_ADMIN, "owner@hub1z.com"))
    page = owner.get("/admin/hub1z-billing/plans", headers=headers).get_data(as_text=True)
    assert "Units at renewal" in page and "Cancel at renewal" in page
    owner.post(f"/admin/hub1z-billing/addons/{addon.id}/renewal", data={"quantity": "1"}, headers=headers)
    assert addon.renewal_quantity == 1
    assert "Reduces to 1 at renewal" in owner.get("/admin/hub1z-billing/plans", headers=headers).get_data(as_text=True)
    owner.post(f"/admin/hub1z-billing/addons/{addon.id}/renewal", data={"change": "cancel"}, headers=headers)
    assert addon.cancel_at_period_end
    owner.post(f"/admin/hub1z-billing/addons/{addon.id}/renewal", data={"change": "keep"}, headers=headers)
    assert addon.renewing_quantity == 2


def test_reported_payment_alerts_platform_billing_staff_and_emails_support(scenario, monkeypatch, caplog):
    import logging
    from flask import g
    from app.models import PlatformPaymentReport, UserRole
    app, operator = scenario
    caplog.set_level(logging.INFO)
    invoice = billing.request_plan(operator, PricingTier.query.filter_by(key="starter").one())
    db.session.commit()
    owner = _client(app, _user(operator, UserRole.SUPER_ADMIN, "owner@hub1z.com"))
    form = {"amount": "1180", "paid_on": date.today().isoformat(), "reference": "UTR-ALERT-1"}
    assert owner.post(f"/admin/hub1z-billing/invoices/{invoice.id}/report", data=form,
                      headers={"Host": "billing.hub1z.com"}).status_code == 302
    support = app.config["PLATFORM_SUPPORT_EMAIL"]
    assert support == "support@hub1z.com"
    assert f"to={support} subject=Payment reported: Billing" in caplog.text
    assert "UTR-ALERT-1" in caplog.text and "Amount reported" in caplog.text

    def broken(*args, **kwargs):
        raise RuntimeError("smtp down")
    monkeypatch.setattr("app.services.mail_service.send", broken)
    assert owner.post(f"/admin/hub1z-billing/invoices/{invoice.id}/report", data=form,
                      headers={"Host": "billing.hub1z.com"}).status_code == 302
    assert PlatformPaymentReport.query.count() == 1
    second = PlatformInvoice(operator_id=operator.id, number="MANUAL-1", period_start=date.today(),
                             period_end=date.today(), due_date=date.today(), amount=500, kind="manual",
                             status=PlatformInvoiceStatus.ISSUED)
    db.session.add(second)
    db.session.commit()
    assert owner.post(f"/admin/hub1z-billing/invoices/{second.id}/report", data=dict(form, amount="500"),
                      headers={"Host": "billing.hub1z.com"}).status_code == 302
    assert PlatformPaymentReport.query.filter_by(status="pending").count() == 2

    host = {"Host": "hub1z.com"}
    granted = _user(None, UserRole.PLATFORM_MANAGER, "billing-manager@hub1z.com")
    granted.set_platform_permissions(["billing", "leads"])
    denied = _user(None, UserRole.PLATFORM_MANAGER, "leads-manager@hub1z.com")
    denied.set_platform_permissions(["leads"])
    platform_owner = _user(None, UserRole.PLATFORM_OWNER, "platform@hub1z.com")
    db.session.commit()
    def fresh_request():
        # The fixture shares one app context, so per-request caches would leak between clients.
        g.pop("_login_user", None)
        g.pop("_nav_badges", None)

    for staff in (platform_owner, granted):
        client = _client(app, staff, "hub1z.com")
        fresh_request()
        dashboard = client.get("/platform/", headers=host).get_data(as_text=True)
        assert "Payments to confirm" in dashboard and "2 operator payments waiting for approval" in dashboard
        assert "Billing" in dashboard and "UTR-ALERT-1" in dashboard
        fresh_request()
        assert b"data-payment-notice" in client.get("/platform/attendance", headers=host).data
        fresh_request()
        finance = client.get("/platform/finance", headers=host).get_data(as_text=True)
        assert 'id="payment-reports"' in finance and "2 waiting for approval" in finance
    client = _client(app, denied, "hub1z.com")
    fresh_request()
    assert b"data-payment-notice" not in client.get("/platform/", headers=host).data
    fresh_request()
    assert b"data-payment-notice" not in client.get("/platform/attendance", headers=host).data


def test_duplicate_reports_for_a_paid_invoice_are_closed_not_double_counted(scenario):
    from app.models import PlatformPaymentReport, UserRole
    app, operator = scenario
    invoice = billing.request_plan(operator, PricingTier.query.filter_by(key="starter").one())
    reports = [PlatformPaymentReport(operator_id=operator.id, invoice_id=invoice.id, amount=invoice.amount,
                                     paid_on=date.today(), reference=f"UTR-{n}") for n in (1, 2)]
    db.session.add_all(reports)
    staff = _user(None, UserRole.PLATFORM_OWNER, "platform@hub1z.com")
    db.session.commit()
    client = _client(app, staff, "hub1z.com")
    host = {"Host": "hub1z.com"}
    client.post(f"/platform/finance/payment-reports/{reports[0].id}/accept", data={"method": "upi"}, headers=host)
    client.post(f"/platform/finance/payment-reports/{reports[1].id}/accept", data={"method": "upi"}, headers=host)
    assert invoice.status == PlatformInvoiceStatus.PAID
    assert [report.status for report in reports] == ["accepted", "rejected"]
    assert reports[1].platform_message == "This invoice was already paid."
    assert PlatformPayment.query.count() == 1


def test_all_outgoing_mail_is_redirected_except_hub1z_addresses(scenario, monkeypatch):
    from types import SimpleNamespace
    from app.services import mail_service
    app, operator = scenario
    sent = []
    monkeypatch.setattr(mail_service.mail, "send", sent.append)
    app.config.update(MAIL_SUPPRESS_SEND=False, MAIL_REDIRECT_TO="admin@hub1z.com", MAIL_REDIRECT_KEEP_DOMAINS="hub1z.com")
    lead = SimpleNamespace(name="Asha", email="asha@example.com", phone=None, interest=None)
    with app.test_request_context("/", headers={"Host": "billing.hub1z.com"}):
        mail_service.send("New enquiry", "owner@billing-space.example", "lead_enquiry", operator=operator, lead=lead)
        mail_service.send("New enquiry", "support@hub1z.com", "lead_enquiry", operator=operator, lead=lead)
        app.config["MAIL_REDIRECT_TO"] = ""
        mail_service.send("New enquiry", "owner@billing-space.example", "lead_enquiry", operator=operator, lead=lead)
    redirected, internal, normal = sent
    assert redirected.recipients == ["admin@hub1z.com"]
    assert redirected.subject == "[for owner@billing-space.example] New enquiry"
    assert redirected.body.startswith("Originally addressed to: owner@billing-space.example")
    assert redirected.extra_headers == {"X-Original-To": "owner@billing-space.example"}
    assert internal.recipients == ["support@hub1z.com"] and internal.subject == "New enquiry"
    assert normal.recipients == ["owner@billing-space.example"] and normal.subject == "New enquiry"


def test_hub1z_invoice_pdf_carries_the_logo(scenario):
    from app.services.pdf_docs import pdf_response, platform_invoice_context
    app, operator = scenario
    invoice = billing.request_plan(operator, PricingTier.query.filter_by(key="starter").one())
    db.session.commit()
    context = platform_invoice_context(invoice)
    assert context["logo"].startswith("data:image/png;base64,")
    with app.test_request_context("/"):
        response = pdf_response("pdf/document.html", "invoice.pdf", **context)
        response.direct_passthrough = False
        assert b"/Subtype /Image" in response.get_data()


@pytest.mark.skipif(not os.environ.get("RUN_POSTGRES_MIGRATION_TEST"), reason="Isolated PostgreSQL migration gate")
def test_postgres_rollout_upgrade_downgrade():
    app = create_app({"SQLALCHEMY_DATABASE_URI": os.environ.get("DATABASE_URL"), "MAIL_SUPPRESS_SEND": True})
    with app.app_context():
        ids = []
        for key, status in (("unpaid", OperatorStatus.ACTIVE), ("paid", OperatorStatus.ACTIVE),
                            ("suspended", OperatorStatus.SUSPENDED)):
            operator = Operator(slug=f"migration-{key}", name=f"Migration {key}", status=status,
                                primary_domain=f"migration-{key}.localhost", plan_tier="starter")
            db.session.add(operator)
            db.session.flush()
            ids.append(operator.id)
            if key == "paid":
                db.session.add(PlatformInvoice(operator_id=operator.id, number="MIGRATION-PAID", amount=100,
                    period_start=date.today(), period_end=date.today() + timedelta(days=29),
                    due_date=date.today(), status=PlatformInvoiceStatus.PAID))
        db.session.commit()
        db.session.remove()
        runner = app.test_cli_runner()
        result = runner.invoke(args=["db", "downgrade", "b8d3f6a2c914"])
        assert result.exit_code == 0, result.output
        result = runner.invoke(args=["db", "upgrade"])
        assert result.exit_code == 0, result.output
        unpaid, paid, suspended = [db.session.get(Operator, operator_id) for operator_id in ids]
        assert unpaid.status == OperatorStatus.TRIAL
        assert unpaid.trial_ends_at > datetime.utcnow()
        assert paid.status == OperatorStatus.ACTIVE
        assert suspended.status == OperatorStatus.SUSPENDED
        assert OperatorSubscription.query.filter_by(operator_id=paid.id).one().status == "active"
        assert OperatorSubscription.query.filter_by(operator_id=unpaid.id).one().status == "trial"
        assert PlatformInvoice.query.filter_by(number="MIGRATION-PAID").one().amount == 100
        from sqlalchemy import delete
        db.session.execute(delete(PlatformInvoice).where(PlatformInvoice.operator_id.in_(ids)))
        db.session.execute(delete(OperatorSubscription).where(OperatorSubscription.operator_id.in_(ids)))
        db.session.execute(delete(Operator).where(Operator.id.in_(ids)))
        db.session.commit()