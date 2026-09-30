"""Operator resolver.

Responsibilities:
1. On every request, resolve the incoming `Host` header to an Operator row and
   stash it on ``flask.g.operator`` so downstream code can read operator-specific
   config (currency, tz, tax, branding).
2. Auto-scope all SQLAlchemy ORM queries against ``OperatorScoped`` models so
   they only see rows belonging to ``g.operator``. This is defence-in-depth on
   top of manual filtering.

Deployment modes:
- ``shared``   — one deployment serves many operators; operator is resolved from
   the ``Host`` header (subdomain or custom domain).
- ``dedicated`` — one deployment per operator; the operator is pinned via the
   ``OPERATOR_ID`` env var. Domain lookup is skipped.

For CLI commands / migrations / pytest fixtures that run outside a request
context, no operator filter is applied — callers are expected to know what
they're doing.
"""
from __future__ import annotations

from flask import Flask, abort, g, request, has_request_context
from flask_login import current_user, logout_user
from sqlalchemy import event
from sqlalchemy.orm import Session, with_loader_criteria

from ..extensions import db
from ..models.operator import Operator, OperatorScoped


_scoped_classes_cache: list[type] | None = None

# Areas that only make sense inside one operator's workspace.
_OPERATOR_BLUEPRINTS = {"admin", "company", "member", "book", "community", "api", "checkin"}


@event.listens_for(Session, "before_flush")
def _stamp_operator(session, flush_context, instances):
    """New operator-owned rows get the request's operator, so no screen can forget it."""
    if not has_request_context():
        return
    oid = getattr(g, "operator_id", None)
    if oid is None:
        return
    for obj in session.new:
        if isinstance(obj, OperatorScoped) and obj.operator_id is None:
            obj.operator_id = oid


def _operator_scoped_classes() -> list[type]:
    global _scoped_classes_cache
    if _scoped_classes_cache is None:
        _scoped_classes_cache = [
            m.class_ for m in db.Model.registry.mappers
            if isinstance(m.class_, type)
            and issubclass(m.class_, OperatorScoped)
            and m.class_ is not OperatorScoped
        ]
    return _scoped_classes_cache


def install(app: Flask) -> None:
    @app.before_request
    def _resolve_operator():
        if request.path == "/healthz":
            g.operator, g.operator_id = None, None
            return
        mode = (app.config.get("DEPLOY_MODE") or "shared").lower()
        if mode == "dedicated":
            tid = app.config.get("OPERATOR_ID")
            if tid:
                g.operator = db.session.get(Operator, int(tid))
                g.operator_id = int(tid) if g.operator else None
                return

        host = (request.host or "").split(":")[0].lower()
        base = (app.config.get("PLATFORM_BASE_DOMAIN") or "hub1z.com").lower()
        t = Operator.resolve(host)
        if t is None and host in ("localhost", "127.0.0.1") and host != base and (app.debug or app.testing):
            # Local-dev convenience only (never in production): bare localhost
            # falls back to the first operator. A genuinely unmatched *real*
            # domain (including the platform's own apex, e.g. hub1z.com)
            # must resolve to no operator — that's what tells index() to show
            # the platform's own marketing page instead of an operator's.
            t = Operator.default()
        elif t is None:
            if host != base and host != f"www.{base}":
                # Any other unmatched host — including a *.hub1z.com
                # subdomain that isn't a real operator, or a stray custom
                # domain — gets a friendly "no such workspace" page instead
                # of silently falling through to the platform's marketing
                # page, or a bare 404 with no way back. Links on that page
                # are absolute (this host has no working url_for('index')).
                from flask import render_template, make_response
                body = render_template("errors/workspace_not_found.html",
                                       base_domain=base, requested_host=host)
                return make_response(body, 404)
        g.operator = t
        g.operator_id = t.id if t is not None else None

    @app.before_request
    def _enforce_operator_boundary():
        oid = getattr(g, "operator_id", None)
        # Without an operator the query filter is off, so operator areas must not run.
        if oid is None and request.blueprint in _OPERATOR_BLUEPRINTS:
            abort(404)
        # A session only works on its own operator's host (platform staff: the apex).
        if current_user.is_authenticated and current_user.operator_id != oid:
            logout_user()
            abort(403)

    @event.listens_for(Session, "do_orm_execute")
    def _apply_operator_filter(orm_execute_state):
        if not orm_execute_state.is_select:
            return
        if orm_execute_state.execution_options.get("skip_operator_filter"):
            return
        if not has_request_context():
            return
        tid = getattr(g, "operator_id", None)
        if tid is None:
            return

        opts = []
        for cls in _operator_scoped_classes():
            opts.append(
                with_loader_criteria(
                    cls,
                    cls.operator_id == tid,
                    include_aliases=True,
                )
            )
        if opts:
            orm_execute_state.statement = orm_execute_state.statement.options(*opts)
