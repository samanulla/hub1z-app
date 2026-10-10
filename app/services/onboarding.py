"""First-run guide for a new operator workspace: what to set up next, from the data that exists."""
from __future__ import annotations

from flask import url_for

from ..models import Location, PricingPlan


def steps(stats: dict, is_super_admin: bool) -> list[dict]:
    """Ordered setup steps; each has `done` and, for the current one, `actions` [(label, url)]."""
    first = Location.query.order_by(Location.id).first()
    new_location = url_for("admin.location_new") if is_super_admin else url_for("admin.locations_list")
    inventory = ([("Add seats", url_for("admin.seat_new", location_id=first.id)),
                  ("Add meeting rooms", url_for("admin.room_new", location_id=first.id))]
                 if first else [("Open locations", url_for("admin.locations_list"))])
    return [
        {"key": "location", "title": "Add your first location",
         "text": "Start with the place members will visit: its name, address and opening hours. Seats, rooms and plans all belong to a location.",
         "done": stats["locations"] > 0, "actions": [("Add a location", new_location)]},
        {"key": "inventory", "title": "Add your seats and meeting rooms",
         "text": "Add the desks, cabins and rooms you rent out. You can add many at once and change prices later.",
         "done": (stats["seats"] + stats["rooms"]) > 0, "actions": inventory},
        {"key": "plan", "title": "Create a pricing plan",
         "text": "A plan says what a member pays, for how long and for what. Companies and individuals subscribe to your plans.",
         "done": PricingPlan.query.count() > 0, "actions": [("Create a plan", url_for("admin.plan_new"))]},
        {"key": "people", "title": "Bring in your first company or member",
         "text": "Invite them by email or add them yourself. They can then book seats and rooms.",
         "done": (stats["companies"] + stats["members"]) > 0, "actions": [("Invite people", url_for("admin.invites_list"))]},
    ]


def current(all_steps: list[dict]) -> dict | None:
    return next((s for s in all_steps if not s["done"]), None)
