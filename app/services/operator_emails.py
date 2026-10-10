"""Operator lifecycle emails: welcome after sign-up, congratulations after the first paid plan, and on-screen samples."""
from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace

from flask import current_app, has_request_context, render_template
from sqlalchemy import event
from sqlalchemy.orm import Session

from ..extensions import db
from ..models import Operator, PlatformProfile, PricingTier, TierStatus, User, UserRole
from . import mail_service
from .formatting import format_inr
from .pricing_page import tier_feature_names, tier_limit_lines, trial_days

SESSION_KEY = "operator_upgrade_emails"


def login_url(operator) -> str:
    """Absolute sign-in link; falls back to the production scheme when there is no request (scheduled jobs)."""
    if has_request_context():
        from .operator_urls import workspace_url
        return workspace_url(operator, "/auth/login")
    return f"https://{operator.primary_domain}/auth/login"


def owner_of(operator_id: int) -> User | None:
    return (User.query.execution_options(skip_operator_filter=True)
            .filter(User.operator_id == operator_id, User.role == UserRole.SUPER_ADMIN, User.is_active.is_(True))
            .order_by(User.id).first())


def _tier_by_key(key: str | None) -> PricingTier | None:
    return PricingTier.query.filter_by(key=key).first() if key else None


def higher_tiers(sort_order: int, limit: int = 2) -> list[dict]:
    """Plans above the current one, as short notes for a quiet 'when you grow' line."""
    rows = (PricingTier.query.filter(PricingTier.status == TierStatus.ACTIVE, PricingTier.is_active.is_(True),
                                     PricingTier.sort_order > sort_order, PricingTier.key != "marketplace_partner",
                                     PricingTier.key != "scale")
            .order_by(PricingTier.sort_order).limit(limit).all())
    return [{"name": t.name, "blurb": _blurb(t)} for t in rows]


def _blurb(tier: PricingTier) -> str:
    lines = [line[:1].lower() + line[1:] for line in tier_limit_lines(tier)[:2]]
    return "includes " + " and ".join(lines) if lines else ""


def _person(user) -> SimpleNamespace:
    return SimpleNamespace(full_name=user.full_name, email=user.email)


def _operator_view(operator) -> SimpleNamespace:
    return SimpleNamespace(name=operator.name, slug=operator.slug, primary_domain=operator.primary_domain,
                           plan_tier=operator.plan_tier)


def welcome_context(operator, owner) -> dict:
    profile = PlatformProfile.peek()
    trial_tier = _tier_by_key(profile.trial_tier_key if profile else "growth")
    on_trial = operator.trial_ends_at is not None
    return {
        "user": _person(owner), "operator": _operator_view(operator), "login_url": login_url(operator),
        "plan_label": "Free trial" if on_trial else "Free plan",
        "trial_tier_name": trial_tier.name if trial_tier else None,
        "trial_days": trial_days(),
        "trial_ends": operator.trial_ends_at.strftime("%d %B %Y") if operator.trial_ends_at else None,
        "higher_tiers": higher_tiers(trial_tier.sort_order if trial_tier else 0),
        "support_email": current_app.config.get("PLATFORM_SUPPORT_EMAIL"), "operator_name": "Hub1z",
    }


def upgrade_context(operator, owner, tier, cycle: str, invoice) -> dict:
    highlights = tier_limit_lines(tier) + tier_feature_names(tier)[:4]
    return {
        "user": _person(owner), "operator": _operator_view(operator), "login_url": login_url(operator),
        "tier_name": tier.name, "cycle_label": "billed annually" if cycle == "annual" else "billed monthly",
        "period_end": invoice.period_end.strftime("%d %B %Y") if invoice is not None else None,
        "invoice_number": invoice.number if invoice is not None else None,
        "invoice_amount": format_inr(invoice.amount) if invoice is not None else None,
        "plan_highlights": highlights, "higher_tiers": higher_tiers(tier.sort_order, limit=1),
        "support_email": current_app.config.get("PLATFORM_SUPPORT_EMAIL"), "operator_name": "Hub1z",
    }


def _deliver(subject: str, recipient: str, template: str, context: dict) -> None:
    try:
        mail_service.send(subject, recipient, template, **context)
    except Exception:  # noqa: BLE001 - these are courtesy emails; the sign-up or payment must never fail on them
        current_app.logger.exception("Operator email %s to %s failed", template, recipient)


def send_welcome(operator, owner=None) -> None:
    if operator.plan_tier == "marketplace_partner":
        return
    owner = owner or owner_of(operator.id)
    if owner is None:
        return
    _deliver(f"Welcome to Hub1z, {operator.name}", owner.email, "operator_welcome", welcome_context(operator, owner))


def queue_upgrade(operator, tier, cycle: str, invoice) -> None:
    """Called while a plan is being activated; the email goes out only if the surrounding transaction commits."""
    owner = owner_of(operator.id)
    if owner is None:
        return
    pending = db.session.info.setdefault(SESSION_KEY, [])
    pending.append((owner.email, f"{operator.name} is now on {tier.name}",
                    upgrade_context(operator, owner, tier, cycle, invoice)))


@event.listens_for(Session, "after_commit")
def _send_queued_upgrades(session) -> None:
    pending = session.info.pop(SESSION_KEY, None)
    for recipient, subject, context in pending or []:
        _deliver(subject, recipient, "operator_upgraded", context)


@event.listens_for(Session, "after_rollback")
def _drop_queued_upgrades(session) -> None:
    session.info.pop(SESSION_KEY, None)


# ----------------------------------------------------------- on-screen samples --

def _sample_tiers() -> list[dict]:
    return [{"name": "Growth", "blurb": "includes up to 3 locations and unlimited document storage"},
            {"name": "Scale", "blurb": "includes up to 10 locations and priority support"}]


def sample_emails() -> list[dict]:
    """The four operator emails rendered with made-up data, for the development preview page."""
    person = SimpleNamespace(full_name="Priya Raman", email="priya@lotusworks.in")
    workspace = SimpleNamespace(name="Lotus Works", slug="lotusworks", primary_domain="lotusworks.hub1z.com",
                                plan_tier="starter")
    common = {"user": person, "operator": workspace, "login_url": "https://lotusworks.hub1z.com/auth/login",
              "support_email": "support@hub1z.com"}
    ends = date.today().replace(day=1)
    samples = [
        ("invite", "1. Invitation: set your password", "Set up Lotus Works on Hub1z", "platform_operator_invite",
         {**common, "accept_url": "https://hub1z.com/platform/operators/accept/eyJhbGciOi...", "ttl_days": 7}),
        ("welcome", "2. After sign-up: welcome to the free trial", "Welcome to Hub1z, Lotus Works", "operator_welcome",
         {**common, "plan_label": "Free trial", "trial_tier_name": "Growth", "trial_days": 14,
          "trial_ends": datetime.utcnow().strftime("%d %B %Y"), "higher_tiers": _sample_tiers()[:2]}),
        ("upgraded", "3. After the first payment: congratulations", "Lotus Works is now on Growth",
         "operator_upgraded",
         {**common, "tier_name": "Growth", "cycle_label": "billed monthly", "period_end": ends.strftime("%d %B %Y"),
          "invoice_number": "HUB-261008-3F9A2C", "invoice_amount": "₹11,800",
          "plan_highlights": ["Up to 3 locations", "Attendance and QR check-in", "Payroll and expenses",
                              "5 GB document storage"], "higher_tiers": _sample_tiers()[1:]}),
    ]
    out = []
    for key, title, subject, template, ctx in samples:
        out.append({"key": key, "title": title, "subject": subject, "to": person.email,
                    "html": render_template(f"emails/{template}.html", **ctx),
                    "text": render_template(f"emails/{template}.txt", **ctx)})
    return out
