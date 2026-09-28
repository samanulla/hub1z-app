"""Hub1 SaaS tier usage and operator subscription pricing."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import or_

from ..models import (
    Company, Location, Seat, SeatAllocation, AllocationStatus, Subscription,
    SubscriptionStatus, User,
    OperatorUsageSnapshot,
)


def active_contracted_seats(tenant_id: int) -> int:
    """Count contracted customer seats, not physical workspace capacity."""
    subscriptions = (Subscription.query
                     .outerjoin(Company, Subscription.company_id == Company.id)
                     .outerjoin(User, Subscription.user_id == User.id)
                     .filter(Subscription.status == SubscriptionStatus.ACTIVE)
                     .filter(or_(Subscription.tenant_id == tenant_id,
                                 Company.tenant_id == tenant_id,
                                 User.tenant_id == tenant_id)).all())
    contracted = sum(subscription.quantity for subscription in subscriptions)
    assigned = SeatAllocation.query.join(SeatAllocation.seat).filter(
        SeatAllocation.status == AllocationStatus.ACTIVE,
        SeatAllocation.seat.has(tenant_id=tenant_id, is_active=True),
    ).count()
    return max(contracted, assigned)


def record_usage_snapshot(tenant_id: int) -> int:
    seats = active_contracted_seats(tenant_id)
    snapshot = OperatorUsageSnapshot.query.filter_by(tenant_id=tenant_id, recorded_on=date.today()).first()
    if snapshot is None:
        snapshot = OperatorUsageSnapshot(tenant_id=tenant_id, recorded_on=date.today(), active_contracted_seats=seats)
        from ..extensions import db
        db.session.add(snapshot)
    else:
        snapshot.active_contracted_seats = max(snapshot.active_contracted_seats, seats)
    return seats


def subscription_pricing(tenant, tier, subscription=None) -> dict:
    """Return an auditable monthly/annual operator charge breakdown."""
    monthly = not subscription or subscription.billing_cycle != "annual"
    base = (
        subscription.negotiated_base_price
        if subscription and subscription.negotiated_base_price is not None
        else (tier.monthly_price if monthly else tier.annual_price)
    )
    base = Decimal(base or 0)
    locations = Location.query.filter_by(tenant_id=tenant.id).count()
    seats = record_usage_snapshot(tenant.id)
    period_start = date.today().replace(day=1)
    peak = (OperatorUsageSnapshot.query.filter(
        OperatorUsageSnapshot.tenant_id == tenant.id,
        OperatorUsageSnapshot.recorded_on >= period_start,
    ).with_entities(OperatorUsageSnapshot.active_contracted_seats)
            .order_by(OperatorUsageSnapshot.active_contracted_seats.desc()).first())
    seats = max(seats, peak[0] if peak else 0)
    included_locations = (tier.max_locations or 0) + (subscription.additional_free_locations if subscription else 0)
    included_seats = (tier.included_active_contracted_seats or 0) + (subscription.additional_free_seats if subscription else 0)
    seat_rate = (subscription.custom_additional_seat_rate if subscription and subscription.custom_additional_seat_rate is not None
                 else tier.additional_seat_rate)
    location_rate = (subscription.custom_additional_location_rate if subscription and subscription.custom_additional_location_rate is not None
                     else tier.additional_location_rate)
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
    }