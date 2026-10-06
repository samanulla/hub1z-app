"""Operator plan invoices and payment-confirmed activation."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from uuid import uuid4

from dateutil.relativedelta import relativedelta

from ..extensions import db
from ..models import (AuditLog, Location, Operator, OperatorAddon, OperatorStatus, OperatorSubscription,
                      PlatformInvoice, PlatformInvoiceStatus, PlatformModule, PlatformPayment,
                      PlatformProfile, PricingTier, TierStatus, User, UserRole)
from ..models import OperatorUsageSnapshot
from .catalog import ADDON, BY_CODE
from .platform_pricing import active_contracted_seats, record_usage_snapshot
from .pricing_page import trial_days

OPEN = (PlatformInvoiceStatus.ISSUED, PlatformInvoiceStatus.OVERDUE)
METHODS = ("upi", "gpay", "bank", "cash", "other")


def money(value):
    return Decimal(str(value or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def audit(action, entity_id, actor_id=None, **details):
    db.session.add(AuditLog(action=action, entity_type="operator_subscription", entity_id=entity_id,
                            actor_id=actor_id, details=json.dumps(details, default=str)))


def subscription_for(operator):
    subscription = OperatorSubscription.query.filter_by(operator_id=operator.id).first()
    if subscription is None:
        subscription = OperatorSubscription(operator_id=operator.id, status="trial")
        db.session.add(subscription)
        db.session.flush()
    return subscription


def start_trial(operator):
    operator.trial_ends_at = datetime.utcnow() + timedelta(days=trial_days())
    operator.status = OperatorStatus.TRIAL
    subscription_for(operator)


def snapshot(tier, subscription=None):
    return {
        "tier_id": tier.id, "tier_key": tier.key, "name": tier.name, "sort_order": tier.sort_order,
        "monthly_price": str(tier.monthly_price) if tier.monthly_price is not None else None,
        "annual_price": str(tier.calculate_annual_price()) if tier.monthly_price is not None else None,
        "annual_discount": str(tier.annual_discount), "pricing_version": tier.pricing_version,
        "all_features": tier.all_features,
        "features": [module.code for module in tier.module_catalog if module.kind == "feature"],
        "included_addons": [module.code for module in tier.module_catalog if module.kind == "addon"],
        "included_locations": tier.max_locations, "included_active_contracted_seats": tier.included_active_contracted_seats,
        "max_staff_users": tier.max_staff_users, "max_open_leads": tier.max_open_leads, "storage_mb": tier.storage_mb,
        "additional_seat_rate": str(tier.additional_seat_rate),
        "additional_location_rate": str(tier.additional_location_rate),
        "seat_overage_policy": tier.seat_overage_policy.value,
        "location_overage_policy": tier.location_overage_policy.value,
        "seat_usage_method": tier.seat_usage_method.value,
        "negotiated_base_price": (str(subscription.negotiated_base_price)
                                  if tier.contact_sales and subscription and subscription.negotiated_base_price is not None
                                  else None),
    }


def base_price(terms, cycle):
    negotiated = terms.get("negotiated_base_price")
    value = negotiated if negotiated is not None else terms.get("annual_price" if cycle == "annual" else "monthly_price")
    if value is None:
        raise ValueError("Contact Hub1z for a priced Enterprise quote.")
    return money(max(money(value) + money(terms.get("premium_modules_amount")) - money(terms.get("discount_amount")), 0))


def paid_terms(subscription):
    if subscription.tier is None:
        return json.loads(subscription.pricing_snapshot or "{}")
    stored = json.loads(subscription.pricing_snapshot or "{}")
    terms = snapshot(subscription.tier, subscription)
    terms.update(stored)
    if "features" in stored and "included_addons" not in stored:
        # Contracts captured before tiers could include add-ons keep their original terms.
        terms["included_addons"] = []
    if "negotiated_base_price" not in stored and subscription.negotiated_base_price is not None:
        terms["negotiated_base_price"] = str(subscription.negotiated_base_price)
    for name in ("premium_modules_amount", "discount_amount"):
        if name not in stored:
            terms[name] = str(getattr(subscription, name) or 0)
    if not stored.get("commercial_allowances_applied"):
        for name, extra in (("included_locations", subscription.additional_free_locations),
                            ("included_active_contracted_seats", subscription.additional_free_seats)):
            if terms.get(name) is not None:
                terms[name] += extra or 0
        for name in ("seat", "location"):
            custom = getattr(subscription, f"custom_additional_{name}_rate")
            if custom is not None:
                terms[f"additional_{name}_rate"] = str(custom)
    terms["commercial_allowances_applied"] = True
    return terms


def validate_capacity(operator, terms, strict=True):
    if terms.get("all_features"):
        return
    counts = {"included_locations": Location.query.filter_by(operator_id=operator.id).count(),
              "included_active_contracted_seats": active_contracted_seats(operator.id),
              "max_staff_users": User.query.execution_options(skip_operator_filter=True).filter(
                  User.operator_id == operator.id,
                  User.role.in_((UserRole.SUPER_ADMIN, UserRole.MANAGER, UserRole.LOCATION_MANAGER))).count()}
    from .entitlements import active_addon, storage_used, open_manual_leads
    storage_addon = active_addon(operator, "extra_storage")
    counts.update(storage_mb=storage_used(operator.id) / (1024 * 1024),
                  max_open_leads=open_manual_leads(operator.id))
    for name, count in counts.items():
        policy = terms.get("seat_overage_policy" if name == "included_active_contracted_seats" else "location_overage_policy")
        if not strict and name in ("included_active_contracted_seats", "included_locations") and policy == "allow_and_charge":
            continue
        limit = terms.get(name)
        if name == "storage_mb" and limit is not None and storage_addon:
            limit += storage_addon.renewing_quantity * 5 * 1024
        if limit is not None and count > limit:
            raise ValueError(f"Reduce current usage before selecting this plan ({name.replace('_', ' ')}: {count:g}/{limit}).")


def _invoice(operator, lines, start, end, kind, target=None, key=None, today=None):
    today = today or date.today()
    if key:
        existing = PlatformInvoice.query.filter_by(idempotency_key=key).first()
        if existing:
            return existing
    profile = PlatformProfile.get()
    same_state = bool(profile.gst_state and operator.gst_state and profile.gst_state == operator.gst_state)
    invoice = PlatformInvoice(
        operator_id=operator.id, number=f"{profile.invoice_prefix}-{today:%y%m%d}-{uuid4().hex[:10].upper()}",
        period_start=start, period_end=end, due_date=today,
        gst_state=operator.gst_state, tax_rate=profile.default_gst_rate, sac_code=profile.sac_code,
        activation=target, kind=kind, idempotency_key=key, status=PlatformInvoiceStatus.ISSUED,
        **_amounts(lines, profile.default_gst_rate, same_state))
    db.session.add(invoice)
    db.session.flush()
    return invoice


def _amounts(lines, rate, same_state):
    subtotal = money(sum((money(line["amount"]) for line in lines), Decimal(0)))
    tax = money(subtotal * money(rate) / 100)
    cgst = money(tax / 2) if same_state else Decimal(0)
    return dict(lines=[dict(line, amount=str(money(line["amount"]))) for line in lines], subtotal=subtotal,
                amount=subtotal + tax, cgst=cgst, sgst=tax - cgst if same_state else 0, igst=0 if same_state else tax)


def request_plan(operator, tier, cycle="monthly", today=None, actor_id=None, terms=None):
    today = today or date.today()
    custom_terms = terms is not None
    if cycle not in ("monthly", "annual") or tier.status != TierStatus.ACTIVE or not tier.is_active or tier.key == "scale":
        raise ValueError("Select an active plan and a valid billing cycle.")
    Operator.query.execution_options(skip_operator_filter=True).filter_by(id=operator.id).with_for_update().one()
    subscription = subscription_for(operator)
    terms = terms or snapshot(tier, subscription)
    target_price = base_price(terms, cycle)
    paid = subscription.status == "active" and subscription.current_period_end is not None
    current_terms = paid_terms(subscription) if paid else {}
    if paid and (cycle != subscription.billing_cycle
                 or terms["sort_order"] < current_terms.get("sort_order", subscription.tier.sort_order if subscription.tier else 0)
                 or (current_terms and target_price < base_price(current_terms, cycle))):
        validate_capacity(operator, terms)
        subscription.scheduled_tier_id = tier.id
        subscription.scheduled_billing_cycle = cycle
        subscription.scheduled_terms = terms
        audit("operator_plan.scheduled", subscription.id, actor_id, tier=tier.key, cycle=cycle)
        return None
    if paid and subscription.tier_id == tier.id and subscription.billing_cycle == cycle and (not custom_terms or terms == current_terms):
        raise ValueError("This is already your active plan.")
    pending = PlatformInvoice.query.filter_by(operator_id=operator.id).filter(
        PlatformInvoice.kind.in_(("plan", "upgrade")), PlatformInvoice.status.in_(OPEN)).first()
    if pending:
        if pending.activation and pending.activation["terms"]["tier_id"] == tier.id and pending.activation["cycle"] == cycle:
            return pending
        raise ValueError("Cancel the existing unpaid plan invoice before choosing a different plan.")
    start = today
    end = today + relativedelta(years=1 if cycle == "annual" else 0, months=1 if cycle == "monthly" else 0) - timedelta(days=1)
    kind = "plan"
    amount = target_price
    if paid and today <= subscription.current_period_end:
        start, end, kind = subscription.current_period_start, subscription.current_period_end, "upgrade"
        remaining = (end - today).days + 1
        total_days = (end - start).days + 1
        amount = money(max(target_price - base_price(current_terms, cycle), Decimal(0)) * remaining / total_days)
    validate_capacity(operator, terms, strict=False)
    lines = [{"description": f"{tier.name} {cycle}" + (" upgrade (prorated)" if kind == "upgrade" else ""), "amount": amount}]
    if not paid and money(terms.get("implementation_charge")) > 0:
        lines.append({"description": "Implementation (one-time)", "amount": money(terms["implementation_charge"])})
    invoice = _invoice(operator, lines, start, end, kind,
                       {"terms": terms, "cycle": cycle}, today=today)
    audit("operator_plan.invoiced", subscription.id, actor_id, invoice=invoice.number, tier=tier.key)
    if invoice.amount == 0:
        invoice.status = PlatformInvoiceStatus.PAID
        invoice.paid_at = datetime.utcnow()
        _activate(invoice, today)
    return invoice


def payment_total(invoice):
    return money(sum((payment.amount for payment in invoice.payments), Decimal(0)))


def balance(invoice):
    return Decimal(0) if invoice.status == PlatformInvoiceStatus.PAID else max(money(invoice.amount - payment_total(invoice)), Decimal(0))


def confirm_payment(invoice, amount, method, reference=None, actor_id=None, report_id=None, paid_on=None, request_key=None):
    invoice = PlatformInvoice.query.filter_by(id=invoice.id).with_for_update().one()
    if request_key:
        existing = PlatformPayment.query.filter_by(request_key=request_key).first()
        if existing:
            if existing.invoice_id != invoice.id:
                raise ValueError("This payment request belongs to a different invoice.")
            return invoice
    if invoice.status == PlatformInvoiceStatus.PAID:
        return invoice
    if invoice.status not in OPEN or method not in METHODS or money(amount) <= 0:
        raise ValueError("Choose an open invoice, a valid payment method and a positive amount.")
    if report_id and PlatformPayment.query.filter_by(report_id=report_id).first():
        return invoice
    remaining = money(invoice.amount - payment_total(invoice))
    if money(amount) > remaining:
        raise ValueError("The payment exceeds the invoice's outstanding amount.")
    payment = PlatformPayment(invoice_id=invoice.id, report_id=report_id, amount=money(amount), method=method,
                              reference=(reference or "")[:120] or None, recorded_by_id=actor_id,
                              paid_on=paid_on or date.today(), request_key=request_key)
    db.session.add(payment)
    invoice.payments.append(payment)
    db.session.flush()
    if payment_total(invoice) >= invoice.amount:
        invoice.status = PlatformInvoiceStatus.PAID
        invoice.paid_at = datetime.utcnow()
        _activate(invoice)
    audit("operator_payment.confirmed", invoice.id, actor_id, amount=amount, method=method, reference=reference)
    return invoice


def _activate(invoice, today=None):
    today = today or date.today()
    if not invoice.activation:
        return
    operator = Operator.query.execution_options(skip_operator_filter=True).filter_by(id=invoice.operator_id).one()
    subscription = subscription_for(operator)
    if invoice.kind == "addon":
        module_id = invoice.activation["module_id"]
        addon = OperatorAddon.query.filter_by(operator_id=operator.id, module_id=module_id).first()
        if addon is None:
            addon = OperatorAddon(operator_id=operator.id, module_id=module_id)
            db.session.add(addon)
        addon.quantity = invoice.activation["quantity"]
        addon.monthly_price = Decimal(invoice.activation["monthly_price"])
        addon.active = True
        addon.cancel_at_period_end = False
        addon.renewal_quantity = None
        addon.paid_through = invoice.period_end
        db.session.flush()
        _reprice_renewals(operator, [renewal for renewal in _upcoming_renewals(operator, subscription)
                                     if renewal.status in OPEN and not renewal.payments])
        return
    terms = invoice.activation["terms"]
    if invoice.kind == "renewal" and invoice.period_start > today:
        return
    subscription.tier_id = terms["tier_id"]
    subscription.status = "active"
    subscription.billing_cycle = invoice.activation["cycle"]
    subscription.current_period_start = invoice.period_start
    subscription.current_period_end = invoice.period_end
    subscription.pricing_snapshot = json.dumps(terms)
    subscription.scheduled_tier_id = None
    subscription.scheduled_billing_cycle = None
    subscription.scheduled_terms = None
    operator.plan_tier = terms["tier_key"]
    if operator.status == OperatorStatus.TRIAL:
        operator.status = OperatorStatus.ACTIVE
    if invoice.kind != "renewal":
        return
    renewing = {entry["module_id"]: entry for entry in invoice.activation.get("addons", [])}
    for addon in OperatorAddon.query.filter_by(operator_id=operator.id, active=True).all():
        entry = renewing.get(addon.module_id)
        if entry:
            addon.paid_through = invoice.period_end
            addon.quantity = entry.get("quantity", addon.quantity)
            addon.renewal_quantity = None
            addon.cancel_at_period_end = False
        elif addon.renewing_quantity == 0:
            addon.active = False
            addon.cancel_at_period_end = False
            addon.renewal_quantity = None


def request_addon(operator, module, quantity=1, today=None, actor_id=None):
    today = today or date.today()
    entry = BY_CODE.get(module.code)
    if (module.kind != ADDON or not module.is_active or module.availability != "available" or not entry or not entry.built
            or not 1 <= quantity <= 100 or module.monthly_price <= 0):
        raise ValueError("This add-on is not available for purchase.")
    from .entitlements import plan_terms
    if module.code in plan_terms(operator).get("included_addons", []):
        raise ValueError("This add-on is already included in your plan.")
    subscription = subscription_for(operator)
    if subscription.status != "active" or not subscription.current_period_end or today > subscription.current_period_end:
        raise ValueError("Activate a paid plan before purchasing add-ons.")
    addon = OperatorAddon.query.filter_by(operator_id=operator.id, module_id=module.id, active=True).first()
    if addon and not addon.cancel_at_period_end and addon.quantity == quantity:
        raise ValueError("This add-on is already active.")
    old_quantity = addon.quantity if addon and addon.paid_through and addon.paid_through >= today else 0
    if quantity <= old_quantity:
        raise ValueError("To add units, request more than you have now. Use the renewal controls to reduce or cancel.")
    pending = PlatformInvoice.query.filter_by(operator_id=operator.id, kind="addon").filter(
        PlatformInvoice.status.in_(OPEN)).all()
    for invoice in pending:
        if invoice.activation["module_id"] == module.id:
            return invoice
    remaining = (subscription.current_period_end - today).days + 1
    period_days = (subscription.current_period_end - subscription.current_period_start).days + 1
    multiplier = 12 if subscription.billing_cycle == "annual" else 1
    amount = money(module.monthly_price * (quantity - old_quantity) * multiplier * remaining / period_days)
    invoice = _invoice(operator, [{"description": f"{module.name} x {quantity - old_quantity} (prorated)", "amount": amount}],
                       today, subscription.current_period_end, "addon",
                       {"module_id": module.id, "quantity": quantity, "monthly_price": str(module.monthly_price)}, today=today)
    audit("operator_addon.invoiced", subscription.id, actor_id, module=module.code, quantity=quantity)
    return invoice


def _renewal_lines(operator, terms, cycle):
    lines = [{"description": f"{terms['name']} {cycle} renewal", "amount": base_price(terms, cycle)}]
    addons = []
    for addon in OperatorAddon.query.filter_by(operator_id=operator.id, active=True).all():
        units = addon.renewing_quantity
        if units:
            lines.append({"description": f"{addon.module.name} x {units}",
                          "amount": addon.monthly_price * units * (12 if cycle == "annual" else 1)})
            addons.append({"module_id": addon.module_id, "quantity": units})
    return lines, addons


def schedule_addon_renewal(operator, addon, units, actor_id=None):
    """Choose how many units renew: 0 cancels the add-on at period end, None keeps the current quantity."""
    Operator.query.execution_options(skip_operator_filter=True).filter_by(id=operator.id).with_for_update().one()
    if addon.operator_id != operator.id or not addon.active:
        raise ValueError("This add-on is not active.")
    if units is not None and not 0 <= units <= addon.quantity:
        raise ValueError(f"Choose between 0 and {addon.quantity} units. To add units, purchase more.")
    if units == addon.quantity:
        units = None
    upcoming = _upcoming_renewals(operator, subscription_for(operator))
    if any(invoice.status == PlatformInvoiceStatus.PAID or invoice.payments for invoice in upcoming):
        raise ValueError("Your next renewal is already paid or has a payment in progress. "
                         "Change add-ons after it starts, or contact Hub1z.")
    addon.cancel_at_period_end = units == 0
    addon.renewal_quantity = units or None
    db.session.flush()
    _reprice_renewals(operator, upcoming)
    audit("operator_addon.renewal_changed", addon.id, actor_id, module=addon.module.code, units=units)


def _upcoming_renewals(operator, subscription):
    """Renewal invoices for a period that has not started yet."""
    if not subscription.current_period_end:
        return []
    return PlatformInvoice.query.filter_by(operator_id=operator.id, kind="renewal").filter(
        PlatformInvoice.status.in_((*OPEN, PlatformInvoiceStatus.PAID)),
        PlatformInvoice.period_start > subscription.current_period_end).all()


def _reprice_renewals(operator, renewals):
    profile = PlatformProfile.get()
    for invoice in renewals:
        lines, addons = _renewal_lines(operator, invoice.activation["terms"], invoice.activation["cycle"])
        same_state = bool(profile.gst_state and invoice.gst_state and profile.gst_state == invoice.gst_state)
        for name, value in _amounts(lines, invoice.tax_rate, same_state).items():
            setattr(invoice, name, value)
        invoice.activation = dict(invoice.activation, addons=addons)


def run_jobs(today=None):
    today = today or date.today()
    created = 0
    profile = PlatformProfile.get()
    for subscription in OperatorSubscription.query.filter_by(status="active").all():
        if not subscription.current_period_end:
            continue
        operator = Operator.query.execution_options(skip_operator_filter=True).filter_by(id=subscription.operator_id).one()
        record_usage_snapshot(operator.id, today)
        _bill_usage(operator, subscription, today)
        if today < subscription.current_period_end - timedelta(days=profile.renewal_notice_days):
            continue
        start = subscription.current_period_end + timedelta(days=1)
        paid_renewal = PlatformInvoice.query.filter_by(operator_id=operator.id, kind="renewal",
                                                      period_start=start, status=PlatformInvoiceStatus.PAID).first()
        if paid_renewal and start <= today:
            _activate(paid_renewal, today)
            continue
        tier = db.session.get(PricingTier, subscription.scheduled_tier_id or subscription.tier_id)
        if tier is None:
            continue
        terms = subscription.scheduled_terms if subscription.scheduled_tier_id else paid_terms(subscription)
        if not terms:
            terms = snapshot(tier, subscription)
        try:
            validate_capacity(operator, terms, strict=bool(subscription.scheduled_tier_id))
        except ValueError:
            if subscription.scheduled_tier_id:
                subscription.scheduled_tier_id = None
                subscription.scheduled_billing_cycle = None
                subscription.scheduled_terms = None
                terms = paid_terms(subscription)
            else:
                continue
        cycle = subscription.scheduled_billing_cycle or subscription.billing_cycle
        key = f"renewal:{operator.id}:{start.isoformat()}"
        if PlatformInvoice.query.filter_by(idempotency_key=key).first():
            continue
        end = start + relativedelta(years=1 if cycle == "annual" else 0, months=1 if cycle == "monthly" else 0) - timedelta(days=1)
        lines, addons = _renewal_lines(operator, terms, cycle)
        invoice = _invoice(operator, lines, start, end, "renewal", {"terms": terms, "cycle": cycle, "addons": addons}, key, today)
        invoice.due_date = start
        created += 1
    for invoice in PlatformInvoice.query.filter(PlatformInvoice.status == PlatformInvoiceStatus.ISSUED,
                                                PlatformInvoice.due_date < today).all():
        invoice.status = PlatformInvoiceStatus.OVERDUE
    db.session.commit()
    return created


def _bill_usage(operator, subscription, today):
    start, paid_end = subscription.current_period_start, subscription.current_period_end
    if not start:
        return None
    terms = paid_terms(subscription)
    if terms.get("all_features"):
        return None
    month = 0
    while start + relativedelta(months=month) <= paid_end:
        window_start = start + relativedelta(months=month)
        window_end = min(start + relativedelta(months=month + 1) - timedelta(days=1), paid_end)
        if window_end >= today:
            break
        _bill_usage_period(operator, terms, window_start, window_end, today)
        month += 1


def _bill_usage_period(operator, terms, start, end, today):
    key = f"usage:{operator.id}:{start.isoformat()}:{end.isoformat()}"
    if PlatformInvoice.query.filter_by(idempotency_key=key).first():
        return None
    records = OperatorUsageSnapshot.query.filter(OperatorUsageSnapshot.operator_id == operator.id,
        OperatorUsageSnapshot.recorded_on >= start, OperatorUsageSnapshot.recorded_on <= end).order_by(
        OperatorUsageSnapshot.recorded_on).all()
    if not records:
        return None
    method = terms.get("seat_usage_method", "maximum_during_billing_period")
    seats = max(record.active_contracted_seats for record in records)
    if method == "end_of_period_usage":
        seats = records[-1].active_contracted_seats
    elif method == "average_daily_usage":
        daily = {record.recorded_on: record.active_contracted_seats for record in records}
        value, total = 0, 0
        for offset in range((end - start).days + 1):
            value = daily.get(start + timedelta(days=offset), value)
            total += value
        seats = Decimal(total) / ((end - start).days + 1)
    locations = max(record.active_locations for record in records)
    lines = []
    for name, count in (("seat", seats), ("location", locations)):
        included = terms.get("included_active_contracted_seats" if name == "seat" else "included_locations")
        if included is None or terms.get(f"{name}_overage_policy") != "allow_and_charge":
            continue
        extra = max(count - included, 0)
        rate = money(terms.get(f"additional_{name}_rate"))
        if extra > 0 and rate > 0:
            lines.append({"description": f"Extra contracted {name}s ({extra:g}) in arrears", "amount": money(extra * rate)})
    if not lines:
        return None
    return _invoice(operator, lines, start, end, "usage", key=key, today=today)