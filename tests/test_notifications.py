import os
os.environ.setdefault("FLASK_ENV", "testing")
from app.extensions import db
from app.models import Notification, User
from app.services.notifications import notify
from datetime import datetime, timedelta
from tests.test_release_upi_parcels_alerts import DEMO, OTHER, _client, _get, _post, _seeded_app


def test_notifications_deduplicate_and_read_state_is_per_recipient():
    app, _ = _seeded_app()
    with app.app_context():
        recipient = User.query.execution_options(skip_operator_filter=True).filter_by(email="employee@acmeco.com").one()
        assert notify(recipient, "test:1", "announcement", "New notice", "Details", "/hub/announcements") == 1
        assert notify(recipient, "test:1", "announcement", "New notice", "Details", "/hub/announcements") == 0
        db.session.commit()
        notification_id = Notification.query.execution_options(skip_operator_filter=True).one().id
    employee = _client(app, DEMO, "employee@acmeco.com")
    other = _client(app, OTHER, "owner@otherspace.com")
    colleague = _client(app, DEMO, "admin@acmeco.com")
    assert _get(employee, DEMO, "/notifications/summary").json["unread"] == 1
    assert _post(other, OTHER, f"/notifications/{notification_id}/read").status_code == 404
    assert _post(colleague, DEMO, f"/notifications/{notification_id}/read").status_code == 404
    assert _post(employee, DEMO, f"/notifications/{notification_id}/read").status_code == 302
    assert _get(employee, DEMO, "/notifications/summary").json["unread"] == 0
    assert _post(employee, DEMO, f"/notifications/{notification_id}/unread").status_code == 302
    assert _get(employee, DEMO, "/notifications/summary").json["unread"] == 1
    assert b'New notice' in _get(employee, DEMO, "/notifications/").data
    response = _post(employee, DEMO, f"/notifications/{notification_id}/open")
    assert response.location.endswith("/hub/announcements")
    assert _get(employee, DEMO, "/notifications/summary").json["unread"] == 0
    _post(employee, DEMO, f"/notifications/{notification_id}/unread")
    assert _post(employee, DEMO, "/notifications/read-all").status_code == 302
    assert _get(employee, DEMO, "/notifications/summary").json["unread"] == 0


def test_announcements_and_ticket_updates_reach_recipients():
    from app.models import SupportTicket
    app, _ = _seeded_app()
    owner = _client(app, DEMO, "owner@demospace.com")
    employee = _client(app, DEMO, "employee@acmeco.com")
    assert _post(owner, DEMO, "/hub/announcements/new", {"title": "Water maintenance", "body": "Tomorrow at noon"}).status_code == 302
    assert b'Water maintenance' in _get(employee, DEMO, "/notifications/").data
    with app.app_context():
        notice = Notification.query.execution_options(skip_operator_filter=True).filter_by(title="Water maintenance").first()
        detail_url = notice.href
    assert b'Tomorrow at noon' in _get(employee, DEMO, detail_url).data
    assert _post(employee, DEMO, "/hub/tickets", {"subject": "Broken chair", "body": "Please replace", "priority": "normal"}).status_code == 302
    with app.app_context():
        ticket_id = SupportTicket.query.execution_options(skip_operator_filter=True).filter_by(subject="Broken chair").one().id
    assert b'Broken chair' in _get(owner, DEMO, "/notifications/").data
    assert _post(owner, DEMO, f"/hub/tickets/{ticket_id}/resolve").status_code == 302
    assert b'Ticket updated: Broken chair' in _get(employee, DEMO, "/notifications/").data
    other = _client(app, OTHER, "owner@otherspace.com")
    assert b'Water maintenance' not in _get(other, OTHER, "/notifications/").data


def test_due_meeting_reminder_is_created_once():
    from app.models import RoomBooking, BookingStatus, ConferenceRoom
    from app.services.notifications import sync_user
    app, _ = _seeded_app()
    with app.app_context():
        user = User.query.execution_options(skip_operator_filter=True).filter_by(email="employee@acmeco.com").one()
        room = ConferenceRoom.query.execution_options(skip_operator_filter=True).filter_by(operator_id=user.operator_id).first()
        now = datetime.utcnow()
        db.session.add(RoomBooking(operator_id=user.operator_id, room_id=room.id, user_id=user.id,
                                   start_at=now + timedelta(minutes=20), end_at=now + timedelta(minutes=50), status=BookingStatus.CONFIRMED))
        db.session.flush()
        sync_user(user, now=now)
        sync_user(user, now=now)
        db.session.commit()
        rows = Notification.query.execution_options(skip_operator_filter=True).filter_by(user_id=user.id, kind="meeting").all()
        assert len(rows) == 1 and "20 minutes" in rows[0].title


def test_company_renewal_reaches_admin_not_other_members():
    from app.models import Company, Subscription, SubscriptionStatus
    from app.services.notifications import sync_user
    from dateutil.relativedelta import relativedelta
    app, _ = _seeded_app()
    with app.app_context():
        admin = User.query.execution_options(skip_operator_filter=True).filter_by(email="admin@acmeco.com").one()
        individual = User.query.execution_options(skip_operator_filter=True).filter_by(email="individual@demospace.com").one()
        sub = Subscription.query.execution_options(skip_operator_filter=True).filter_by(company_id=admin.company_id, status=SubscriptionStatus.ACTIVE).first()
        sub.start_date = datetime.utcnow().date() - relativedelta(months=sub.term_months) + timedelta(days=20)
        db.session.flush()
        sync_user(admin)
        sync_user(individual)
        db.session.commit()
        key_prefix = f"renewal30:{sub.id}:"
        query = Notification.query.execution_options(skip_operator_filter=True).filter(Notification.event_key.like(key_prefix + "%"))
        assert query.filter_by(user_id=admin.id).count() == 1
        assert query.filter_by(user_id=individual.id).count() == 0


def test_location_announcement_is_not_sent_to_unrelated_location():
    from app.models import Location, Subscription, LocationScope
    app, _ = _seeded_app()
    with app.app_context():
        admin = User.query.execution_options(skip_operator_filter=True).filter_by(email="admin@acmeco.com").one()
        home = Location.query.execution_options(skip_operator_filter=True).filter_by(operator_id=admin.operator_id).first()
        other = Location(operator_id=admin.operator_id, name="Other floor", code="OTHER", address_line1="2 Main Street", city="Chennai", country="IN")
        db.session.add(other)
        for sub in Subscription.query.execution_options(skip_operator_filter=True).filter_by(company_id=admin.company_id).all():
            sub.plan.location_scope = LocationScope.ONE
            sub.plan.locations = [home]
        db.session.commit()
        location_id = other.id
    owner = _client(app, DEMO, "owner@demospace.com")
    employee = _client(app, DEMO, "employee@acmeco.com")
    assert _post(owner, DEMO, "/hub/announcements/new", {"title": "Other location only", "body": "Local notice", "location_id": str(location_id)}).status_code == 302
    assert b'Other location only' not in _get(employee, DEMO, "/notifications/").data
    assert b'Other location only' not in _get(employee, DEMO, "/hub/announcements").data