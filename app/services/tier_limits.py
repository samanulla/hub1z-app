"""Enforce a tenant's PricingTier resource caps (seats, private offices,
conference rooms, locations, people). None caps happen: unlimited on that
tier, or no tier configured (e.g. slug doesn't match any PricingTier.key).

Seat/ConferenceRoom have no tenant_id of their own — they're scoped only via
their Location — so every count here joins through Location explicitly
rather than relying on the ambient tenant auto-scoping listener.

"People" (resource="person") is capped at the SAME number as max_seats —
number of seats = number of people, always. This exists specifically so a
tenant can't sidestep a seat cap by just not buying more desks while still
piling on employees/individual members past what its plan is meant to
support. Counts EMPLOYEE + INDIVIDUAL + COMPANY_ADMIN (people who occupy
space), not tenant staff (Manager/Location Manager/Super Admin).
"""
from __future__ import annotations

from ..models import PricingTier, Location, Seat, SeatType, ConferenceRoom, User, UserRole

_PERSON_ROLES = [UserRole.EMPLOYEE, UserRole.INDIVIDUAL, UserRole.COMPANY_ADMIN]


def _tier_for(tenant) -> PricingTier | None:
    if tenant is None or not tenant.plan_tier:
        return None
    return PricingTier.query.filter_by(key=tenant.plan_tier).first()


def check_limit(tenant, resource: str) -> tuple[bool, str | None]:
    """Can this tenant add one more of `resource`?

    `resource` is one of: "location", "seat", "private_office", "room", "person".
    Returns (True, None) if allowed (including when there's no tier or no
    limit configured — fail open, not closed). Returns (False, message)
    when the tenant is already at its tier's cap.
    """
    tier = _tier_for(tenant)
    if tier is None:
        return True, None
    tid = tenant.id

    if resource == "location":
        limit, count = tier.max_locations, Location.query.filter_by(tenant_id=tid).count()
    elif resource == "seat":
        limit = tier.max_seats
        count = (Seat.query.join(Location)
                 .filter(Location.tenant_id == tid,
                        Seat.seat_type.in_([SeatType.HOT_DESK, SeatType.DEDICATED_DESK]))
                 .count())
    elif resource == "private_office":
        limit = tier.max_private_offices
        count = (Seat.query.join(Location)
                 .filter(Location.tenant_id == tid, Seat.seat_type == SeatType.PRIVATE_OFFICE)
                 .count())
    elif resource == "room":
        limit = tier.max_rooms
        count = ConferenceRoom.query.join(Location).filter(Location.tenant_id == tid).count()
    elif resource == "person":
        limit = tier.max_seats  # no of seats = no of people, always
        count = User.query.filter(User.tenant_id == tid, User.role.in_(_PERSON_ROLES)).count()
    else:
        return True, None

    if limit is None:
        return True, None
    if count >= limit:
        label = "people" if resource == "person" else (
            resource.replace("_", " ") + ("s" if not resource.endswith("s") else ""))
        return False, (f"Your {tier.name} plan allows up to {limit} {label}. "
                       f"Contact your account manager to upgrade.")
    return True, None
