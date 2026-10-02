"""Hub1 SaaS tier usage and operator subscription pricing."""
from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

from sqlalchemy import or_

from ..models import (
    Company, Location, Seat, SeatAllocation, AllocationStatus, Subscription,
    SubscriptionStatus, User,
    OperatorUsageSnapshot,
)


def active_contracted_seats(operator_id: int) -> int:
    """Count contracted customer seats, not physical workspace capacity."""
    subscriptions = (Subscription.query
                     .outerjoin(Company, Subscription.company_id == Company.id)
                     .outerjoin(User, Subscription.user_id == User.id)
                     .filter(Subscription.status == SubscriptionStatus.ACTIVE)
                     .filter(or_(Subscription.operator_id == operator_id,
                                 Company.operator_id == operator_id,
                                 User.operator_id == operator_id)).all())
    contracted = sum(subscription.quantity for subscription in subscriptions)
    assigned = SeatAllocation.query.join(SeatAllocation.seat).filter(
        SeatAllocation.status == AllocationStatus.ACTIVE,
        SeatAllocation.seat.has(operator_id=operator_id, is_active=True),
    ).count()
    return max(contracted, assigned)


def record_usage_snapshot(operator_id: int, on: date | None = None) -> int:
    on = on or date.today()
    seats = active_contracted_seats(operator_id)
    locations = Location.query.filter_by(operator_id=operator_id).count()
    snapshot = OperatorUsageSnapshot.query.filter_by(operator_id=operator_id, recorded_on=on).first()
    if snapshot is None:
        snapshot = OperatorUsageSnapshot(operator_id=operator_id, recorded_on=on, active_contracted_seats=seats,
                         active_locations=locations)
        from ..extensions import db
        db.session.add(snapshot)
    else:
        snapshot.active_contracted_seats = max(snapshot.active_contracted_seats, seats)
        snapshot.active_locations = max(snapshot.active_locations, locations)
    return seats


def subscription_pricing(operator, tier, subscription=None) -> dict:
    """Return an auditable monthly/annual operator charge breakdown."""
    snapshot = json.loads(subscription.pricing_snapshot) if subscription and subscription.pricing_snapshot else {}
    monthly = not subscription or subscription.billing_cycle != "annual"

    def _decimal_or_none(value):
        if value is None:
            return None
        return Decimal(str(value))

    if subscription and subscription.negotiated_base_price is not None:
        base = Decimal(subscription.negotiated_base_price)
    else:
        snapshot_base = _decimal_or_none(snapshot.get("monthly_price" if monthly else "annual_price"))
        tier_base = tier.monthly_price if monthly else tier.annual_price
        base = snapshot_base if snapshot_base is not None else _decimal_or_none(tier_base) or Decimal(0)
    locations = Location.query.filter_by(operator_id=operator.id).count()
    seats = record_usage_snapshot(operator.id)
    period_start = date.today().replace(day=1)
    peak = (OperatorUsageSnapshot.query.filter(
        OperatorUsageSnapshot.operator_id == operator.id,
        OperatorUsageSnapshot.recorded_on >= period_start,
    ).with_entities(OperatorUsageSnapshot.active_contracted_seats)
            .order_by(OperatorUsageSnapshot.active_contracted_seats.desc()).first())
    seats = max(seats, peak[0] if peak else 0)
    included_locations = (snapshot.get("included_locations", tier.max_locations) or 0) + (subscription.additional_free_locations if subscription else 0)
    included_seats = (snapshot.get("included_active_contracted_seats", tier.included_active_contracted_seats) or 0) + (subscription.additional_free_seats if subscription else 0)
    seat_rate = (subscription.custom_additional_seat_rate if subscription and subscription.custom_additional_seat_rate is not None
                 else snapshot.get("additional_seat_rate", tier.additional_seat_rate))
    location_rate = (subscription.custom_additional_location_rate if subscription and subscription.custom_additional_location_rate is not None
                     else snapshot.get("additional_location_rate", tier.additional_location_rate))
    additional_seats = max(seats - included_seats, 0)
    additional_locations = max(locations - included_locations, 0)
    seat_overage = Decimal(seat_rate or 0) * additional_seats
    location_overage = Decimal(location_rate or 0) * additional_locations
    modules = Decimal(subscription.premium_modules_amount or 0) if subscription else Decimal(0)
    implementation = Decimal(subscription.implementation_charge or 0) if subscription else Decimal(0)
    discount = Decimal(subscription.discount_amount or 0) if subscription else Decimal(0)
    subtotal = base + seat_overage + location_overage + modules + implementation - discount
    tax_rate = Decimal(subscription.tax_rate or 0) if subscription else Decimal(0)
    tax = max(subtotal, Decimal(0)) * tax_rate / Decimal(100)
    return {
        "locations": locations,
        "active_contracted_seats": seats,
        "additional_locations": additional_locations,
        "additional_seats": additional_seats,
        "base": base,
        "seat_overage": seat_overage,
        "location_overage": location_overage,
        "seat_overage_requires_review": additional_seats > 0 and Decimal(seat_rate or 0) == 0,
        "location_overage_requires_review": additional_locations > 0 and Decimal(location_rate or 0) == 0,
        "premium_modules": modules,
        "implementation": implementation,
        "discount": discount,
        "tax": tax,
        "total": subtotal + tax,
        "pricing_version": snapshot.get("pricing_version", tier.pricing_version),
    }