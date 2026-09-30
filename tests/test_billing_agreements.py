"""Agreements and invoicing: GST split, advance billing, deposits, late fees, revisions, notice and exit."""
import os
os.environ.setdefault("FLASK_ENV", "testing")

from datetime import date
from decimal import Decimal

import pytest

from app import create_app
from app.extensions import db
from app.models import (
    BillingSettings, Company, CompanyStatus, DepositEntry, Invoice, InvoiceStatus, Operator, OperatorStatus,
    PlanScope, PlanType, BillingCycle, PricingPlan, RateRevision, Subscription, SubscriptionStatus, TaxRate,
    User, UserRole,
)
from app.services import billing_service as bs
from app.services import gst


def _app():
    app = create_app({"SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:", "WTF_CSRF_ENABLED": False,
                      "MAIL_SUPPRESS_SEND": True, "STORAGE_BACKEND": "local",
                      "LOCAL_STORAGE_DIR": "./var/test-uploads"})
    with app.app_context():
        db.create_all()
    return app


def _seed(app):
    """A Tamil Nadu operator with a local company (TN) and an out-of-state company (Karnataka)."""
    with app.app_context():
        op = Operator(slug="adyarspace", name="Adyar Space", primary_domain="adyarspace.hub1z.com",
                      status=OperatorStatus.ACTIVE, gstin="33AAAAA0000A1Z5", gst_state="33",
                      company_legal_name="Adyar Space LLP", currency_code="INR")
        db.session.add(op)
        db.session.flush()
        admin = User(operator_id=op.id, email="admin@adyarspace.com", full_name="Admin",
                     role=UserRole.SUPER_ADMIN, is_active=True)
        admin.set_password("AdminPass123!")
        db.session.add(admin)
        local = Company(operator_id=op.id, name="Local Co", billing_email="a@local.example",
                        status=CompanyStatus.ACTIVE, max_employees=10, gst_state="33",
                        tax_id="33BBBBB1111B1Z5", pan="BBBBB1111B")
        far = Company(operator_id=op.id, name="Far Co", billing_email="a@far.example",
                      status=CompanyStatus.ACTIVE, max_employees=10, gst_state="29")
        plan = PricingPlan(operator_id=op.id, name="Dedicated Desk", scope=PlanScope.COMPANY_STANDARD,
                           plan_type=PlanType.DEDICATED_DESK, billing_cycle=BillingCycle.MONTHLY,
                           base_price=22000, max_locations=1)
        db.session.add_all([local, far, plan])
        db.session.commit()
        return {"op": op.id, "local": local.id, "far": far.id, "plan": plan.id}


def _sub(ids, company="local", start=date(2026, 1, 1), qty=1, price=22000, **terms):
    sub = Subscription(operator_id=ids["op"], plan_id=ids["plan"], company_id=ids[company], quantity=qty,
                       unit_price=Decimal(price), start_date=start, status=SubscriptionStatus.ACTIVE)
    db.session.add(sub)
    db.session.flush()
    bs.apply_default_terms(sub)
    for k, v in terms.items():
        setattr(sub, k, v)
    db.session.commit()
    return sub


def _invoices(sub):
    return Invoice.query.filter_by(subscription_id=sub.id).order_by(Invoice.period_start, Invoice.id).all()


# ---------------------------------------------------------------- GST --

def test_gst_split_same_state_and_other_state():
    assert gst.split_gst(Decimal("1800"), "33", "33") == (Decimal("900.00"), Decimal("900.00"), Decimal("0.00"))
    assert gst.split_gst(Decimal("1800"), "33", "29") == (Decimal("0.00"), Decimal("0.00"), Decimal("1800.00"))
    # unknown buyer state: treated as local
    assert gst.split_gst(Decimal("1800"), "33", None)[2] == Decimal("0.00")
    # odd paise never go missing
    cgst, sgst, igst = gst.split_gst(Decimal("0.01"), "33", "33")
    assert cgst + sgst == Decimal("0.01")


def test_state_taken_from_gstin_when_not_set():
    assert gst.state_of(None, "29ABCDE1234F1Z5") == "29"
    assert gst.state_of("", "not-a-gstin") is None


def test_rate_depends_on_charge_and_date():
    app = _app()
    ids = _seed(app)
    with app.app_context():
        op = db.session.get(Operator, ids["op"])
        db.session.add_all([
            TaxRate(operator_id=op.id, charge_type="plan", rate=18, effective_from=date(2020, 1, 1), sac_code="997212"),
            TaxRate(operator_id=op.id, charge_type="plan", rate=12, effective_from=date(2026, 4, 1)),
        ])
        db.session.commit()
        assert gst.rate_for(op, "plan", date(2026, 3, 31)) == (Decimal("18.00"), "997212")
        assert gst.rate_for(op, "plan", date(2026, 4, 1))[0] == Decimal("12.00")
        assert gst.rate_for(op, "deposit", date(2026, 4, 1))[0] == Decimal("0.00")
        assert gst.rate_for(op, "addon", date(2026, 4, 1))[0] == Decimal(op.default_tax_rate)


# ------------------------------------------------------ monthly invoices --

def test_monthly_invoice_is_advance_with_cgst_sgst_and_due_day():
    app = _app()
    ids = _seed(app)
    with app.app_context():
        sub = _sub(ids, qty=2)
        made = bs.run_monthly_billing(today=date(2026, 1, 1))
        assert len(made) == 1
        inv = made[0]
        assert (inv.subtotal, inv.tax_amount) == (Decimal("44000.00"), Decimal("7920.00"))
        assert (inv.cgst_amount, inv.sgst_amount, inv.igst_amount) == (Decimal("3960.00"), Decimal("3960.00"), 0)
        assert inv.total_amount == Decimal("51920.00")
        assert inv.due_date == date(2026, 1, 5)
        assert (inv.period_start, inv.period_end) == (date(2026, 1, 1), date(2026, 1, 31))
        assert (inv.seller_gstin, inv.buyer_gstin, inv.buyer_pan) == ("33AAAAA0000A1Z5", "33BBBBB1111B1Z5", "BBBBB1111B")
        # running again changes nothing
        assert bs.run_monthly_billing(today=date(2026, 1, 2)) == []
        assert len(_invoices(sub)) == 1


def test_other_state_company_pays_igst():
    app = _app()
    ids = _seed(app)
    with app.app_context():
        _sub(ids, company="far", qty=2)
        inv = bs.run_monthly_billing(today=date(2026, 1, 1))[0]
        assert (inv.cgst_amount, inv.sgst_amount, inv.igst_amount) == (0, 0, Decimal("7920.00"))


def test_invoices_wait_for_the_configured_issue_day():
    app = _app()
    ids = _seed(app)
    with app.app_context():
        _sub(ids)
        BillingSettings.for_operator(ids["op"]).invoice_issue_day = 3
        db.session.commit()
        assert bs.run_monthly_billing(today=date(2026, 1, 2)) == []
        assert len(bs.run_monthly_billing(today=date(2026, 1, 3))) == 1


def test_first_partial_month_is_prorated():
    app = _app()
    ids = _seed(app)
    with app.app_context():
        _sub(ids, start=date(2026, 1, 21), price=31000)
        inv = bs.run_monthly_billing(today=date(2026, 1, 21))[0]
        assert inv.subtotal == Decimal("11000.00")
        assert "11 of 31 days" in inv.line_items[0].description


def test_price_that_includes_gst_is_split_out():
    app = _app()
    ids = _seed(app)
    with app.app_context():
        _sub(ids, price=11800, price_includes_tax=True)
        inv = bs.run_monthly_billing(today=date(2026, 1, 1))[0]
        assert (inv.subtotal, inv.tax_amount, inv.total_amount) == (Decimal("10000.00"), Decimal("1800.00"),
                                                                    Decimal("11800.00"))


def test_agreement_not_running_yet_or_ended_gets_no_invoice():
    app = _app()
    ids = _seed(app)
    with app.app_context():
        _sub(ids, start=date(2026, 3, 1))
        assert bs.run_monthly_billing(today=date(2026, 1, 1)) == []
        assert len(bs.run_monthly_billing(today=date(2026, 3, 1))) == 1


# ------------------------------------------------------------- deposit --

def test_deposit_invoice_has_no_gst_and_is_held_once_paid():
    app = _app()
    ids = _seed(app)
    with app.app_context():
        sub = _sub(ids)
        assert sub.deposit_amount == Decimal("66000.00")          # 3 x 22,000
        inv = bs.create_deposit_invoice(sub, today=date(2026, 1, 1))
        db.session.commit()
        assert (inv.tax_amount, inv.total_amount) == (0, Decimal("66000.00"))
        assert bs.create_deposit_invoice(sub, today=date(2026, 1, 1)) is None   # only once
        assert bs.deposit_balance(sub) == 0
        inv.amount_paid, inv.status = inv.total_amount, InvoiceStatus.PAID
        bs.after_payment(inv)
        bs.after_payment(inv)                                                    # not counted twice
        db.session.commit()
        assert bs.deposit_balance(sub) == Decimal("66000.00")
        bs.record_deposit(sub, "deduction", 6000, date(2026, 8, 1), "Damage")
        bs.record_deposit(sub, "refund", 30000, date(2026, 8, 10))
        assert bs.deposit_balance(sub) == Decimal("30000.00")
        with pytest.raises(bs.BillingError):
            bs.record_deposit(sub, "refund", 30000.01, date(2026, 8, 11))


# ----------------------------------------------------------- late fees --

def test_per_day_late_fee_is_billed_on_the_next_invoice_and_never_twice():
    app = _app()
    ids = _seed(app)
    with app.app_context():
        sub = _sub(ids, late_fee_mode="per_day", late_fee_value=Decimal("100"))
        jan = bs.run_monthly_billing(today=date(2026, 1, 1))[0]
        feb = bs.run_monthly_billing(today=date(2026, 2, 1))[0]
        fee = [li for li in feb.line_items if li.line_type == "late_fee"]
        assert len(fee) == 1 and fee[0].amount == Decimal("2700.00")     # due 5 Jan, 27 days to 1 Feb
        assert fee[0].tax_rate == Decimal("18.00")
        assert jan.late_fee_charged_through == date(2026, 2, 1)
        mar = bs.run_monthly_billing(today=date(2026, 3, 1))[0]
        jan_fee = [li for li in mar.line_items if li.line_type == "late_fee" and jan.number in li.description]
        assert len(jan_fee) == 1 and jan_fee[0].amount == Decimal("2800.00")  # only 1 Feb to 1 Mar


def test_interest_late_fee_and_grace_days():
    app = _app()
    ids = _seed(app)
    with app.app_context():
        _sub(ids, late_fee_mode="interest", late_fee_value=Decimal("12"), late_fee_grace_days=3)
        jan = bs.run_monthly_billing(today=date(2026, 1, 1))[0]
        feb = bs.run_monthly_billing(today=date(2026, 2, 1))[0]
        fee = [li for li in feb.line_items if li.line_type == "late_fee"][0]
        days = (date(2026, 2, 1) - date(2026, 1, 8)).days               # due 5 Jan + 3 grace days
        assert fee.amount == gst.money(Decimal(jan.total_amount) * 12 / 100 * days / 365)


def test_paid_invoices_and_no_late_fee_setting_add_nothing():
    app = _app()
    ids = _seed(app)
    with app.app_context():
        sub = _sub(ids, late_fee_mode="per_day", late_fee_value=Decimal("100"))
        jan = bs.run_monthly_billing(today=date(2026, 1, 1))[0]
        jan.amount_paid, jan.status = jan.total_amount, InvoiceStatus.PAID
        db.session.commit()
        feb = bs.run_monthly_billing(today=date(2026, 2, 1))[0]
        assert [li.line_type for li in feb.line_items] == ["plan"]
        sub.late_fee_mode = "none"
        db.session.commit()
        mar = bs.run_monthly_billing(today=date(2026, 3, 1))[0]
        assert [li.line_type for li in mar.line_items] == ["plan"]


# --------------------------------------------------------- escalation --

def test_yearly_increase_is_proposed_early_and_billed_only_after_confirmation():
    app = _app()
    ids = _seed(app)
    with app.app_context():
        sub = _sub(ids)                                                  # 10% after 11 months -> 1 Dec 2026
        assert bs.propose_revisions(today=date(2026, 10, 31)) == 0
        assert bs.propose_revisions(today=date(2026, 11, 1)) == 1
        assert bs.propose_revisions(today=date(2026, 11, 2)) == 0        # not proposed twice
        rev = RateRevision.query.one()
        assert (rev.effective_from, rev.old_unit_price, rev.new_unit_price) == (
            date(2026, 12, 1), Decimal("22000.00"), Decimal("24200.00"))
        # nothing changes until the operator confirms
        assert bs.run_monthly_billing(target_month=date(2026, 12, 1))[0].subtotal == Decimal("22000.00")
        bs.decide_revision(rev, True, None, percent=5)                   # operator negotiates 5% instead
        db.session.commit()
        assert bs.effective_unit_price(sub, date(2026, 11, 30)) == Decimal("22000")
        jan = bs.run_monthly_billing(target_month=date(2027, 1, 1))[0]
        assert jan.subtotal == Decimal("23100.00")
        with pytest.raises(bs.BillingError):
            bs.decide_revision(rev, True, None)                          # already decided


def test_dismissed_increase_keeps_price_and_next_one_is_a_year_later():
    app = _app()
    ids = _seed(app)
    with app.app_context():
        sub = _sub(ids)
        bs.propose_revisions(today=date(2026, 11, 1))
        bs.decide_revision(RateRevision.query.one(), False, None)
        db.session.commit()
        assert bs.effective_unit_price(sub, date(2027, 6, 1)) == Decimal("22000")
        assert bs.propose_revisions(today=date(2027, 10, 31)) == 0
        assert bs.propose_revisions(today=date(2027, 11, 1)) == 1
        assert RateRevision.query.filter_by(status="proposed").one().effective_from == date(2027, 12, 1)


def test_no_increase_when_percent_is_zero():
    app = _app()
    ids = _seed(app)
    with app.app_context():
        _sub(ids, escalation_percent=Decimal("0"))
        assert bs.propose_revisions(today=date(2027, 1, 1)) == 0


# ------------------------------------------------------ notice and exit --

def test_notice_inside_lock_in_charges_the_remaining_lock_in_fees():
    app = _app()
    ids = _seed(app)
    with app.app_context():
        sub = _sub(ids)                                                  # lock-in to 1 Jul, 3 months' notice
        result = bs.give_notice(sub, date(2026, 2, 1))
        db.session.commit()
        assert sub.terminate_on == date(2026, 5, 1)
        assert result["months"] == 2                                     # May and June
        inv = result["early_exit_invoice"]
        assert (inv.subtotal, inv.tax_amount) == (Decimal("44000.00"), Decimal("7920.00"))
        assert inv.line_items[0].line_type == "early_exit"
        with pytest.raises(bs.BillingError):
            bs.give_notice(sub, date(2026, 2, 2))


def test_notice_can_forfeit_the_deposit_instead():
    app = _app()
    ids = _seed(app)
    with app.app_context():
        sub = _sub(ids, early_exit_rule="forfeit_deposit")
        bs.record_deposit(sub, "received", 66000, date(2026, 1, 1))
        result = bs.give_notice(sub, date(2026, 2, 1))
        db.session.commit()
        assert result["early_exit_invoice"] is None
        assert result["forfeited"] == Decimal("66000.00")
        assert bs.deposit_balance(sub) == 0


def test_notice_after_the_lock_in_costs_nothing_and_billing_stops_at_the_end_date():
    app = _app()
    ids = _seed(app)
    with app.app_context():
        sub = _sub(ids)
        result = bs.give_notice(sub, date(2026, 7, 1))                   # ends 1 Oct, lock-in was over
        db.session.commit()
        assert result["early_exit_invoice"] is None and result["months"] == 0
        assert len(bs.run_monthly_billing(target_month=date(2026, 9, 1))) == 1
        assert bs.run_monthly_billing(target_month=date(2026, 10, 1)) == []
        assert bs.end_terminated_subscriptions(today=date(2026, 9, 30)) == 0
        assert bs.end_terminated_subscriptions(today=date(2026, 10, 1)) == 1
        db.session.refresh(sub)
        assert (sub.status, sub.end_date) == (SubscriptionStatus.EXPIRED, date(2026, 10, 1))


def test_last_partial_month_is_prorated_to_the_end_date():
    app = _app()
    ids = _seed(app)
    with app.app_context():
        sub = _sub(ids, price=31000)
        bs.give_notice(sub, date(2026, 7, 15))                           # ends 15 Oct
        db.session.commit()
        inv = bs.run_monthly_billing(target_month=date(2026, 10, 1))[0]
        assert inv.subtotal == Decimal("14000.00")                       # 14 of 31 days


# ------------------------------------------------------------- screens --

def _login(client):
    return client.post("/auth/login", data={"email": "admin@adyarspace.com", "password": "AdminPass123!"})


def test_subscribing_records_terms_and_raises_the_deposit_invoice():
    app = _app()
    ids = _seed(app)
    c = app.test_client()
    _login(c)
    r = c.post(f"/admin/companies/{ids['local']}/subscriptions/new", data={
        "plan_id": ids["plan"], "quantity": 2, "start_date": "2026-01-01",
        "term_months": 11, "lock_in_months": 6, "notice_months": 2, "due_day": 7, "deposit_refund_days": 20,
        "escalation_percent": "8", "escalation_after_months": 12, "late_fee_mode": "per_day", "late_fee_value": "50",
        "late_fee_grace_days": 3, "early_exit_rule": "forfeit_deposit", "deposit_months": 2,
    }, follow_redirects=False)
    assert r.status_code == 302
    with app.app_context():
        sub = Subscription.query.filter_by(company_id=ids["local"]).one()
        assert (sub.notice_months, sub.due_day, sub.early_exit_rule) == (2, 7, "forfeit_deposit")
        assert (sub.late_fee_mode, sub.late_fee_value, sub.late_fee_grace_days) == ("per_day", Decimal("50"), 3)
        assert sub.escalation_percent == Decimal("8")
        assert sub.deposit_amount == Decimal("88000.00")                 # 2 months x 2 seats x 22,000
        dep = Invoice.query.filter_by(subscription_id=sub.id).one()
        assert (dep.total_amount, dep.tax_amount) == (Decimal("88000.00"), 0)


def test_subscribing_without_terms_uses_the_operator_defaults():
    app = _app()
    ids = _seed(app)
    with app.app_context():
        st = BillingSettings.for_operator(ids["op"])
        st.notice_months, st.deposit_months = 1, 1
        db.session.commit()
    c = app.test_client()
    _login(c)
    r = c.post(f"/admin/companies/{ids['local']}/subscriptions/new",
               data={"plan_id": ids["plan"], "quantity": 1, "start_date": "2026-01-01"}, follow_redirects=False)
    assert r.status_code == 302
    with app.app_context():
        sub = Subscription.query.one()
        assert (sub.notice_months, sub.deposit_amount) == (1, Decimal("22000.00"))


def test_paying_the_deposit_invoice_on_screen_puts_it_on_the_ledger():
    app = _app()
    ids = _seed(app)
    c = app.test_client()
    _login(c)
    c.post(f"/admin/companies/{ids['local']}/subscriptions/new",
           data={"plan_id": ids["plan"], "quantity": 1, "start_date": "2026-01-01"})
    with app.app_context():
        sub = Subscription.query.one()
        inv = Invoice.query.one()
        sub_id, inv_id, total = sub.id, inv.id, inv.total_amount
    r = c.post(f"/admin/invoices/{inv_id}/payments/new",
               data={"amount": str(total), "method": "upi", "reference": "X1", "paid_at": "2026-01-02"})
    assert r.status_code == 302
    with app.app_context():
        assert bs.deposit_balance(db.session.get(Subscription, sub_id)) == Decimal("66000.00")
    r = c.post(f"/admin/subscriptions/{sub_id}/deposit",
               data={"entry_type": "refund", "amount": "16000", "entry_date": "2026-09-01", "note": "Part"})
    assert r.status_code == 302
    with app.app_context():
        assert bs.deposit_balance(db.session.get(Subscription, sub_id)) == Decimal("50000.00")
    page = c.get(f"/admin/subscriptions/{sub_id}/agreement")
    assert page.status_code == 200 and b"Security deposit" in page.data and b"50,000" in page.data


def test_agreement_page_notice_and_revision_actions():
    app = _app()
    ids = _seed(app)
    with app.app_context():
        sub = _sub(ids)
        sub_id = sub.id
        bs.propose_revisions(today=date(2026, 11, 1))
        rev_id = RateRevision.query.one().id
    c = app.test_client()
    _login(c)
    base = f"/admin/subscriptions/{sub_id}"
    assert b"Yearly increases" in c.get(base + "/agreement").data
    assert c.post(f"{base}/revisions/{rev_id}/confirm", data={"percent": "6"}).status_code == 302
    assert c.post(f"{base}/notice", data={"notice_date": "2026-02-01"}).status_code == 302
    with app.app_context():
        rev = db.session.get(RateRevision, rev_id)
        assert (rev.status, rev.new_unit_price) == ("confirmed", Decimal("23320.00"))
        sub = db.session.get(Subscription, sub_id)
        assert sub.terminate_on == date(2026, 5, 1)
        assert Invoice.query.filter_by(subscription_id=sub_id).count() == 1     # the early exit invoice
    assert b"2026-05-01" in c.get(base + "/agreement").data


def test_billing_settings_page_saves_defaults_tax_details_and_rates():
    app = _app()
    ids = _seed(app)
    c = app.test_client()
    _login(c)
    assert c.get("/admin/billing/settings").status_code == 200
    assert c.post("/admin/billing/settings/terms", data={
        "invoice_issue_day": 2, "due_day": 9, "late_fee_mode": "interest", "late_fee_value": "18",
        "late_fee_grace_days": 5, "term_months": 12, "lock_in_months": 6, "notice_months": 2, "deposit_months": 2,
        "deposit_refund_days": 30, "escalation_percent": "7", "escalation_after_months": 12,
        "early_exit_rule": "forfeit_deposit",
    }).status_code == 302
    assert c.post("/admin/billing/settings/tax-details", data={
        "company_legal_name": "Adyar Space LLP", "gstin": "33aaaaa0000a1z5", "pan": "aaaaa0000a", "gst_state": "33",
    }).status_code == 302
    assert c.post("/admin/billing/settings/tax-rates", data={
        "charge_type": "plan", "rate": "12", "sac_code": "997212", "effective_from": "2026-04-01",
    }).status_code == 302
    with app.app_context():
        st = BillingSettings.for_operator(ids["op"])
        assert (st.invoice_issue_day, st.due_day, st.late_fee_mode, st.late_fee_value) == (2, 9, "interest", Decimal("18"))
        assert (st.deposit_months, st.early_exit_rule) == (2, "forfeit_deposit")
        op = db.session.get(Operator, ids["op"])
        assert (op.gstin, op.pan) == ("33AAAAA0000A1Z5", "AAAAA0000A")
        assert TaxRate.query.filter_by(operator_id=ids["op"]).one().rate == Decimal("12")


def test_invoice_screen_and_pdf_show_the_gst_split_and_ids():
    app = _app()
    ids = _seed(app)
    with app.app_context():
        _sub(ids, qty=2)
        inv_id = bs.run_monthly_billing(today=date(2026, 1, 1))[0].id
    c = app.test_client()
    _login(c)
    page = c.get(f"/admin/invoices/{inv_id}").data
    assert b"CGST" in page and b"SGST" in page and b"33AAAAA0000A1Z5" in page and b"33BBBBB1111B1Z5" in page
    assert b"IGST" not in page


def test_manual_invoice_lines_carry_gst():
    app = _app()
    ids = _seed(app)
    c = app.test_client()
    _login(c)
    r = c.post("/admin/invoices/new", data={"company_id": ids["far"]}, follow_redirects=False)
    inv_id = int(r.headers["Location"].rstrip("/").split("/")[-1])
    c.post(f"/admin/invoices/{inv_id}/lines/add",
           data={"description": "Printing", "quantity": "2", "unit_price": "500"})
    c.post(f"/admin/invoices/{inv_id}/lines/add",
           data={"description": "Books", "quantity": "1", "unit_price": "100", "tax_rate": "0"})
    with app.app_context():
        inv = db.session.get(Invoice, inv_id)
        assert (inv.subtotal, inv.tax_amount, inv.total_amount) == (Decimal("1100.00"), Decimal("180.00"),
                                                                    Decimal("1280.00"))
        assert inv.igst_amount == Decimal("180.00")                      # Far Co is in another state


def test_scheduled_jobs_command_runs_the_agreement_jobs():
    app = _app()
    ids = _seed(app)
    with app.app_context():
        sub = _sub(ids)
        bs.give_notice(sub, date(2025, 1, 1))                            # already past its end date
        db.session.commit()
        assert bs.run_agreement_jobs(today=date(2026, 6, 1))["ended"] == 1
