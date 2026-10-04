"""Creating and editing a pricing plan through the admin form."""
import os
from decimal import Decimal

os.environ.setdefault("FLASK_ENV", "testing")

from app.models import PlanStatus, PricingPlan
from tests.test_release_upi_parcels_alerts import DEMO, _client, _get, _post, _seeded_app


def _form(**overrides):
    data = {"name": "Day pass", "scope": "individual", "plan_type": "day_pass", "billing_unit": "per_day_pass",
            "billing_cycle": "daily", "status": "active", "base_price": "499", "currency": "INR",
            "location_scope": "all", "effective_from": "2026-10-01"}
    data.update(overrides)
    return data


def test_plan_create_and_edit_set_is_active_from_status():
    app, _ = _seeded_app()
    owner = _client(app, DEMO, "owner@demospace.com")
    r = _post(owner, DEMO, "/admin/plans/new", _form(plan_type="dedicated_desk", billing_unit="per_seat",
                                                 billing_cycle="monthly", included_seat_quantity="10"))
    assert r.status_code == 302, r.data[:400]
    with app.app_context():
        plan = PricingPlan.query.execution_options(skip_operator_filter=True).filter_by(name="Day pass").one()
        assert plan.status == PlanStatus.ACTIVE and plan.is_active and plan.base_price == Decimal("499.00")
        plan_id = plan.id

    page = _get(owner, DEMO, f"/admin/plans/{plan_id}/edit").data.decode()
    assert 'selected value="dedicated_desk"' in page
    assert 'selected value="per_seat"' in page
    assert 'name="included_seat_quantity" type="number" value="10"' in page

    r = _post(owner, DEMO, f"/admin/plans/{plan_id}/edit", _form(status="inactive"))
    assert r.status_code == 302, r.data[:400]
    with app.app_context():
        plan = PricingPlan.query.execution_options(skip_operator_filter=True).get(plan_id)
        assert plan.status == PlanStatus.INACTIVE and not plan.is_active
