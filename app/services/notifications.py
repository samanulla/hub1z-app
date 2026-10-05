from datetime import datetime, timedelta
from flask import request, session
from flask_login import current_user
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from ..extensions import db
from ..models import (Notification, Announcement, User, UserRole, SupportTicket, TicketStatus, RoomBooking,
                      BookingStatus, Subscription, SubscriptionStatus, SeatAllocation, AllocationStatus,
                      PaymentSubmission, PaymentSubmissionStatus, Parcel, PlatformPaymentReport, PlatformInvoice,
                      PlatformInvoiceStatus)


def user_notifications(user):
    return Notification.query.execution_options(skip_operator_filter=True).filter_by(user_id=user.id, operator_id=user.operator_id)


def notify(user, event_key, kind, title, body, href):
    if not user.is_active:
        return 0
    insert = postgres_insert if db.engine.dialect.name == "postgresql" else sqlite_insert
    statement = insert(Notification).values(user_id=user.id, operator_id=user.operator_id, event_key=event_key,
                                            kind=kind, title=title[:200], body=body, href=href)
    result = db.session.execute(statement.on_conflict_do_nothing(index_elements=["user_id", "event_key"]))
    return result.rowcount


def active_users(operator_id):
    return User.query.execution_options(skip_operator_filter=True).filter_by(operator_id=operator_id, is_active=True).all()


def announcement_visible(user, post):
    if user.operator_id != post.operator_id:
        return False
    if post.location_id is None or user.role in (UserRole.SUPER_ADMIN, UserRole.MANAGER):
        return True
    if user.managed_location_id == post.location_id:
        return True
    allocations = SeatAllocation.query.execution_options(skip_operator_filter=True).filter_by(
        operator_id=user.operator_id, user_id=user.id, status=AllocationStatus.ACTIVE).all()
    if any(allocation.seat.location_id == post.location_id for allocation in allocations):
        return True
    owner = {"company_id": user.company_id} if user.company_id else {"user_id": user.id}
    subscriptions = Subscription.query.execution_options(skip_operator_filter=True).filter_by(
        operator_id=user.operator_id, status=SubscriptionStatus.ACTIVE, **owner).all()
    return any(sub.plan.location_scope.value == "all" or any(location.id == post.location_id for location in sub.plan.locations)
               for sub in subscriptions)


def announcement_added(post):
    for user in active_users(post.operator_id):
        if user.id != post.author_id and announcement_visible(user, post):
            notify(user, f"announcement:{post.id}", "announcement", post.title, post.body[:1000], f"/hub/announcements/{post.id}")


def ticket_changed(ticket, new=False):
    for user in active_users(ticket.operator_id):
        if new and user.is_admin and user.id != ticket.submitter_id:
            notify(user, f"ticket-new:{ticket.id}", "ticket", f"New support ticket: {ticket.subject}", ticket.body[:1000], "/hub/tickets")
        elif not new and user.id == ticket.submitter_id:
            notify(user, f"ticket:{ticket.id}:{ticket.status.value}:{ticket.updated_at.isoformat()}", "ticket",
                   f"Ticket updated: {ticket.subject}", f"Status: {ticket.status.value.replace('_', ' ').title()}", "/hub/tickets")


def sync_user(user, now=None):
    if not user.is_active or (user.company and user.company.status.value in ("suspended", "churned")):
        return
    now = now or datetime.utcnow()
    today = now.date()
    if user.operator_id is None:
        if user.has_platform_permission("billing"):
            for report in PlatformPaymentReport.query.filter_by(status="pending").all():
                notify(user, f"platform-payment:{report.id}", "payment", "Operator payment awaiting review", report.reference or "", "/platform/finance#payment-reports")
        return
    posts = Announcement.query.execution_options(skip_operator_filter=True).filter(
        Announcement.operator_id == user.operator_id, Announcement.published_at >= max(user.created_at, now - timedelta(days=30))).all()
    for post in posts:
        if post.author_id != user.id and announcement_visible(user, post):
            notify(user, f"announcement:{post.id}", "announcement", post.title, post.body[:1000], f"/hub/announcements/{post.id}")
    tickets = SupportTicket.query.execution_options(skip_operator_filter=True).filter_by(operator_id=user.operator_id).all()
    for ticket in tickets:
        if ticket.submitter_id == user.id and ticket.updated_at > ticket.created_at:
            notify(user, f"ticket:{ticket.id}:{ticket.status.value}:{ticket.updated_at.isoformat()}", "ticket",
                   f"Ticket updated: {ticket.subject}", f"Status: {ticket.status.value.replace('_', ' ').title()}", "/hub/tickets")
        elif user.is_admin and ticket.status in (TicketStatus.OPEN, TicketStatus.IN_PROGRESS) and ticket.submitter_id != user.id:
            notify(user, f"ticket-new:{ticket.id}", "ticket", f"New support ticket: {ticket.subject}", ticket.body[:1000], "/hub/tickets")
    meetings = RoomBooking.query.execution_options(skip_operator_filter=True).filter(
        RoomBooking.operator_id == user.operator_id, RoomBooking.user_id == user.id,
        RoomBooking.status == BookingStatus.CONFIRMED, RoomBooking.start_at > now,
        RoomBooking.start_at <= now + timedelta(minutes=30)).all()
    for meeting in meetings:
        minutes = max(1, int((meeting.start_at - now).total_seconds() // 60))
        notify(user, f"meeting:{meeting.id}:{meeting.start_at.isoformat()}", "meeting", f"Meeting in {minutes} minutes: {meeting.room.name}",
               meeting.title or "Your meeting-room booking starts soon.", "/book/calendar")
    from .alerts import subscription_items, overdue_items
    items = subscription_items(user.operator_id, today, links=False)
    for item in items:
        sub = item["sub"]
        owns = bool(user.company_id) and sub.company_id == user.company_id if user.is_company_admin else sub.user_id == user.id
        if user.is_admin or owns:
            href = "/admin/alerts" if user.is_admin else ("/company/subscriptions" if user.is_company_admin else "/me/")
            notify(user, item["key"], item["kind"], item["title"], item["detail"], href)
    for item in overdue_items(user.operator_id, today, links=False):
        invoice = item["invoice"]
        owns = bool(user.company_id) and invoice.company_id == user.company_id if user.is_company_admin else invoice.user_id == user.id
        if user.is_admin or owns:
            href = f"/admin/invoices/{invoice.id}" if user.is_admin else ("/company/invoices" if user.is_company_admin else "/me/invoices")
            notify(user, item["key"], "overdue", item["title"], item["detail"], href)
    if user.is_admin:
        for payment in PaymentSubmission.query.execution_options(skip_operator_filter=True).filter_by(
                operator_id=user.operator_id, status=PaymentSubmissionStatus.PENDING).all():
            notify(user, f"payment:{payment.id}", "payment", "Payment awaiting confirmation", payment.reference or "A member reported a payment.", "/admin/invoices")
        from ..models import Lead
        for lead in Lead.query.execution_options(skip_operator_filter=True).filter(
                Lead.operator_id == user.operator_id, Lead.stage.notin_(["won", "lost"]),
                Lead.next_follow_up <= today).all():
            notify(user, f"lead:{lead.id}:{lead.next_follow_up}", "lead", "Lead follow-up due", lead.name, "/admin/leads")
    parcels = Parcel.query.execution_options(skip_operator_filter=True).filter_by(operator_id=user.operator_id, status="waiting").all()
    for parcel in parcels:
        owns = bool(user.company_id) and parcel.company_id == user.company_id if user.is_company_admin else parcel.user_id == user.id
        if owns or (user.is_admin and parcel.received_at < now - timedelta(days=3)):
            href = "/admin/parcels" if user.is_admin else ("/company/parcels" if user.is_company_admin else "/me/parcels")
            notify(user, f"parcel:{parcel.id}", "parcel", "Parcel waiting for collection", f"Pickup code: {parcel.pickup_code}" if owns else parcel.recipient_name, href)
    if user.is_super_admin:
        for invoice in PlatformInvoice.query.filter(PlatformInvoice.operator_id == user.operator_id,
                PlatformInvoice.status.in_([PlatformInvoiceStatus.ISSUED, PlatformInvoiceStatus.OVERDUE])).all():
            notify(user, f"hub1z-invoice:{invoice.id}", "billing", "Hub1z subscription payment due", invoice.number, "/admin/hub1z-billing")


def run_jobs(now=None):
    users = User.query.execution_options(skip_operator_filter=True).filter_by(is_active=True).all()
    for user in users:
        sync_user(user, now=now)
    db.session.commit()
    return len(users)


def install(app):
    @app.before_request
    def collect_due_notifications():
        if request.method == "GET" and request.path != "/healthz" and current_user.is_authenticated:
            now = datetime.utcnow().timestamp()
            if session.get("notification_sync_user") == current_user.get_id() and now - session.get("notification_sync_at", 0) < 60:
                return
            sync_user(current_user)
            db.session.commit()
            session["notification_sync_user"] = current_user.get_id()
            session["notification_sync_at"] = now


def summary(user):
    query = user_notifications(user)
    return {"unread": query.filter(Notification.read_at.is_(None)).count(),
            "items": query.order_by(Notification.read_at.is_(None).desc(), Notification.created_at.desc(), Notification.id.desc()).limit(5).all()}