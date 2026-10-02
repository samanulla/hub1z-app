"""Email sending + secure signed tokens for password reset / invitations.

Uses Flask-Mail (SMTP) — works with local dev, SES SMTP, SendGrid, etc.
No separate DB table needed: tokens are self-contained + expiry-signed via itsdangerous.
"""
from __future__ import annotations

from typing import Any

from flask import current_app, render_template
from flask_mail import Message
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from markupsafe import escape

from ..extensions import mail


def _serializer(salt: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt=salt)


def make_token(payload: Any, purpose: str) -> str:
    return _serializer(f"cowork-{purpose}").dumps(payload)


def read_token(token: str, purpose: str, max_age_seconds: int) -> Any | None:
    try:
        return _serializer(f"cowork-{purpose}").loads(token, max_age=max_age_seconds)
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
    destination, redirected = _destination(recipient)
    if redirected:
        subject = f"[for {recipient}] {subject}"
        body_txt = f"Originally addressed to: {recipient}\n\n{body_txt}"
        if body_html:
            body_html = f"<p><em>Originally addressed to: {escape(recipient)}</em></p>{body_html}"
    msg = Message(subject=subject, recipients=[destination],
                  body=body_txt, html=body_html)
    if redirected:
        msg.extra_headers = {"X-Original-To": recipient}
    if current_app.config.get("MAIL_SUPPRESS_SEND"):
        current_app.logger.info("MAIL SUPPRESSED to=%s subject=%s\n%s",
                                destination, subject, body_txt)
        return
    mail.send(msg)
