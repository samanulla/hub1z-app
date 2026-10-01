"""Mail and parcels at reception: who it is for, telling them, and handing it over."""
from __future__ import annotations

from datetime import datetime, timedelta

from flask import current_app

from ..extensions import db
from ..models import Company, Parcel, User, UserRole
from ..models.parcel import WAITING
from . import mail_service

MEMBER_ROLES = [UserRole.COMPANY_ADMIN, UserRole.EMPLOYEE, UserRole.INDIVIDUAL]
STALE_DAYS = 3


def recipient_emails(parcel: Parcel) -> list[str]:
    """The person it is addressed to; for a company-addressed item, the company's admins."""
    if parcel.user is not None:
        return [parcel.user.email]
    if parcel.company is not None:
        admins = User.query.filter(User.company_id == parcel.company_id, User.role == UserRole.COMPANY_ADMIN,
                                   User.is_active.is_(True)).all()
        return [u.email for u in admins] or ([parcel.company.billing_email] if parcel.company.billing_email else [])
    return []


def notify(parcel: Parcel, operator) -> bool:
    """Email the recipient; False when it could not be sent (the parcel is still logged)."""
    emails = recipient_emails(parcel)
    if not emails:
        return False
    try:
        for email in emails:
            mail_service.send(f"{parcel.kind_label} waiting for you at {operator.name}", email, "parcel_arrived",
                              parcel=parcel, operator=operator)
    except Exception:  # SMTP down or the address is refused; reception can still tell them
        current_app.logger.exception("parcel %s: notification email failed", parcel.id)
        return False
    parcel.notified_at = datetime.utcnow()
    return True


def waiting_query(**owner):
    return Parcel.query.filter_by(status=WAITING, **owner)


def stale_count(operator_id: int, now: datetime | None = None) -> int:
    now = now or datetime.utcnow()
    return (Parcel.query.filter(Parcel.operator_id == operator_id, Parcel.status == WAITING,
                                Parcel.received_at < now - timedelta(days=STALE_DAYS)).count())


def recipient_choices(operator_id: int) -> tuple[list[User], list[Company]]:
    people = (User.query.filter(User.operator_id == operator_id, User.role.in_(MEMBER_ROLES), User.is_active.is_(True))
              .order_by(User.full_name).all())
    companies = Company.query.filter(Company.operator_id == operator_id).order_by(Company.name).all()
    return people, companies
