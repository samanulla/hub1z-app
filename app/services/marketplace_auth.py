"""Marketplace customer sign-in: email one-time codes and a session that only exists on the marketplace host."""
from __future__ import annotations

import hmac
import secrets
from datetime import datetime, timedelta
from hashlib import sha256

from flask import current_app, session

from ..extensions import db
from ..models import MarketplaceCustomer
from . import mail_service

CODE_TTL = timedelta(minutes=10)
RESEND_AFTER = timedelta(seconds=60)
MAX_ATTEMPTS = 5
SESSION_KEY = "mc"


class SignInError(Exception):
    """Safe to show to the visitor."""


def _hash(email: str, code: str) -> str:
    key = current_app.config["SECRET_KEY"].encode()
    return hmac.new(key, f"{email}:{code}".encode(), sha256).hexdigest()


def request_code(email: str, name: str = "", phone: str = "") -> str:
    """Create the account if new, email a 6-digit code and return it (callers show it only in dev)."""
    email = email.strip().lower()
    now = datetime.utcnow()
    customer = MarketplaceCustomer.query.filter_by(email=email).first()
    if customer is None:
        if not name.strip():
            raise SignInError("Tell us your name to create your account.")
        customer = MarketplaceCustomer(email=email, full_name=name.strip()[:150], phone=(phone or "").strip()[:30] or None)
        db.session.add(customer)
    elif not customer.is_active:
        raise SignInError("This account can't sign in.")
    elif customer.otp_expires_at and customer.otp_expires_at - CODE_TTL + RESEND_AFTER > now:
        raise SignInError("A code was just sent. Wait a minute before asking for another.")
    code = f"{secrets.randbelow(10 ** 6):06d}"
    customer.otp_hash = _hash(email, code)
    customer.otp_expires_at = now + CODE_TTL
    customer.otp_attempts = 0
    db.session.commit()
    mail_service.send("Your Hub1z sign-in code", email, "marketplace_otp", name=customer.full_name, code=code,
                      ttl_minutes=int(CODE_TTL.total_seconds() // 60), operator_name="Hub1z")
    return code


def verify_code(email: str, code: str) -> MarketplaceCustomer:
    email = email.strip().lower()
    customer = MarketplaceCustomer.query.filter_by(email=email).first()
    if (customer is None or not customer.otp_hash or not customer.otp_expires_at
            or customer.otp_expires_at < datetime.utcnow() or customer.otp_attempts >= MAX_ATTEMPTS):
        raise SignInError("That code has expired. Ask for a new one.")
    customer.otp_attempts += 1
    if not hmac.compare_digest(customer.otp_hash, _hash(email, (code or "").strip())):
        db.session.commit()
        raise SignInError("That code isn't right.")
    customer.otp_hash = None
    customer.otp_expires_at = None
    customer.otp_attempts = 0
    customer.email_verified_at = customer.email_verified_at or datetime.utcnow()
    customer.auth_version = (customer.auth_version or 0) + 1
    db.session.commit()
    return customer


def sign_in(customer: MarketplaceCustomer) -> None:
    session.clear()
    session[SESSION_KEY] = f"{customer.id}:{customer.auth_version}"
    session.permanent = False


def sign_out() -> None:
    session.pop(SESSION_KEY, None)


def current_customer() -> MarketplaceCustomer | None:
    raw = session.get(SESSION_KEY)
    if not raw:
        return None
    try:
        cid, version = (int(p) for p in raw.split(":"))
    except ValueError:
        return None
    customer = db.session.get(MarketplaceCustomer, cid)
    if customer is None or not customer.is_active or (customer.auth_version or 0) != version:
        return None
    return customer
