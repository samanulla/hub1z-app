from datetime import date, timedelta
from app import create_app
from app.extensions import db
from app.models import Operator, User, UserRole, Location, ConferenceRoom, Floor

app = create_app()
app.config["WTF_CSRF_ENABLED"] = False

with app.app_context():
    t = Operator.query.execution_options(skip_operator_filter=True).filter_by(slug="__previewtest__").first()
    print("operator exists:", bool(t))

    member = User.query.filter_by(operator_id=t.id, role=UserRole.INDIVIDUAL).first()
    member.set_password("TestPass123!")
    db.session.commit()

    loc_a = Location.query.filter_by(operator_id=t.id).first()
    loc_b = Location.query.filter(Location.operator_id == t.id, Location.id != loc_a.id).first()
    if not loc_b:
        loc_b = Location(operator_id=t.id, name="Branch B", code="BR-B", address_line1="2 Side St",
                         city="Chennai", country="IN", timezone="Asia/Kolkata")
        db.session.add(loc_b); db.session.flush()
    floor_b = Floor.query.filter_by(location_id=loc_b.id).first()
    if not floor_b:
        floor_b = Floor(location_id=loc_b.id, level=1, name="Ground")
        db.session.add(floor_b); db.session.flush()

    # A room in Location B, opted into cross-location booking.
    room_b = ConferenceRoom.query.filter_by(location_id=loc_b.id).first()
    if not room_b:
        room_b = ConferenceRoom(operator_id=t.id, location_id=loc_b.id, floor_id=floor_b.id,
                                name="Cross Room", code="XROOM", capacity=4, hourly_rate=300,
                                is_active=True, cross_location_bookable=True)
        db.session.add(room_b); db.session.flush()
    else:
        room_b.cross_location_bookable = True
    db.session.commit()

    member_email = member.email
    loc_a_id = loc_a.id
    room_b_id = room_b.id
    print("location A:", loc_a_id, "location B room (cross-bookable):", room_b_id)

with app.test_client() as c:
    c.post("/auth/login", data={"email": member_email, "password": "TestPass123!"},
           headers={"Host": "previewtest.hub1z.com"}, follow_redirects=True)

    r1 = c.get(f"/book/locations/{loc_a_id}/calendar", headers={"Host": "previewtest.hub1z.com"})
    html = r1.get_data(as_text=True)
    print("calendar A status:", r1.status_code)
    print("modal includes cross-location room option:", "Cross Room (Branch B)" in html)

    tomorrow = (date.today() + timedelta(days=2)).isoformat()
    start = f"{tomorrow}T14:00"
    end = f"{tomorrow}T15:00"

    r2 = c.post(f"/book/locations/{loc_a_id}/calendar/quick-book", data={
        "room_id": room_b_id, "title": "Cross-location meeting", "start": start, "end": end,
        "attendees": 1, "notes": "",
    }, headers={"Host": "previewtest.hub1z.com"}, follow_redirects=True)
    print("cross-location quick-book status:", r2.status_code)
    print("cross-location quick-book success:", "booked" in r2.get_data(as_text=True).lower())
