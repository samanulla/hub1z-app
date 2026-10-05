"""Email sending + secure signed tokens for password reset / invitations.

Uses Flask-Mail (SMTP) — works with local dev, SES SMTP, SendGrid, etc.
No separate DB table needed: tokens are self-contained + expiry-signed via itsdangerous.
"""
from __future__ import annotations

from typing import Any
from hashlib import sha256
from email.utils import parseaddr
from pathlib import Path

from flask import current_app, render_template, g, has_request_context
from flask_mail import Message
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from markupsafe import escape

from ..extensions import mail


def _serializer(salt: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt=salt)


def make_token(payload: Any, purpose: str) -> str:
    if purpose in USER_INVITE_ROLES or purpose == "password-reset":
        from ..extensions import db
        from ..models import User
        user = db.session.get(User, int(payload))
        payload = {"user_id": user.id, "stamp": sha256((user.password_hash + user.email).encode()).hexdigest()}
    return _serializer(f"cowork-{purpose}").dumps(payload)


USER_INVITE_ROLES = {"employee-invite": "employee", "operator-member-invite": "individual",
                     "operator-company-invite": "company_admin", "operator-team-invite": ("manager", "location_manager"),
                     "platform-operator-invite": "super_admin"}


def read_token(token: str, purpose: str, max_age_seconds: int) -> Any | None:
    try:
        payload = _serializer(f"cowork-{purpose}").loads(token, max_age=max_age_seconds)
        if purpose not in USER_INVITE_ROLES and purpose != "password-reset":
            return payload
        from ..extensions import db
        from ..models import User
        user_id = payload.get("user_id") if isinstance(payload, dict) else payload
        if not isinstance(user_id, int):
            return None
        user = db.session.get(User, user_id)
        roles = USER_INVITE_ROLES.get(purpose)
        if not user or (roles and (user.invite_revoked or user.role.value not in (roles if isinstance(roles, tuple) else (roles,)))):
            return None
        if user.company and user.company.status.value in ("suspended", "churned"):
            return None
        if has_request_context() and user.operator_id != getattr(g, "operator_id", None) and not (
                purpose in ("platform-operator-invite", "password-reset") and getattr(g, "operator_id", None) is None):
            return None
        if purpose == "password-reset" and not isinstance(payload, dict):
            return None
        if isinstance(payload, dict) and payload.get("stamp") != sha256((user.password_hash + user.email).encode()).hexdigest():
            return None
        return user.id
    except (BadSignature, SignatureExpired):
        return None


def _destination(recipient: str) -> tuple[str, bool]:
    """Where a message really goes. While SES approval is pending, bounces from real customer addresses are
    a risk, so everything outside Hub1z's own domains is rerouted to MAIL_REDIRECT_TO (unset = send normally)."""
    target = (current_app.config.get("MAIL_REDIRECT_TO") or "").strip()
    if not target:
        return recipient, False
    keep = {d.strip().lower() for d in (current_app.config.get("MAIL_REDIRECT_KEEP_DOMAINS") or "").split(",") if d.strip()}
    if recipient.rsplit("@", 1)[-1].lower() in keep:
        return recipient, False
    return target, True


def send(subject: str, recipient: str, template: str, **ctx: Any) -> None:
    """Render ``templates/emails/<template>.txt`` and .html and send via SMTP.

    Falls back to logging when MAIL_SUPPRESS_SEND is true (tests / dev).
    """
    body_txt = render_template(f"emails/{template}.txt", **ctx)
    try:
        body_html = render_template(f"emails/{template}.html", **ctx)
    except Exception:
        body_html = None
    body_txt += "\n\nPowered by Hub1z | https://hub1z.com\n"
    if body_html:
        body_html += ('<table role="presentation" style="margin-top:28px;border-top:1px solid #dde3e9;padding-top:12px">'
                      '<tr><td style="color:#546175;font-size:12px">Powered by '
                      '<a href="https://hub1z.com" style="color:#007f78;text-decoration:none">'
                      '<img src="cid:hub1z-mark" width="20" height="20" alt="Hub1z" '
                      'style="vertical-align:middle;border:0"> Hub1z</a></td></tr></table>')
    operator = ctx.get("operator") or (getattr(g, "operator", None) if has_request_context() else None)
    brand_name = ctx.get("operator_name") or getattr(operator, "name", None) or "Hub1z"
    if template == "employee_invite" and ctx.get("company"):
        brand_name = ctx["company"].name
    if template == "platform_operator_invite":
        brand_name = "Hub1z"
    sender = current_app.config.get("MAIL_DEFAULT_SENDER")
    if sender:
        address = sender[1] if isinstance(sender, (tuple, list)) else parseaddr(sender)[1]
        display_name = str(brand_name).replace("\r", " ").replace("\n", " ")
        sender = (display_name if display_name == "Hub1z" else f"{display_name} on Hub1z", address)
    destination, redirected = _destination(recipient)
    if redirected:
        subject = f"[for {recipient}] {subject}"
        body_txt = f"Originally addressed to: {recipient}\n\n{body_txt}"
        if body_html:
            body_html = f"<p><em>Originally addressed to: {escape(recipient)}</em></p>{body_html}"
    msg = Message(subject=subject, recipients=[destination],
                  body=body_txt, html=body_html, sender=sender)
    if body_html:
        icon = Path(current_app.static_folder) / "img/brand/png/hub1z-icon-small.png"
        msg.attach("hub1z.png", "image/png", icon.read_bytes(), disposition="inline", headers={"Content-ID": "<hub1z-mark>"})
    if redirected:
        msg.extra_headers = {"X-Original-To": recipient}
    if current_app.config.get("MAIL_SUPPRESS_SEND"):
        current_app.logger.info("MAIL SUPPRESSED to=%s subject=%s\n%s",
                                destination, subject, body_txt)
        return
    mail.send(msg)
