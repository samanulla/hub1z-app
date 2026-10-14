"""Spaces and people on a subscription: which office or desks a customer has, and who can sit there."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import or_

from ..extensions import db
from ..models import (AllocationStatus, Floor, Invoice, InvoiceStatus, Location, LocationScope, PlanType, Seat,
                      SeatAllocation, SeatType)
from .billing_service import (_month_end, _operator, _q, add_line, due_date_for, invoice_status, open_invoice,
                              recompute_invoice)
from .gst import money

OFFICE_TYPES = {PlanType.PRIVATE_OFFICE, PlanType.EXECUTIVE_OFFICE, PlanType.MANAGED_OFFICE}
TRACKED_SEAT_TYPES = [SeatType.DEDICATED_DESK, SeatType.PRIVATE_OFFICE]


class SpaceError(ValueError):
    """A change that cannot be made; the message is safe to show to the operator."""


def seat_types_for(plan) -> list[SeatType]:
    """Physical inventory a plan can be tied to. Hot desks, day passes and the like are not assigned."""
    if plan.plan_type == PlanType.DEDICATED_DESK:
        return [SeatType.DEDICATED_DESK]
    if plan.plan_type in OFFICE_TYPES:
        return [SeatType.PRIVATE_OFFICE]
    return []


def people_per_unit(plan) -> int:
    if plan.plan_type in OFFICE_TYPES:
        return max(1, plan.office_capacity or plan.included_seat_quantity or 1)
    return 1


def _free_query():
    return Seat.query.filter(Seat.is_active.is_(True),
                             ~Seat.allocations.any(SeatAllocation.status == AllocationStatus.ACTIVE))


def free_seats(plan=None) -> list[Seat]:
    """Active offices/desks nobody holds. With a plan: only the kind it sells, at the locations it covers."""
    query = _free_query()
    if plan is None:
        return query.filter(Seat.seat_type.in_(TRACKED_SEAT_TYPES)).order_by(Seat.code).all()
    types = seat_types_for(plan)
    if not types:
        return []
    query = query.filter(Seat.seat_type.in_(types))
    if plan.plan_type in OFFICE_TYPES:
        # Capacity 1 is the unset default, so those rooms stay available.
        query = query.filter(or_(Seat.capacity == people_per_unit(plan), Seat.capacity <= 1))
    if plan.location_scope != LocationScope.ALL:
        query = query.filter(Seat.location_id.in_([loc.id for loc in plan.locations] or [0]))
    return query.order_by(Seat.code).all()


def holders(seat_ids) -> dict[int, list[str]]:
    """Customers currently holding each seat, by seat id (names in the order they were assigned)."""
    out: dict[int, list[str]] = {}
    rows = SeatAllocation.query.filter(SeatAllocation.seat_id.in_(list(seat_ids) or [0]),
                                       SeatAllocation.status == AllocationStatus.ACTIVE).order_by(SeatAllocation.id)
    for row in rows:
        name = row.company.name if row.company else (row.user.full_name if row.user else "")
        if name and name not in out.setdefault(row.seat_id, []):
            out[row.seat_id].append(name)
    return {seat_id: names for seat_id, names in out.items() if names}


# What cannot change while a customer holds the space: the plan was sold against that type and size.
HELD_LOCKED_FIELDS = ("seat_type", "capacity", "is_active")


def create_space(location: Location, code: str, plan) -> Seat:
    code = (code or "").strip()
    if not code:
        raise SpaceError("Enter a name or code for the new space.")
    if len(code) > 30:
        raise SpaceError("A space code can be at most 30 characters.")
    if Seat.query.filter_by(location_id=location.id, code=code).first():
        raise SpaceError(f"{code} already exists at {location.name}. Pick it from the list instead.")
    floors = Floor.query.filter_by(location_id=location.id).order_by(Floor.level).all()
    floor = next((f for f in floors if f.level >= 0), floors[0] if floors else None)
    if floor is None:
        floor = Floor(operator_id=location.operator_id, location_id=location.id, level=0, name="Ground floor")
        db.session.add(floor)
        db.session.flush()
    seat = Seat(operator_id=location.operator_id, location_id=location.id, floor_id=floor.id, code=code,
                seat_type=seat_types_for(plan)[0], capacity=people_per_unit(plan), is_active=True)
    db.session.add(seat)
    db.session.flush()
    return seat


def places(sub) -> list[SeatAllocation]:
    return SeatAllocation.query.execution_options(skip_operator_filter=True).filter_by(
        subscription_id=sub.id, status=AllocationStatus.ACTIVE).order_by(SeatAllocation.id).all()


def _add_places(sub, seat: Seat, count: int, start: date) -> None:
    """One row per person who can sit in the space; an individual holds the space themselves."""
    rows = 1 if sub.user_id else count
    for _ in range(rows):
        db.session.add(SeatAllocation(operator_id=sub.operator_id, seat_id=seat.id, company_id=sub.company_id,
                                      user_id=sub.user_id, subscription_id=sub.id,
                                      status=AllocationStatus.ACTIVE, start_date=start))


def attach_spaces(sub, seats: list[Seat]) -> None:
    for seat in seats:
        _add_places(sub, seat, sub.people_per_unit or 1, sub.start_date)
    if seats and sub.extra_people and not sub.user_id:
        _add_places(sub, seats[0], sub.extra_people, sub.start_date)


def end_places(sub, on: date | None = None) -> None:
    on = on or date.today()
    for row in places(sub):
        row.status = AllocationStatus.ENDED
        row.end_date = on


def _first_of_next_month(today: date) -> date:
    return _month_end(today.replace(day=1)).replace(day=1) if False else (
        today.replace(day=28) + (today.replace(day=28) - today.replace(day=1))).replace(day=1) \
        if False else _next_month(today)


def _next_month(today: date) -> date:
    return date(today.year + (today.month == 12), today.month % 12 + 1, 1)


def change_extra_people(sub, new_count: int, mode: str, today: date | None = None):
    """Set the extra people on a running subscription.

    mode "prorate": an increase is billed now for the rest of this month; "next": it is billed from the next
    invoice month. A decrease always applies from next month. Returns (adjustment invoice or None, message)."""
    today = today or date.today()
    new_count = int(new_count)
    if new_count < 0:
        raise SpaceError("Extra people cannot be negative.")
    plan = sub.plan
    if new_count and not plan.additional_seats_allowed:
        raise SpaceError("This plan does not allow extra people. Turn on 'Allow extra people' on the plan first.")
    if plan.maximum_additional_seats and new_count > plan.maximum_additional_seats:
        raise SpaceError(f"This plan allows at most {plan.maximum_additional_seats} extra people.")
    old = sub.extra_people or 0
    if new_count == old:
        return None, "Nothing changed."
    delta = new_count - old
    held = places(sub)
    if delta < 0 and held:
        unassigned = [row for row in held if row.user_id is None]
        if len(unassigned) < -delta:
            raise SpaceError(f"{-delta - len(unassigned)} of the places are named to employees. "
                             "Ask the company to release them first.")

    month_start = today.replace(day=1)
    next_month = _next_month(today)
    billed_now = sub.extra_people_for(month_start)
    price = Decimal(sub.extra_person_price or 0)
    invoice = None
    regular_exists = _q(Invoice, sub.operator_id).filter(
        Invoice.subscription_id == sub.id, Invoice.period_start == month_start,
        Invoice.status != InvoiceStatus.VOID).first() is not None

    sub.extra_people_before = billed_now
    sub.extra_people = new_count
    if delta > 0 and mode == "prorate" and price > 0:
        if today.day == 1 and not regular_exists:
            sub.extra_effective_from = month_start       # this month's invoice has not been raised yet
            message = "Extra people added. They are included in this month's invoice."
        else:
            sub.extra_effective_from = next_month
            last = _month_end(month_start)
            month_days = last.day
            days = (last - today).days + 1
            operator = _operator(sub.operator_id)
            invoice = open_invoice(operator, company_id=sub.company_id, user_id=sub.user_id,
                                   subscription_id=sub.id, period_start=today, period_end=last,
                                   due_date=due_date_for(sub, today, today), status=invoice_status(sub))
            add_line(invoice, f"Additional people ({today} to {last}, {days} of {month_days} days)", delta,
                     money(price * days / month_days), "plan", today, tax_inclusive=sub.price_includes_tax)
            recompute_invoice(invoice)
            message = f"Extra people added. An invoice for the rest of this month was raised ({invoice.number})."
    else:
        sub.extra_effective_from = next_month
        message = ("Extra people will be billed from the next invoice month." if delta > 0
                   else "Extra people reduced. The change applies from the next invoice month.")

    if held and not sub.user_id:
        if delta > 0:
            _add_places(sub, db.session.get(Seat, held[0].seat_id), delta, today)
        else:
            for row in [r for r in held if r.user_id is None][:-delta]:
                db.session.delete(row)
    db.session.flush()
    return invoice, message
