"""Workspace slug rules shared by the sign-up, invite and edit forms and the live availability check."""
from __future__ import annotations

import re

from flask import current_app

from ..models import Operator

SLUG_RE = re.compile(r"^[a-z0-9-]+$")
RESERVED = frozenset({"www", "app", "admin", "api", "platform", "support", "mail", "static", "spaces", "hub",
                      "billing", "help", "status", "docs", "blog", "login", "auth"})


def check(slug: str | None, exclude_id: int | None = None) -> tuple[bool, str]:
    """(available, message) for a candidate workspace slug."""
    slug = (slug or "").strip().lower()
    if len(slug) < 3 or len(slug) > 40:
        return False, "Use 3 to 40 characters."
    if not SLUG_RE.match(slug) or slug.startswith("-") or slug.endswith("-"):
        return False, "Lowercase letters, digits and hyphens only."
    if slug in RESERVED:
        return False, "That name is reserved. Please choose another."
    base = current_app.config.get("PLATFORM_BASE_DOMAIN", "hub1z.com")
    query = Operator.query.execution_options(skip_operator_filter=True)
    if exclude_id:
        query = query.filter(Operator.id != exclude_id)
    if query.filter((Operator.slug == slug) | (Operator.primary_domain == f"{slug}.{base}")).first():
        return False, "That address is already taken."
    return True, f"Available: {slug}.{base}"
