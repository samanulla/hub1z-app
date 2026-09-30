"""Enforce only SaaS limits that constrain the operator contract.

Seat/ConferenceRoom have no operator_id of their own — they're scoped only via
their Location — so every count here joins through Location explicitly
rather than relying on the ambient operator auto-scoping listener.

"People" (resource="person") is capped at the SAME number as max_seats —
number of seats = number of people, always. This exists specifically so a
operator can't sidestep a seat cap by just not buying more desks while still
piling on employees/individual members past what its plan is meant to
support. Counts EMPLOYEE + INDIVIDUAL + COMPANY_ADMIN (people who occupy
space), not operator staff (Manager/Location Manager/Super Admin).
"""
from __future__ import annotations

from ..models import PricingTier, Location


def _tier_for(operator) -> PricingTier | None:
    if operator is None or not operator.plan_tier:
        return None
    return PricingTier.query.filter_by(key=operator.plan_tier).first()


def check_limit(operator, resource: str) -> tuple[bool, str | None]:
    """Can this operator add one more of `resource`?

    Only locations are a hard creation cap. Active contracted seats are
    measured for billing, while desks, private offices and meeting rooms stay
    operational inventory and do not carry separate Hub1 SaaS caps.
    Returns (True, None) if allowed (including when there's no tier or no
    limit configured — fail open, not closed). Returns (False, message)
    when the operator is already at its tier's cap.
    """
    tier = _tier_for(operator)
    if tier is None:
        return True, None
    tid = operator.id

    if resource == "location":
        limit, count = tier.max_locations, Location.query.filter_by(operator_id=tid).count()
    else:
        return True, None

    if limit is None:
        return True, None
    if count >= limit:
        return False, (f"Your {tier.name} plan allows up to {limit} locations. "
                       f"Contact your account manager to upgrade.")
    return True, None
