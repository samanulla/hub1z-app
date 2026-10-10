"""Who owns the business, and who is setting up the account on their behalf.

The signed-up user is often a representative in India, so the owner's details and, where needed, the owner's
authorisation are captured separately and checked before the operator moves to a paid plan.
"""
from __future__ import annotations

import re
from datetime import datetime

from ..models import Document, DocumentKind

ROLE_OWNER = "owner_director"
ROLE_REP = "representative"
ROLE_CHOICES = [(ROLE_OWNER, "I am the owner, director, partner or proprietor"),
                (ROLE_REP, "I am an authorised representative setting this up for the owner")]
DOC_PAN = "owner_pan_card"
DOC_ID = "owner_id_proof"
DOC_AUTH = "authorisation_letter"
DOC_LABELS = {
    DOC_PAN: "Owner PAN card",
    DOC_ID: "Owner ID proof (passport, driving licence, voter ID, or Aadhaar with the number masked)",
    DOC_AUTH: "Authorisation letter on the business letterhead, signed by the owner or director",
}
FIELDS = ("owner_setup_role", "rep_designation", "owner_name", "owner_designation", "owner_mobile", "owner_email",
          "owner_pan", "rep_declaration_at", "rep_declaration_by")
MOBILE = re.compile(r"^[6-9]\d{9}$")
PAN = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")


def clean_mobile(value: str | None) -> str:
    digits = re.sub(r"\D", "", value or "")
    return digits[-10:] if len(digits) >= 10 else digits


def mobile_ok(value: str | None) -> bool:
    return bool(MOBILE.match(clean_mobile(value)))


def pan_ok(value: str | None) -> bool:
    return bool(PAN.match((value or "").strip().upper()))


def latest_documents(operator_id: int) -> dict[str, Document]:
    rows = (Document.query.execution_options(skip_operator_filter=True)
            .filter(Document.operator_id == operator_id, Document.owner_type == "operator",
                    Document.kind == DocumentKind.KYC, Document.tag.in_(tuple(DOC_LABELS)))
            .order_by(Document.created_at, Document.id).all())
    return {row.tag: row for row in rows}


def details(operator) -> dict:
    return {key: (operator.profile_details or {}).get(key) for key in FIELDS}


def status(operator) -> dict:
    """What is still missing before this operator can move to a paid plan."""
    data = details(operator)
    docs = latest_documents(operator.id)
    rep = data["owner_setup_role"] == ROLE_REP
    missing = []
    if data["owner_setup_role"] not in (ROLE_OWNER, ROLE_REP):
        missing.append("Say whether you are the owner or an authorised representative")
    if not (data["owner_name"] or "").strip():
        missing.append("Owner or director name")
    if not mobile_ok(data["owner_mobile"]):
        missing.append("Owner mobile number")
    if "@" not in (data["owner_email"] or ""):
        missing.append("Owner email")
    if rep and not data["rep_declaration_at"]:
        missing.append("Representative declaration")
    for tag in (DOC_PAN, DOC_ID) + ((DOC_AUTH,) if rep else ()):
        if tag not in docs:
            missing.append(f"Upload: {DOC_LABELS[tag].split(' (')[0]}")
    return {"complete": not missing, "missing": missing, "role": data["owner_setup_role"], "docs": docs,
            "representative": rep}


def declare(operator, user_name: str) -> None:
    saved = dict(operator.profile_details or {})
    saved["rep_declaration_at"] = datetime.utcnow().isoformat(timespec="seconds")
    saved["rep_declaration_by"] = user_name
    operator.profile_details = saved
