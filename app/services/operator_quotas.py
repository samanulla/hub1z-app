"""Enforce operator quotas at persistence, including invite acceptance and imports."""
from collections import defaultdict
from datetime import datetime, timedelta

from sqlalchemy import event, inspect, func
from sqlalchemy.orm import Session

from ..models import (Lead, Location, Operator, User, UserRole, Subscription, SubscriptionStatus,
                      SeatAllocation, AllocationStatus, OperatorSubscription, OperatorStatus)
from .entitlements import has_feature, open_manual_leads, plan_terms

STAFF = (UserRole.SUPER_ADMIN, UserRole.MANAGER, UserRole.LOCATION_MANAGER)


class QuotaExceeded(ValueError):
    pass


def _before(obj, name):
    history = inspect(obj).attrs[name].history
    return history.deleted[0] if history.deleted else getattr(obj, name)


def _manual_open(obj, previous=False):
    value = (lambda name: _before(obj, name)) if previous else (lambda name: getattr(obj, name))
    return not value("is_website_enquiry") and value("stage") not in ("won", "lost")


@event.listens_for(Session, "before_flush")
def enforce_quotas(session, flush_context, instances):
    increments = defaultdict(lambda: defaultdict(int))
    for obj in set(session.new) | set(session.dirty):
        if isinstance(obj, Operator) and obj in session.new and obj.plan_tier != "marketplace_partner":
            from flask import has_request_context
            if has_request_context():
                from .pricing_page import trial_days
                obj.trial_ends_at = obj.trial_ends_at or datetime.utcnow() + timedelta(days=trial_days())
                if obj.status is None or obj.status == OperatorStatus.ACTIVE:
                    obj.status = OperatorStatus.TRIAL
                session.add(OperatorSubscription(operator=obj, status="trial"))
        if isinstance(obj, Operator) and obj.id and obj.custom_domain and _before(obj, "custom_domain") != obj.custom_domain:
            from flask import has_request_context
            from flask_login import current_user
            # Platform staff map domains during onboarding; only the operator itself needs the paid add-on.
            staff = has_request_context() and current_user.is_authenticated and current_user.is_platform_staff
            if has_request_context() and not staff and not has_feature(obj, "white_label"):
                raise QuotaExceeded("Purchase White Label before configuring a new custom domain.")
        operator_id = getattr(obj, "operator_id", None)
        if not operator_id:
            continue
        new = obj in session.new
        if isinstance(obj, User):
            increments[operator_id]["max_staff_users"] += int(obj.role in STAFF) - (0 if new else int(_before(obj, "role") in STAFF))
        elif isinstance(obj, Lead):
            increments[operator_id]["max_open_leads"] += int(_manual_open(obj)) - (0 if new else int(_manual_open(obj, True)))
        elif isinstance(obj, Location) and new:
            increments[operator_id]["included_locations"] += 1
        elif isinstance(obj, Subscription):
            after = (obj.quantity or 1) if (obj.status or SubscriptionStatus.ACTIVE) == SubscriptionStatus.ACTIVE else 0
            before = 0 if new else ((_before(obj, "quantity") or 1) if _before(obj, "status") == SubscriptionStatus.ACTIVE else 0)
            increments[operator_id]["contracted"] += after - before
        elif isinstance(obj, SeatAllocation):
            after = int((obj.status or AllocationStatus.ACTIVE) == AllocationStatus.ACTIVE)
            before = 0 if new else int(_before(obj, "status") == AllocationStatus.ACTIVE)
            increments[operator_id]["allocated"] += after - before
    for operator_id, changes in increments.items():
        operator = Operator.query.execution_options(skip_operator_filter=True).filter_by(id=operator_id).with_for_update().one()
        terms = plan_terms(operator)
        subscription = OperatorSubscription.query.filter_by(operator_id=operator_id).first()
        if terms.get("all_features") and not (subscription and subscription.scheduled_terms):
            continue
        if subscription and subscription.scheduled_terms:
            terms = dict(terms)
            terms["all_features"] = bool(subscription.scheduled_terms.get("all_features"))
            for name in ("max_staff_users", "max_open_leads", "included_locations", "included_active_contracted_seats"):
                pending_limit = subscription.scheduled_terms.get(name)
                if pending_limit is not None:
                    terms[name] = min(terms[name], pending_limit) if terms.get(name) is not None else pending_limit
            terms["location_overage_policy"] = "require_plan_upgrade"
            terms["seat_overage_policy"] = "require_plan_upgrade"
        counts = {"max_staff_users": lambda: User.query.execution_options(skip_operator_filter=True).filter(
                      User.operator_id == operator_id, User.role.in_(STAFF)).count(),
                  "max_open_leads": lambda: open_manual_leads(operator_id),
                  "included_locations": lambda: Location.query.execution_options(skip_operator_filter=True).filter_by(
                      operator_id=operator_id).count()}
        for name, increment in changes.items():
            limit = terms.get(name)
            if name == "included_locations" and terms.get("location_overage_policy") == "allow_and_charge":
                continue
            if increment > 0 and limit is not None and counts[name]() + increment > limit:
                raise QuotaExceeded(f"Your plan's {name.replace('_', ' ')} allowance is {limit}. Upgrade to add more.")
        seat_limit = terms.get("included_active_contracted_seats")
        if seat_limit is not None and terms.get("seat_overage_policy") != "allow_and_charge" and (
                changes.get("contracted", 0) > 0 or changes.get("allocated", 0) > 0):
            contracted = session.query(func.coalesce(func.sum(Subscription.quantity), 0)).execution_options(
                skip_operator_filter=True).filter(Subscription.operator_id == operator_id,
                Subscription.status == SubscriptionStatus.ACTIVE).scalar()
            allocated = SeatAllocation.query.execution_options(skip_operator_filter=True).filter_by(
                operator_id=operator_id, status=AllocationStatus.ACTIVE).count()
            if max(contracted + changes.get("contracted", 0), allocated + changes.get("allocated", 0)) > seat_limit:
                raise QuotaExceeded(f"Your contracted-seat allowance is {seat_limit}. Upgrade before adding more.")