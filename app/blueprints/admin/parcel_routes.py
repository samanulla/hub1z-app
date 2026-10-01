"""Reception: log mail and parcels, tell the recipient, and record the hand-over."""
from __future__ import annotations

from datetime import datetime, timedelta

from flask import flash, g, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy import or_

from ...extensions import db
from ...models import Company, Parcel, User
from ...models.parcel import COLLECTED, PARCEL_KINDS, RETURNED, WAITING
from ...services import parcels as svc
from ...utils.decorators import admin_required
from ..checkin import locations_for


def register_parcel_routes(bp):

    @bp.route("/parcels")
    @admin_required
    def parcels():
        status = request.args.get("status", WAITING)
        q = (request.args.get("q") or "").strip()
        rows = Parcel.query.filter(Parcel.operator_id == g.operator_id)
        if status in (WAITING, COLLECTED, RETURNED):
            rows = rows.filter(Parcel.status == status)
        if q:
            like = f"%{q}%"
            rows = (rows.outerjoin(User, Parcel.user_id == User.id).outerjoin(Company, Parcel.company_id == Company.id)
                    .filter(or_(User.full_name.ilike(like), Company.name.ilike(like), Parcel.reference.ilike(like),
                                Parcel.sender.ilike(like), Parcel.carrier.ilike(like))))
        rows = rows.order_by(Parcel.received_at.desc()).limit(300).all()
        today_start = datetime.utcnow() - timedelta(hours=24)
        base = Parcel.query.filter(Parcel.operator_id == g.operator_id)
        stats = {
            "waiting": base.filter(Parcel.status == WAITING).count(),
            "stale": svc.stale_count(g.operator_id),
            "received_today": base.filter(Parcel.received_at >= today_start).count(),
            "collected_today": base.filter(Parcel.status == COLLECTED, Parcel.collected_at >= today_start).count(),
        }
        people, companies = svc.recipient_choices(g.operator_id)
        return render_template("admin/parcels.html", rows=rows, stats=stats, status=status, q=q, people=people,
                               companies=companies, kinds=PARCEL_KINDS, locations=locations_for(current_user),
                               stale_before=datetime.utcnow() - timedelta(days=svc.STALE_DAYS))

    @bp.route("/parcels/new", methods=["POST"])
    @admin_required
    def parcel_new():
        target = request.form.get("recipient", "")
        kind, _, raw_id = target.partition(":")
        user = company = None
        if kind == "user" and raw_id.isdigit():
            user = User.query.filter(User.id == int(raw_id), User.operator_id == g.operator_id).first()
        elif kind == "company" and raw_id.isdigit():
            company = Company.query.filter(Company.id == int(raw_id), Company.operator_id == g.operator_id).first()
        if user is None and company is None:
            flash("Choose who the item is for.", "warning")
            return redirect(url_for("admin.parcels"))
        locations = locations_for(current_user)
        location = next((l for l in locations if l.id == request.form.get("location_id", type=int)), None)
        location = location or (locations[0] if locations else None)
        item_kind = request.form.get("kind", "parcel")
        parcel = Parcel(
            operator_id=g.operator_id, user_id=user.id if user else None,
            company_id=user.company_id if user else company.id,
            location_id=location.id if location else None,
            kind=item_kind if item_kind in dict(PARCEL_KINDS) else "parcel",
            carrier=(request.form.get("carrier") or "").strip()[:60] or None,
            reference=(request.form.get("reference") or "").strip()[:120] or None,
            sender=(request.form.get("sender") or "").strip()[:120] or None,
            note=(request.form.get("note") or "").strip()[:255] or None,
            received_by_id=current_user.id,
        )
        db.session.add(parcel)
        db.session.flush()
        told = svc.notify(parcel, g.operator) if request.form.get("notify", "1") == "1" else False
        db.session.commit()
        message = f"Logged for {parcel.recipient_name}. Pickup code {parcel.pickup_code}."
        flash(message + (" They have been emailed." if told else " No email was sent."), "success")
        return redirect(url_for("admin.parcels"))

    @bp.route("/parcels/<int:parcel_id>/collect", methods=["POST"])
    @admin_required
    def parcel_collect(parcel_id: int):
        parcel = Parcel.query.filter_by(id=parcel_id, operator_id=g.operator_id, status=WAITING).first_or_404()
        code = (request.form.get("code") or "").strip()
        if code and code != parcel.pickup_code:
            flash("That pickup code does not match. Check it with the person collecting.", "warning")
            return redirect(url_for("admin.parcels"))
        parcel.status = COLLECTED
        parcel.collected_at = datetime.utcnow()
        parcel.collected_by = (request.form.get("collected_by") or "").strip()[:120] or parcel.recipient_name
        parcel.handed_over_by_id = current_user.id
        db.session.commit()
        flash(f"Handed over to {parcel.collected_by}.", "success")
        return redirect(url_for("admin.parcels"))

    @bp.route("/parcels/<int:parcel_id>/return", methods=["POST"])
    @admin_required
    def parcel_return(parcel_id: int):
        parcel = Parcel.query.filter_by(id=parcel_id, operator_id=g.operator_id, status=WAITING).first_or_404()
        parcel.status = RETURNED
        parcel.collected_at = datetime.utcnow()
        parcel.handed_over_by_id = current_user.id
        db.session.commit()
        flash("Marked as returned to sender.", "info")
        return redirect(url_for("admin.parcels"))

    @bp.route("/parcels/<int:parcel_id>/remind", methods=["POST"])
    @admin_required
    def parcel_remind(parcel_id: int):
        parcel = Parcel.query.filter_by(id=parcel_id, operator_id=g.operator_id, status=WAITING).first_or_404()
        if svc.notify(parcel, g.operator):
            db.session.commit()
            flash(f"Reminder sent to {parcel.recipient_name}.", "success")
        else:
            flash("The reminder could not be emailed.", "warning")
        return redirect(url_for("admin.parcels"))
