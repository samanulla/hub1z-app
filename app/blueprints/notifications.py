from datetime import datetime
from urllib.parse import urlsplit
from flask import Blueprint, jsonify, redirect, render_template, request, url_for, abort
from flask_login import current_user, login_required
from ..extensions import db
from ..models import Notification
from ..services.notifications import user_notifications, summary

notifications_bp = Blueprint("notifications", __name__)


@notifications_bp.route("/")
@login_required
def index():
    state = request.args.get("state", "all")
    query = user_notifications(current_user)
    if state == "unread":
        query = query.filter(Notification.read_at.is_(None))
    elif state == "read":
        query = query.filter(Notification.read_at.isnot(None))
    rows = query.order_by(Notification.created_at.desc(), Notification.id.desc()).paginate(per_page=30, error_out=False)
    return render_template("notifications.html", rows=rows, state=state)


@notifications_bp.route("/summary")
@login_required
def badge():
    data = summary(current_user)
    return jsonify(unread=data["unread"], items=[{"id": item.id, "title": item.title,
                   "body": item.body or "", "unread": item.read_at is None,
                   "open_url": url_for("notifications.update", notification_id=item.id, action="open")} for item in data["items"]])


@notifications_bp.route("/<int:notification_id>/<action>", methods=["POST"])
@login_required
def update(notification_id, action):
    notification = user_notifications(current_user).filter_by(id=notification_id).first_or_404()
    if action not in ("read", "unread", "open"):
        abort(404)
    notification.read_at = None if action == "unread" else datetime.utcnow()
    db.session.commit()
    if action == "open":
        target = urlsplit(notification.href)
        if not target.scheme and not target.netloc and notification.href.startswith("/") and not notification.href.startswith("//") and "\\" not in notification.href:
            return redirect(notification.href)
    return redirect(url_for("notifications.index"))


@notifications_bp.route("/read-all", methods=["POST"])
@login_required
def read_all():
    user_notifications(current_user).filter(Notification.read_at.is_(None)).update({"read_at": datetime.utcnow()}, synchronize_session=False)
    db.session.commit()
    return redirect(url_for("notifications.index"))