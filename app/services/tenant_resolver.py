"""Tenant resolver.

Responsibilities:
1. On every request, resolve the incoming `Host` header to a Tenant row and
   stash it on ``flask.g.tenant`` so downstream code can read tenant-specific
   config (currency, tz, tax, branding).
2. Auto-scope all SQLAlchemy ORM queries against ``TenantScoped`` models so
   they only see rows belonging to ``g.tenant``. This is defence-in-depth on
   top of manual filtering.

Deployment modes:
- ``shared``   — one deployment serves many tenants; tenant is resolved from
   the ``Host`` header (subdomain or custom domain).
- ``dedicated`` — one deployment per tenant; the tenant is pinned via the
   ``TENANT_ID`` env var. Domain lookup is skipped.

For CLI commands / migrations / pytest fixtures that run outside a request
context, no tenant filter is applied — callers are expected to know what
they're doing.
"""
from __future__ import annotations

from flask import Flask, g, request, has_request_context
from sqlalchemy import event, or_
from sqlalchemy.orm import Session, with_loader_criteria

from ..extensions import db
from ..models.tenant import Tenant, TenantScoped


_scoped_classes_cache: list[type] | None = None


def _tenant_scoped_classes() -> list[type]:
    global _scoped_classes_cache
    if _scoped_classes_cache is None:
        _scoped_classes_cache = [
            m.class_ for m in db.Model.registry.mappers
            if isinstance(m.class_, type)
            and issubclass(m.class_, TenantScoped)
            and m.class_ is not TenantScoped
        ]
    return _scoped_classes_cache


def install(app: Flask) -> None:
    @app.before_request
    def _resolve_tenant():
        mode = (app.config.get("DEPLOY_MODE") or "shared").lower()
        if mode == "dedicated":
            tid = app.config.get("TENANT_ID")
            if tid:
                g.tenant = db.session.get(Tenant, int(tid))
                g.tenant_id = int(tid) if g.tenant else None
                return

        host = (request.host or "").split(":")[0].lower()
        t = Tenant.resolve(host)
        if t is None and host in ("localhost", "127.0.0.1"):
            # Local-dev convenience only: bare localhost with no DNS set up
            # falls back to the first tenant. A genuinely unmatched *real*
            # domain (including the platform's own apex, e.g. hub1z.com)
            # must resolve to no tenant — that's what tells index() to show
            # the platform's own marketing page instead of a tenant's.
            t = Tenant.default()
        g.tenant = t
        g.tenant_id = t.id if t is not None else None

    @event.listens_for(Session, "do_orm_execute")
    def _apply_tenant_filter(orm_execute_state):
        if not orm_execute_state.is_select:
            return
        if orm_execute_state.execution_options.get("skip_tenant_filter"):
            return
        if not has_request_context():
            return
        tid = getattr(g, "tenant_id", None)
        if tid is None:
            return

        opts = []
        for cls in _tenant_scoped_classes():
            opts.append(
                with_loader_criteria(
                    cls,
                    or_(cls.tenant_id == tid, cls.tenant_id.is_(None)),
                    include_aliases=True,
                )
            )
        if opts:
            orm_execute_state.statement = orm_execute_state.statement.options(*opts)
