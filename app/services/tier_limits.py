"""Enforce only SaaS limits that constrain the operator contract.

Seat/ConferenceRoom have no operator_id of their own — they're scoped only via
their Location — so every count here joins through Location explicitly
rather than relying on the ambient operator auto-scoping listener.
"""
from __future__ import annotations

from ..models import PricingTier, Location
from .entitlements import plan_terms


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
    terms = plan_terms(operator)
    if not operator or not terms or terms.get("all_features"):
        return True, None
    tid = operator.id

    if resource == "location":
        if terms.get("location_overage_policy") == "allow_and_charge":
            return True, None
        limit, count = terms.get("included_locations"), Location.query.filter_by(operator_id=tid).count()
    else:
        return True, None

    if limit is None:
        return True, None
    if count >= limit:
        return False, (f"Your {terms.get('name', 'current')} plan allows up to {limit} locations. "
                       f"Contact your account manager to upgrade.")
    return True, None
