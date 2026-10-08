"""Amenities an operator can offer on a marketplace listing, each included or available to buy."""
from __future__ import annotations

# key, label, icon, listing types it applies to
CATALOG = [
    ("wifi", "High-speed Wi-Fi", "bi-wifi", ("room", "day_access")),
    ("ac", "Air conditioning", "bi-snow", ("room", "day_access")),
    ("power", "Power sockets", "bi-plug", ("room", "day_access")),
    ("water", "Drinking water", "bi-droplet", ("room", "day_access")),
    ("tea_coffee", "Tea and coffee", "bi-cup-hot", ("room", "day_access")),
    ("snacks_drinks", "Snacks and drinks", "bi-cup-straw", ("room", "day_access")),
    ("printer", "Printing and scanning", "bi-printer", ("room", "day_access", "virtual_office")),
    ("tv_screen", "TV or display screen", "bi-tv", ("room",)),
    ("projector", "Projector", "bi-projector", ("room",)),
    ("whiteboard", "Whiteboard", "bi-easel2", ("room",)),
    ("video_conf", "Video conferencing setup", "bi-camera-video", ("room",)),
    ("phone_booth", "Phone booths", "bi-telephone", ("day_access",)),
    ("lockers", "Lockers", "bi-lock", ("day_access",)),
    ("lounge", "Lounge and cafeteria", "bi-cup", ("day_access",)),
    ("reception", "Reception support", "bi-person-badge", ("room", "day_access", "virtual_office")),
    ("restrooms", "Restrooms", "bi-person-standing", ("room", "day_access")),
    ("parking", "Parking", "bi-p-square", ("room", "day_access")),
    ("accessible", "Step-free access", "bi-person-wheelchair", ("room", "day_access")),
    ("mail_handling", "Mail and parcel handling", "bi-envelope", ("virtual_office",)),
    ("address_use", "Business address for GST and registration", "bi-geo-alt", ("virtual_office",)),
    ("call_answering", "Call answering", "bi-headset", ("virtual_office",)),
    ("meeting_access", "Meeting room access", "bi-people", ("virtual_office",)),
]
BY_KEY = {key: (label, icon, kinds) for key, label, icon, kinds in CATALOG}
STATES = ("included", "paid")
MAX_OTHER = 200


def for_kind(kind: str) -> list[tuple[str, str, str]]:
    return [(key, label, icon) for key, label, icon, kinds in CATALOG if kind in kinds]


def parse(form, kind: str) -> dict:
    """Read amenity_<key> radio values and the free-text extras from the listing form."""
    items = {}
    for key, _, _ in for_kind(kind):
        state = form.get(f"amenity_{key}", "")
        if state in STATES:
            items[key] = state
    other = " ".join((form.get("amenity_other") or "").split())[:MAX_OTHER]
    return {"items": items, "other": other}


def display(amenities: dict | None) -> dict:
    """Included and for-purchase amenities with their labels, in catalog order, for the public page."""
    data = amenities or {}
    items = data.get("items", {})
    rows = {"included": [], "paid": []}
    for key, label, icon, _ in CATALOG:
        state = items.get(key)
        if state in rows:
            rows[state].append({"key": key, "label": label, "icon": icon})
    return {"included": rows["included"], "paid": rows["paid"], "other": data.get("other", "")}
