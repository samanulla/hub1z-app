"""New subscriptions raise draft invoices; the operator sends them, or turns on automatic sending."""
import os
from datetime import date
from decimal import Decimal

os.environ.setdefault("FLASK_ENV", "testing")

from app.models import Invoice, Subscription
from app.services import billing_service
from tests.test_subscription_packages import _setup, _subscribe


def test_new_subscription_invoices_wait_as_drafts_until_sent():
    app, client, ids = _setup()
    assert _subscribe(client, ids, plan_id=ids["office_plan"], new_space_code="CABIN-4",
                      deposit_months=1).status_code == 302
    with app.app_context():
        sub = Subscription.query.filter_by(company_id=ids["company"]).one()
        sub_id = sub.id
        assert sub.auto_send_invoices is False and sub.prorate_partial is True
        draft = billing_service.generate_invoice_for_subscription(sub, date(2026, 2, 1), date(2026, 2, 28))
        assert draft.status.value == "draft"
        assert {i.status.value for i in Invoice.query.filter_by(subscription_id=sub_id)} == {"draft"}
    assert client.post("/admin/invoices/issue-drafts").status_code == 302
    with app.app_context():
        assert {i.status.value for i in Invoice.query.filter_by(subscription_id=sub_id)} == {"issued"}


def test_auto_send_issues_invoices_and_full_month_option_skips_proration():
    app, client, ids = _setup()
    _subscribe(client, ids, plan_id=ids["office_plan"], new_space_code="CABIN-4", start_date="2026-02-15",
               auto_send_invoices="1", prorate_partial="0")
    with app.app_context():
        sub = Subscription.query.filter_by(company_id=ids["company"]).one()
        assert sub.auto_send_invoices is True and sub.prorate_partial is False
        made = billing_service.run_monthly_billing(target_month=date(2026, 2, 1), today=date(2026, 2, 15))
        invoice = next(i for i in made if i.subscription_id == sub.id)
        assert invoice.status.value == "issued"
        assert Decimal(invoice.line_items[0].unit_price) == Decimal("30000")  # not prorated


def test_free_rooms_are_limited_to_the_plans_size():
    from app.extensions import db
    from app.models import Seat, SeatType
    app, client, ids = _setup()
    with app.app_context():
        desk = db.session.get(Seat, ids["desk"])
        rooms = {}
        for code, capacity in (("Office4", 4), ("Office10", 10), ("Unset", 1)):
            seat = Seat(operator_id=desk.operator_id, location_id=desk.location_id, floor_id=desk.floor_id,
                        code=code, seat_type=SeatType.PRIVATE_OFFICE, capacity=capacity)
            db.session.add(seat)
            db.session.flush()
            rooms[code] = seat.id
        db.session.commit()
    assert _subscribe(client, ids, plan_id=ids["office_plan"], space_ids=[rooms["Office10"]]).status_code == 200
    assert _subscribe(client, ids, plan_id=ids["office_plan"], space_ids=[rooms["Office4"]]).status_code == 302
    assert _subscribe(client, ids, plan_id=ids["office_plan"], space_ids=[rooms["Unset"]]).status_code == 302
