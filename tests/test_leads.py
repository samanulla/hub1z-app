"""Leads for operators and for the Platform: separate pipelines, separate people, no leaks."""
import os

os.environ.setdefault("FLASK_ENV", "testing")

from app.cli import PERSONA_PASSWORD
from app.extensions import db
from app.models import Lead, User, UserRole
from app.services import leads as leads_service
from tests.test_role_paths import APEX, DEMO, OTHER, OWNER_PASSWORD, _login, _seeded_app

LEAD = {"name": "Karthik S", "company_name": "Nimbus Labs", "phone": "9840011223", "interest": "3 dedicated desks",
        "expected_value": "45000", "stage": "new", "temperature": "hot", "owner_id": "0", "source": "Website",
        "seats": "3"}


def _client(app, host, email, password):
    c = app.test_client()
    assert _login(c, host, email, password).status_code == 302, email
    return c


def _get(c, host, path, **kw):
    return c.get(path, headers={"Host": host}, **kw)


def _lead_id(app, name):
    with app.app_context():
        return Lead.query.execution_options(skip_operator_filter=True).filter_by(name=name).one().id


def test_operator_adds_moves_and_closes_a_lead_and_other_operators_never_see_it():
    app, _ = _seeded_app()
    demo = _client(app, DEMO, "owner@demospace.com", PERSONA_PASSWORD)
    r = demo.post("/admin/leads/new", data=LEAD, headers={"Host": DEMO})
    assert r.status_code == 302

    page = _get(demo, DEMO, "/admin/leads").data
    assert b"Karthik S" in page and b"Nimbus Labs" in page and b"Tour booked" in page and b"Demo booked" not in page

    other = _client(app, OTHER, "owner@otherspace.com", PERSONA_PASSWORD)
    assert b"Karthik S" not in _get(other, OTHER, "/admin/leads").data
    platform = _client(app, APEX, "admin@hub1z.com", OWNER_PASSWORD)
    assert b"Karthik S" not in _get(platform, APEX, "/platform/leads").data

    lead_id = _lead_id(app, "Karthik S")
    js = {"Host": DEMO, "Accept": "application/json"}
    moved = demo.post(f"/admin/leads/{lead_id}/move", json={"stage": "tour"}, headers=js)
    assert moved.status_code == 200 and moved.json["stage"] == "tour" and moved.json["label"] == "Tour booked"
    assert demo.post(f"/admin/leads/{lead_id}/move", json={"stage": "nonsense"}, headers=js).status_code == 400
    # another operator cannot move or open it
    assert other.post(f"/admin/leads/{lead_id}/move", json={"stage": "won"},
                      headers={"Host": OTHER, "Accept": "application/json"}).status_code == 404
    assert _get(other, OTHER, f"/admin/leads/{lead_id}").status_code == 404

    won = demo.post(f"/admin/leads/{lead_id}/move", json={"stage": "won"}, headers=js)
    assert won.json["stage"] == "won"
    with app.app_context():
        lead = db.session.get(Lead, lead_id)
        assert lead.closed_at is not None
        assert [a.kind for a in lead.activities].count("stage") == 2
    assert b"100%" in _get(demo, DEMO, "/admin/leads").data  # one won, none lost


def test_lost_needs_no_board_column_and_keeps_its_reason():
    app, _ = _seeded_app()
    demo = _client(app, DEMO, "owner@demospace.com", PERSONA_PASSWORD)
    demo.post("/admin/leads/new", data=LEAD, headers={"Host": DEMO})
    lead_id = _lead_id(app, "Karthik S")
    demo.post(f"/admin/leads/{lead_id}/move", data={"stage": "lost", "reason": "Chose another space"}, headers={"Host": DEMO})
    detail = _get(demo, DEMO, f"/admin/leads/{lead_id}").data
    assert b"Chose another space" in detail
    board = _get(demo, DEMO, "/admin/leads").data
    assert b'data-stage="lost"' not in board
    listing = _get(demo, DEMO, "/admin/leads?view=list").data
    assert b"Karthik S" in listing and b"Lost" in listing


def test_follow_up_numbers_and_notes():
    app, _ = _seeded_app()
    demo = _client(app, DEMO, "owner@demospace.com", PERSONA_PASSWORD)
    demo.post("/admin/leads/new", data={**LEAD, "next_follow_up": "2020-01-01"}, headers={"Host": DEMO})
    page = _get(demo, DEMO, "/admin/leads").data.decode()
    assert "Overdue" in page and "1 overdue" in page
    lead_id = _lead_id(app, "Karthik S")
    r = demo.post(f"/admin/leads/{lead_id}/note", data={"kind": "call", "body": "Called, wants a tour", "next_follow_up": "2999-01-01"},
                  headers={"Host": DEMO})
    assert r.status_code == 302
    detail = _get(demo, DEMO, f"/admin/leads/{lead_id}").data
    assert b"Called, wants a tour" in detail
    assert b"0 overdue" in _get(demo, DEMO, "/admin/leads").data


def test_platform_has_its_own_pipeline_and_operators_cannot_see_it():
    app, _ = _seeded_app()
    platform = _client(app, APEX, "admin@hub1z.com", OWNER_PASSWORD)
    r = platform.post("/platform/leads/new", headers={"Host": APEX},
                      data={**LEAD, "name": "Nisha R", "company_name": "Koramangala Collective", "source": "Webinar"})
    assert r.status_code == 302
    page = _get(platform, APEX, "/platform/leads").data
    assert b"Nisha R" in page and b"Demo booked" in page and b"Tour booked" not in page
    with app.app_context():
        assert Lead.query.execution_options(skip_operator_filter=True).filter_by(name="Nisha R").one().operator_id is None
    demo = _client(app, DEMO, "owner@demospace.com", PERSONA_PASSWORD)
    assert b"Nisha R" not in _get(demo, DEMO, "/admin/leads").data
    lead_id = _lead_id(app, "Nisha R")
    assert _get(demo, DEMO, f"/admin/leads/{lead_id}").status_code == 404
    assert platform.post(f"/platform/leads/{lead_id}/move", json={"stage": "demo"},
                         headers={"Host": APEX, "Accept": "application/json"}).json["label"] == "Demo booked"


def test_only_the_right_people_can_open_leads():
    app, _ = _seeded_app()
    employee = _client(app, DEMO, "employee@acmeco.com", PERSONA_PASSWORD)
    assert _get(employee, DEMO, "/admin/leads").status_code == 403
    with app.app_context():
        manager = User(email="pm@hub1z.com", full_name="Platform Pat", role=UserRole.PLATFORM_MANAGER, is_active=True)
        manager.set_password("Manager123!")
        manager.set_platform_permissions(["operators"])
        db.session.add(manager)
        db.session.commit()
    pm = _client(app, APEX, "pm@hub1z.com", "Manager123!")
    assert _get(pm, APEX, "/platform/leads").status_code == 403
    assert b"Leads" not in _get(pm, APEX, "/platform/").data
    with app.app_context():
        manager = User.query.execution_options(skip_operator_filter=True).filter_by(email="pm@hub1z.com").one()
        manager.set_platform_permissions(["operators", "leads"])
        db.session.commit()
    assert _get(pm, APEX, "/platform/leads").status_code == 200


def test_menus_show_leads_and_export_works():
    app, _ = _seeded_app()
    demo = _client(app, DEMO, "owner@demospace.com", PERSONA_PASSWORD)
    demo.post("/admin/leads/new", data=LEAD, headers={"Host": DEMO})
    assert b"/admin/leads" in _get(demo, DEMO, "/admin/").data
    csv_out = _get(demo, DEMO, "/admin/leads/export.csv")
    assert csv_out.mimetype == "text/csv" and b"Karthik S" in csv_out.data
    platform = _client(app, APEX, "admin@hub1z.com", OWNER_PASSWORD)
    assert b"/platform/leads" in _get(platform, APEX, "/platform/").data


def test_whatsapp_number_and_due_text():
    lead = Lead(name="x", phone="098400 11223")
    assert lead.whatsapp_number == "919840011223"
    assert Lead(name="x", phone="+91 98400 11223").whatsapp_number == "919840011223"
    assert Lead(name="x", phone="12345").whatsapp_number == ""
    from datetime import date
    today = date(2026, 10, 10)
    assert leads_service.due_state(Lead(name="x", stage="new", next_follow_up=date(2026, 10, 8)), today) == ("late", "Overdue 2 days")
    assert leads_service.due_state(Lead(name="x", stage="new", next_follow_up=today), today) == ("today", "Due today")
    assert leads_service.due_state(Lead(name="x", stage="new", next_follow_up=date(2026, 10, 11)), today) == ("ok", "Tomorrow")
    assert leads_service.due_state(Lead(name="x", stage="won", next_follow_up=today), today)[0] == "none"
