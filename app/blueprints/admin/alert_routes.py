"""Operator alerts: renewals, lock-ins, move-outs, overdue invoices and other things to act on."""
from __future__ import annotations

from datetime import date

from flask import g, render_template, request

from ...models import Subscription
from ...services import alerts as svc
from ...services.pdf_docs import address_letter_response
from ...utils.decorators import admin_required

FILTERS = [("all", "Everything"), ("renewal", "Renewals"), ("lock_in", "Lock-ins"), ("leaving", "Move-outs"),
           ("overdue", "Overdue"), ("revision", "Rate revisions")]


def register_alert_routes(bp):

    @bp.route("/alerts")
    @admin_required
    def alerts():
        kind = request.args.get("kind", "all")
        items = svc.operator_alerts(g.operator_id)
        counts = {k: sum(1 for i in items if i["kind"] == k) for k, _ in FILTERS}
        counts["all"] = len(items)
        shown = items if kind == "all" else [i for i in items if i["kind"] == kind]
        return render_template("admin/alerts.html", items=shown, counts=counts, kind=kind, filters=FILTERS,
                               today=date.today())

    @bp.route("/subscriptions/<int:sub_id>/address-letter.pdf")
    @admin_required
    def subscription_address_letter(sub_id: int):
        return address_letter_response(Subscription.query.get_or_404(sub_id))
