"""Leads: stages, board numbers and stage moves, shared by the operator and Platform pages.

Platform leads have no operator (operator_id is NULL). Operator queries never see them, but Platform
queries are not filtered automatically, so every query goes through ``lead_query``.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

from flask import g

from ..extensions import db
from ..models import Lead, LeadActivity, User, UserRole

OPERATOR, PLATFORM = "operator", "platform"

# (key, label, chip colour). "lost" is kept off the board and shown in the list.
STAGES = {
    OPERATOR: [("new", "New", "tint-info"), ("contacted", "Contacted", "tint-brand"),
               ("tour", "Tour booked", "tint-warn"), ("proposal", "Proposal sent", "tint-neutral"),
               ("won", "Won", "tint-success"), ("lost", "Lost", "tint-danger")],
    PLATFORM: [("new", "New", "tint-info"), ("demo", "Demo booked", "tint-brand"),
               ("trial", "Trial running", "tint-warn"), ("negotiation", "Negotiation", "tint-neutral"),
               ("won", "Won", "tint-success"), ("lost", "Lost", "tint-danger")],
}
SOURCES = {
    OPERATOR: ["Website", "Walk-in", "Referral", "Google Ads", "Instagram", "Justdial", "Other"],
    PLATFORM: ["Website", "Webinar", "Referral", "LinkedIn", "Partner", "Other"],
}
TEMPERATURES = [("hot", "Hot", "tint-danger"), ("warm", "Warm", "tint-warn"), ("cold", "Cold", "tint-info")]
ACTIVITY_KINDS = [("note", "Note"), ("call", "Call"), ("email", "Email"), ("meeting", "Meeting")]
CLOSED = {"won", "lost"}


def stages(scope: str) -> list[tuple[str, str, str]]:
    return STAGES[scope]


def board_stages(scope: str) -> list[tuple[str, str, str]]:
    return [s for s in STAGES[scope] if s[0] != "lost"]


def stage_label(scope: str, key: str) -> str:
    return next((label for k, label, _ in STAGES[scope] if k == key), key)


def lead_query(scope: str):
    """Only this scope's leads, whatever the caller forgets to filter."""
    if scope == PLATFORM:
        return Lead.query.filter(Lead.operator_id.is_(None))
    return Lead.query.filter(Lead.operator_id == g.operator_id)


def owner_choices(scope: str) -> list[User]:
    if scope == PLATFORM:
        roles = [UserRole.PLATFORM_OWNER, UserRole.PLATFORM_MANAGER]
        q = User.query.filter(User.operator_id.is_(None))
    else:
        roles = [UserRole.SUPER_ADMIN, UserRole.MANAGER, UserRole.LOCATION_MANAGER]
        q = User.query.filter(User.operator_id == g.operator_id)
    return q.filter(User.role.in_(roles), User.is_active.is_(True)).order_by(User.full_name).all()


def due_state(lead: Lead, today: date) -> tuple[str, str]:
    """('late' | 'today' | 'ok' | 'none', short text) for the follow-up date of an open lead."""
    if lead.stage in CLOSED:
        return "none", (lead.closed_at.strftime("%d-%b-%Y") if lead.closed_at else "Closed")
    d = lead.next_follow_up
    if d is None:
        return "none", "No follow-up set"
    gap = (d - today).days
    if gap < 0:
        return "late", f"Overdue {-gap} day{'s' if gap != -1 else ''}"
    if gap == 0:
        return "today", "Due today"
    if gap == 1:
        return "ok", "Tomorrow"
    return "ok", d.strftime("%a %d %b")


def summary(leads: list[Lead], today: date | None = None, now: datetime | None = None) -> dict:
    """Numbers for the KPI tiles: open leads, pipeline, follow-ups due, 30-day conversion."""
    today = today or date.today()
    now = now or datetime.utcnow()
    open_leads = [l for l in leads if l.stage not in CLOSED]
    due = [l for l in open_leads if l.next_follow_up and l.next_follow_up <= today]
    overdue = [l for l in open_leads if l.next_follow_up and l.next_follow_up < today]
    since = now - timedelta(days=30)
    won = sum(1 for l in leads if l.stage == "won" and l.closed_at and l.closed_at >= since)
    lost = sum(1 for l in leads if l.stage == "lost" and l.closed_at and l.closed_at >= since)
    return {
        "open": len(open_leads),
        "pipeline": sum((Decimal(l.expected_value or 0) for l in open_leads), Decimal(0)),
        "due": len(due), "overdue": len(overdue),
        "won_30": won,
        "conversion": round(won * 100 / (won + lost)) if (won + lost) else None,
    }


def add_activity(lead: Lead, kind: str, body: str, user: User | None) -> LeadActivity:
    act = LeadActivity(lead=lead, operator_id=lead.operator_id, kind=kind, body=body,
                       created_by_id=user.id if user else None)
    db.session.add(act)
    return act


def move_stage(scope: str, lead: Lead, new_stage: str, user: User | None, reason: str | None = None) -> bool:
    """Move a lead to another stage and log it. False when the stage is unknown or unchanged."""
    if new_stage not in {k for k, _, _ in STAGES[scope]} or new_stage == lead.stage:
        return False
    old = lead.stage
    lead.stage = new_stage
    if new_stage in CLOSED:
        lead.closed_at = datetime.utcnow()
        lead.lost_reason = (reason or "").strip()[:200] or None if new_stage == "lost" else None
        if new_stage == "won":
            lead.next_follow_up = None
    else:
        lead.closed_at = None
        lead.lost_reason = None
    text = f"Moved from {stage_label(scope, old)} to {stage_label(scope, new_stage)}"
    if new_stage == "lost" and lead.lost_reason:
        text += f". Reason: {lead.lost_reason}"
    add_activity(lead, "stage", text, user)
    return True
