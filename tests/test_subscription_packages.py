"""Subscription packages: extra people, tracked spaces (pick or create), proration choice, people capacity."""
import os
from datetime import date
from decimal import Decimal

os.environ.setdefault("FLASK_ENV", "testing")

import pytest

from app.extensions import db
from app.models import (AllocationStatus, BillingUnit, Floor, Invoice, Location, PlanScope, PlanType, PricingPlan,
                        Seat, SeatAllocation, SeatType, Subscription)
from app.services import billing_service, subscription_spaces
from tests.test_admin_subscriptions import _app, _login, _seed


def _setup():
    app = _app()
    company_id, desk_plan_id = _seed(app)
    with app.app_context():
        desk_plan = db.session.get(PricingPlan, desk_plan_id)
        operator_id = desk_plan.operator_id
        office = PricingPlan(operator_id=operator_id, name="Private Office", scope=PlanScope.COMPANY_STANDARD,
                             plan_type=PlanType.PRIVATE_OFFICE, billing_unit=BillingUnit.PER_OFFICE,
                             base_price=30000, max_locations=1, office_capacity=4,
                             additional_seats_allowed=True, additional_seat_rate=3000, maximum_additional_seats=3)
        location = Location(operator_id=operator_id, name="HQ", code="HQ", address_line1="1 Main Street",
                            city="Chennai", country="IN", timezone="Asia/Kolkata")
        db.session.add_all([office, location])
        db.session.flush()
        floor = Floor(operator_id=operator_id, location_id=location.id, level=0, name="Ground floor")
        db.session.add(floor)
        db.session.flush()
        desk = Seat(operator_id=operator_id, location_id=location.id, floor_id=floor.id, code="DD-1",
                    seat_type=SeatType.DEDICATED_DESK)
        db.session.add(desk)
        db.session.commit()
        ids = dict(company=company_id, desk_plan=desk_plan_id, office_plan=office.id, location=location.id,
                   desk=desk.id)
    client = app.test_client()
    _login(client, "admin@adyarspace.com", "AdminPass123!")
    return app, client, ids


def _subscribe(client, ids, **data):
    payload = {"quantity": 1, "start_date": "2026-01-01", "new_space_location_id": ids["location"]}
    payload.update(data)
    return client.post(f"/admin/companies/{ids['company']}/subscriptions/new", data=payload, follow_redirects=False)


def test_office_with_new_space_and_extra_people_creates_places_and_invoice_line():
    app, client, ids = _setup()
    response = _subscribe(client, ids, plan_id=ids["office_plan"], extra_people=2, new_space_code="CABIN-4")
    assert response.status_code == 302
    with app.app_context():
        sub = Subscription.query.filter_by(company_id=ids["company"]).one()
        assert (sub.people_per_unit, sub.extra_people, sub.extra_person_price) == (4, 2, Decimal("3000"))
        assert sub.people_capacity == 6 and sub.monthly_total == Decimal("36000")
        seat = Seat.query.filter_by(code="CABIN-4").one()
        assert seat.seat_type == SeatType.PRIVATE_OFFICE and seat.capacity == 4
        rows = SeatAllocation.query.filter_by(subscription_id=sub.id).all()
        assert len(rows) == 6 and {row.seat_id for row in rows} == {seat.id}
        invoice = billing_service.generate_invoice_for_subscription(sub, date(2026, 2, 1), date(2026, 2, 28))
        lines = {li.description.split(" (")[0]: li for li in invoice.line_items}
        assert Decimal(lines["Additional people"].unit_price) == Decimal("3000")
        assert Decimal(lines["Additional people"].quantity) == 2


def test_extra_people_are_validated_against_the_plan():
    app, client, ids = _setup()
    assert _subscribe(client, ids, plan_id=ids["office_plan"], extra_people=4).status_code == 200   # max is 3
    assert _subscribe(client, ids, plan_id=ids["desk_plan"], extra_people=1).status_code == 200    # not allowed
    with app.app_context():
        assert Subscription.query.filter_by(company_id=ids["company"]).count() == 0


def test_existing_free_desk_can_be_picked_once_only():
    app, client, ids = _setup()
    assert _subscribe(client, ids, plan_id=ids["desk_plan"], space_ids=[ids["desk"]]).status_code == 302
    with app.app_context():
        assert SeatAllocation.query.filter_by(seat_id=ids["desk"], status=AllocationStatus.ACTIVE).count() == 1
    assert _subscribe(client, ids, plan_id=ids["desk_plan"], space_ids=[ids["desk"]]).status_code == 200
    # a plan that is not tied to a space cannot take one either
    assert _subscribe(client, ids, plan_id=ids["desk_plan"], new_space_code="X", quantity=1,
                      space_ids=[ids["desk"]]).status_code == 200
    with app.app_context():
        assert Subscription.query.filter_by(company_id=ids["company"]).count() == 1


def test_more_spaces_than_quantity_is_rejected():
    app, client, ids = _setup()
    response = _subscribe(client, ids, plan_id=ids["desk_plan"], space_ids=[ids["desk"]], new_space_code="DD-2",
                          quantity=1)
    assert response.status_code == 200
    with app.app_context():
        assert Seat.query.filter_by(code="DD-2").count() == 0


def test_cancelling_releases_the_space():
    app, client, ids = _setup()
    _subscribe(client, ids, plan_id=ids["desk_plan"], space_ids=[ids["desk"]])
    with app.app_context():
        sub_id = Subscription.query.filter_by(company_id=ids["company"]).one().id
    assert client.post(f"/admin/companies/{ids['company']}/subscriptions/{sub_id}/cancel").status_code == 302
    with app.app_context():
        assert SeatAllocation.query.filter_by(seat_id=ids["desk"], status=AllocationStatus.ACTIVE).count() == 0
    assert _subscribe(client, ids, plan_id=ids["desk_plan"], space_ids=[ids["desk"]]).status_code == 302


def _running_office(app, client, ids, extra=1):
    _subscribe(client, ids, plan_id=ids["office_plan"], extra_people=extra, new_space_code="CABIN-4")
    with app.app_context():
        return Subscription.query.filter_by(company_id=ids["company"]).one().id


def test_prorate_now_raises_an_adjustment_invoice_and_bills_the_new_count_from_next_month():
    app, client, ids = _setup()
    sub_id = _running_office(app, client, ids, extra=1)
    with app.app_context():
        sub = db.session.get(Subscription, sub_id)
        billing_service.generate_invoice_for_subscription(sub, date(2026, 2, 1), date(2026, 2, 28))
        invoice, _ = subscription_spaces.change_extra_people(sub, 3, "prorate", today=date(2026, 2, 10))
        db.session.commit()
        assert invoice is not None and (invoice.period_start, invoice.period_end) == (date(2026, 2, 10),
                                                                                       date(2026, 2, 28))
        line = invoice.line_items[0]
        assert Decimal(line.quantity) == 2 and "19 of 28 days" in line.description
        assert Decimal(line.unit_price) == Decimal("2035.71")      # 3000 * 19 / 28
        assert sub.extra_people_for(date(2026, 2, 1)) == 1 and sub.extra_people_for(date(2026, 3, 1)) == 3
        march = billing_service.generate_invoice_for_subscription(sub, date(2026, 3, 1), date(2026, 3, 31))
        assert any(Decimal(li.quantity) == 3 and li.description.startswith("Additional people")
                   for li in march.line_items)
        assert len(SeatAllocation.query.filter_by(subscription_id=sub_id, status=AllocationStatus.ACTIVE).all()) == 7


def test_bill_next_month_makes_no_invoice_now():
    app, client, ids = _setup()
    sub_id = _running_office(app, client, ids, extra=0)
    with app.app_context():
        sub = db.session.get(Subscription, sub_id)
        invoice, _ = subscription_spaces.change_extra_people(sub, 2, "next", today=date(2026, 2, 10))
        assert invoice is None and sub.extra_effective_from == date(2026, 3, 1)
        feb = billing_service.generate_invoice_for_subscription(sub, date(2026, 2, 1), date(2026, 2, 28))
        assert not any(li.description.startswith("Additional people") for li in feb.line_items)


def test_prorate_on_the_first_before_the_invoice_exists_goes_on_the_regular_invoice():
    app, client, ids = _setup()
    sub_id = _running_office(app, client, ids, extra=0)
    with app.app_context():
        sub = db.session.get(Subscription, sub_id)
        invoice, _ = subscription_spaces.change_extra_people(sub, 1, "prorate", today=date(2026, 2, 1))
        assert invoice is None
        feb = billing_service.generate_invoice_for_subscription(sub, date(2026, 2, 1), date(2026, 2, 28))
        assert any(li.description.startswith("Additional people") for li in feb.line_items)


def test_reducing_extra_people_needs_unnamed_places_and_applies_next_month():
    app, client, ids = _setup()
    sub_id = _running_office(app, client, ids, extra=2)
    with app.app_context():
        sub = db.session.get(Subscription, sub_id)
        subscription_spaces.change_extra_people(sub, 1, "next", today=date(2026, 2, 10))
        assert sub.extra_people_for(date(2026, 2, 1)) == 2 and sub.extra_people_for(date(2026, 3, 1)) == 1
        assert len(subscription_spaces.places(sub)) == 5
        with pytest.raises(subscription_spaces.SpaceError):
            subscription_spaces.change_extra_people(sub, 9, "next", today=date(2026, 2, 10))


def test_company_capacity_counts_people_not_offices():
    app, client, ids = _setup()
    _subscribe(client, ids, plan_id=ids["office_plan"], extra_people=2, new_space_code="CABIN-4")
    company = app.test_client()
    _login(company, "jane@acme.example", "JanePass123!")
    page = company.get("/company/allocations")
    assert page.status_code == 200
    assert b"People covered" in page.data and b"Allocate a seat" not in page.data
