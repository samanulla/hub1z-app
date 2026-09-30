"""Thin REST API for kiosks and mobile clients.

For simplicity this uses HTTP Basic auth via Flask-Login sessions in dev.
Swap for JWT in production (see ``PyJWT`` in requirements).
"""
from __future__ import annotations

from datetime import datetime

from flask import Blueprint, jsonify, request, abort
from flask_login import login_required, current_user

from ...models import Location, Seat, ConferenceRoom
from ...services.booking_service import (
    create_seat_booking, create_room_booking, BookingError,
)
from ...services.formatting import parse_local_naive_to_utc as _parse_local
from ...utils.datetime_helpers import parse_dt_local

api_bp = Blueprint("api", __name__)


def _location_json(loc: Location) -> dict:
    return {
        "id": loc.id, "code": loc.code, "name": loc.name,
        "city": loc.city, "country": loc.country,
        "seats": len([s for s in loc.seats if s.is_active]),
        "rooms": len([r for r in loc.rooms if r.is_active]),
    }


def _seat_json(seat: Seat) -> dict:
    return {
        "id": seat.id, "code": seat.code, "type": seat.seat_type.value,
        "hourly_rate": float(seat.hourly_rate or 0),
        "daily_rate": float(seat.daily_rate or 0),
        "monthly_rate": float(seat.monthly_rate or 0),
        "location_id": seat.location_id, "floor_id": seat.floor_id,
    }


def _room_json(r: ConferenceRoom) -> dict:
    return {
        "id": r.id, "code": r.code, "name": r.name, "capacity": r.capacity,
        "hourly_rate": float(r.hourly_rate or 0),
        "credits_per_30_min": r.credits_per_slot,
        "location_id": r.location_id, "floor_id": r.floor_id,
    }


@api_bp.get("/locations")
@login_required
def list_locations():
    locs = Location.query.filter_by(is_active=True).all()
    return jsonify([_location_json(l) for l in locs])


@api_bp.get("/locations/<int:location_id>/seats")
@login_required
def list_seats(location_id: int):
    seats = Seat.query.filter_by(location_id=location_id, is_active=True).all()
    return jsonify([_seat_json(s) for s in seats])


@api_bp.get("/locations/<int:location_id>/rooms")
@login_required
def list_rooms(location_id: int):
    rooms = ConferenceRoom.query.filter_by(location_id=location_id, is_active=True).all()
    return jsonify([_room_json(r) for r in rooms])


@api_bp.post("/bookings/seat")
@login_required
def book_seat_api():
    data = request.get_json(silent=True) or {}
    try:
        seat = Seat.query.get_or_404(int(data["seat_id"]))
        start = _parse_local(data["start"])
        end = _parse_local(data["end"])
    except (KeyError, ValueError):
        abort(400, description="seat_id, start, end are required")
    try:
        b = create_seat_booking(user=current_user, seat=seat, start=start, end=end,
                                notes=data.get("notes"))
    except BookingError as e:
        return jsonify({"error": str(e)}), 409
    return jsonify({"id": b.id, "status": b.status.value,
                    "total": float(b.total_amount or 0)}), 201


@api_bp.post("/bookings/room")
@login_required
def book_room_api():
    data = request.get_json(silent=True) or {}
    try:
        room = ConferenceRoom.query.get_or_404(int(data["room_id"]))
        start = _parse_local(data["start"])
        end = _parse_local(data["end"])
    except (KeyError, ValueError):
        abort(400, description="room_id, start, end are required")
    try:
        b = create_room_booking(
            user=current_user, room=room, start=start, end=end,
            title=data.get("title"),
            attendees=int(data.get("attendees", 1)),
            notes=data.get("notes"),
        )
    except BookingError as e:
        return jsonify({"error": str(e)}), 409
    return jsonify({"id": b.id, "status": b.status.value,
                    "credits_used": b.credits_used,
                    "total": float(b.total_amount or 0)}), 201
