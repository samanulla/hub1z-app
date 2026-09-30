"""View-model for the shared room calendar: what each viewer sees in every 30-minute slot.

Everyone at an operator sees the same grid, so availability is honest and first-come. What a booked slot
reveals depends on the viewer: the operator sees everything, a company sees its own people's meetings,
everyone else just sees "Booked".
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.orm import selectinload

from ..models import BookingStatus, RoomBlock, RoomBooking

SLOT = timedelta(minutes=30)
UTC = ZoneInfo("UTC")


def location_tz(loc) -> ZoneInfo:
    try:
        return ZoneInfo(loc.timezone or "UTC")
    except Exception:  # noqa: BLE001 - bad/legacy timezone data shouldn't 500 the calendar
        return UTC


def _to_utc(local: datetime, tz: ZoneInfo) -> datetime:
    return local.replace(tzinfo=tz).astimezone(UTC).replace(tzinfo=None)


def _slot_times(loc) -> list[time]:
    if loc.is_247:
        start, end = time(0, 0), None
    else:
        start, end = loc.open_time or time(7, 0), loc.close_time or time(21, 0)
    base = date(2000, 1, 1)
    cur = datetime.combine(base, start)
    stop = datetime.combine(base, end) if end else datetime.combine(base + timedelta(days=1), time.min)
    out = []
    while cur < stop:
        out.append(cur.time())
        cur += SLOT
    return out


def _booking_cell(b, viewer) -> tuple[str, str]:
    detail = f"{b.title or 'Meeting'} \u00b7 {b.user.full_name if b.user else ''}".rstrip(" \u00b7")
    if b.user_id == viewer.id:
        return "mine", b.title or "Your booking"
    if viewer.is_admin:
        return "booked", detail
    if viewer.company_id and b.company_id == viewer.company_id:
        return "company", detail
    return "booked", "Booked"


def build_calendar(*, loc, rooms, day: date, view: str, week_room, viewer, now: datetime | None = None) -> dict:
    tz = location_tz(loc)
    now = now or datetime.utcnow()
    now_local = now.replace(tzinfo=UTC).astimezone(tz)

    if view == "week" and week_room is not None:
        monday = day - timedelta(days=day.weekday())
        days = [monday + timedelta(days=i) for i in range(7)]
        columns = [{"title": d.strftime("%a %d %b"), "sub": week_room.name, "room": week_room, "day": d} for d in days]
    else:
        days = [day]
        columns = [{"title": r.name, "sub": f"Cap {r.capacity} \u00b7 {r.credits_per_slot} cr / 30 min"
                    + (f" \u00b7 {r.location.name}" if r.location_id != loc.id else ""),
                    "room": r, "day": day} for r in rooms]

    room_ids = {c["room"].id for c in columns}
    range_start = _to_utc(datetime.combine(days[0], time.min), tz)
    range_end = _to_utc(datetime.combine(days[-1], time.min) + timedelta(days=1), tz)
    entries: dict[int, list] = {rid: [] for rid in room_ids}
    if room_ids:
        bookings = (RoomBooking.query.options(selectinload(RoomBooking.user))
                    .filter(RoomBooking.room_id.in_(room_ids),
                            RoomBooking.status.in_([BookingStatus.CONFIRMED, BookingStatus.CHECKED_IN]),
                            RoomBooking.start_at < range_end, RoomBooking.end_at > range_start).all())
        blocks = RoomBlock.query.filter(RoomBlock.room_id.in_(room_ids), RoomBlock.start_at < range_end,
                                        RoomBlock.end_at > range_start).all()
        for b in bookings:
            entries[b.room_id].append(("booking", b))
        for k in blocks:
            entries[k.room_id].append(("block", k))

    now_minutes = now_local.hour * 60 + now_local.minute
    rows = []
    for idx, t in enumerate(_slot_times(loc)):
        minutes = t.hour * 60 + t.minute
        row = {"label": t.strftime("%H:%M"), "hour": t.minute == 0,
               "now": now_local.date() in days and minutes <= now_minutes < minutes + 30, "cells": []}
        for col in columns:
            start_local = datetime.combine(col["day"], t)
            s = _to_utc(start_local, tz)
            e = s + SLOT
            cell = {"start": start_local.strftime("%Y-%m-%dT%H:%M"),
                    "end": (start_local + SLOT).strftime("%Y-%m-%dT%H:%M"),
                    "past": e <= now, "state": "available", "label": "", "first": False}
            hit = next((x for x in entries[col["room"].id] if x[1].start_at < e and x[1].end_at > s), None)
            if hit:
                kind, obj = hit
                if kind == "block":
                    cell["state"], cell["label"] = "blocked", ((obj.reason or "Blocked") if viewer.is_admin else "Unavailable")
                else:
                    cell["state"], cell["label"] = _booking_cell(obj, viewer)
                cell["first"] = obj.start_at >= s or idx == 0
            row["cells"].append(cell)
        rows.append(row)
    return {"rows": rows, "columns": columns, "days": days}
