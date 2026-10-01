"""Installable phone app (PWA): web app manifest, service worker, offline page and home-screen icons.

Each operator's site installs as that operator's own app (its name, brand colour and initial); the Platform site
installs as Hub1z.
"""
from __future__ import annotations

import io
import json
import re
from functools import lru_cache

from flask import Blueprint, Response, current_app, g, render_template, send_from_directory, url_for

pwa_bp = Blueprint("pwa", __name__)

HUB1Z_INDIGO = "#5b5bd6"
ICON_SIZES = (32, 180, 192, 512)


def _brand_color(operator) -> str:
    color = (getattr(operator, "brand_color", None) or "").strip()
    return color if re.fullmatch(r"#[0-9a-fA-F]{6}", color) else HUB1Z_INDIGO


@lru_cache(maxsize=256)
def _initial_icon(letter: str, color: str, size: int) -> bytes:
    """A full-bleed square with the operator's initial; safe as a maskable icon (letter sits in the middle 60%)."""
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGB", (size, size), color)
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.load_default(size=int(size * 0.5))
    except TypeError:  # Pillow without FreeType sizing
        font = ImageFont.load_default()
    draw.text((size / 2, size / 2), letter, fill="white", font=font, anchor="mm")
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


@pwa_bp.route("/manifest.webmanifest")
def manifest():
    operator = getattr(g, "operator", None)
    if operator is not None:
        name = operator.name
        icons = [{"src": url_for("pwa.icon", size=s), "sizes": f"{s}x{s}", "type": "image/png", "purpose": "any maskable"}
                 for s in (192, 512)]
        shortcuts = [
            {"name": "Check in", "short_name": "Check in", "url": url_for("checkin.pass_page")},
            {"name": "Book a desk or room", "short_name": "Book", "url": url_for("book.index")},
            {"name": "Calendar", "short_name": "Calendar", "url": url_for("book.calendar")},
        ]
        color = _brand_color(operator)
    else:
        name = "Hub1z"
        icons = [{"src": url_for("static", filename=f"img/brand/icon-{s}.png"), "sizes": f"{s}x{s}", "type": "image/png",
                  "purpose": "any"} for s in (192, 512)]
        shortcuts = [{"name": "Dashboard", "short_name": "Dashboard", "url": "/platform/"}]
        color = HUB1Z_INDIGO
    data = {
        "id": "/", "name": name, "short_name": name[:12], "start_url": "/auth/post-login", "scope": "/",
        "display": "standalone", "background_color": "#ffffff", "theme_color": color,
        "description": f"{name}: check in, book desks and rooms, and pay invoices.",
        "icons": icons, "shortcuts": shortcuts,
    }
    resp = Response(json.dumps(data), mimetype="application/manifest+json")
    resp.headers["Cache-Control"] = "no-cache"
    return resp


@pwa_bp.route("/app-icon-<int:size>.png")
def icon(size: int):
    operator = getattr(g, "operator", None)
    if size not in ICON_SIZES:
        size = 192
    if operator is None:
        return send_from_directory(current_app.static_folder, "img/brand/icon-192.png" if size <= 192 else "img/brand/icon-512.png")
    letter = (operator.name.strip()[:1] or "W").upper()
    resp = Response(_initial_icon(letter, _brand_color(operator), size), mimetype="image/png")
    resp.headers["Cache-Control"] = "public, max-age=86400"
    return resp


@pwa_bp.route("/sw.js")
def service_worker():
    resp = send_from_directory(current_app.static_folder, "js/sw.js", mimetype="application/javascript", max_age=0)
    resp.headers["Cache-Control"] = "no-cache"
    resp.headers["Service-Worker-Allowed"] = "/"
    return resp


@pwa_bp.route("/offline")
def offline():
    return render_template("offline.html")
