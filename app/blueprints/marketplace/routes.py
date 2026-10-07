"""Public marketplace (spaces.hub1z.com): discover shared rooms and day passes, sign in with an email code, book."""
from __future__ import annotations

import re
import secrets
from contextlib import contextmanager
from datetime import date, time, timedelta

from flask import (Blueprint, Response, abort, current_app, flash, g, redirect, render_template, request, session,
                   url_for)

from ...extensions import db, limiter
from ...models import Operator
from ...services import marketplace as mk
from ...services import marketplace_auth as auth
from ...services import marketplace_public as pub
from ...services import upi

marketplace_bp = Blueprint("marketplace", __name__, template_folder="../../templates")

GSTIN = re.compile(r"^\d{2}[A-Z]{5}\d{4}[A-Z]\d[Z][A-Z\d]$")


@contextmanager
def trusted():
    """Booking-engine calls look rows up by ids taken from allowlisted reads, so tenant-table guards step aside."""
    g.marketplace_trusted = True
    try:
        yield
    finally:
        g.marketplace_trusted = False


@marketplace_bp.before_request
def _only_on_the_marketplace_host():
    if not getattr(g, "marketplace_host", False):
        abort(404)


@marketplace_bp.context_processor
def _inject():
    return {"customer": auth.current_customer(), "marketplace_url": pub.marketplace_url}


def _login_required():
    customer = auth.current_customer()
    if customer is None:
        session["mc_next"] = request.full_path.rstrip("?")
        return None
    return customer


def _safe_next(target: str | None) -> str:
    return target if target and target.startswith("/marketplace") and not target.startswith("//") else url_for("marketplace.bookings")


# ---------------------------------------------------------------- browse --

@marketplace_bp.route("/")
def home():
    city = (request.args.get("city") or "").strip()
    kind = request.args.get("kind", "")
    return render_template("marketplace/home.html", listings=pub.search(city, kind), cities=pub.cities(),
                           city=city, kind=kind)


@marketplace_bp.route("/l/<int:listing_id>")
def listing(listing_id):
    item = pub.listing_detail(listing_id)
    if item is None:
        abort(404)
    return render_template("marketplace/listing.html", item=item, key=secrets.token_hex(16),
                           today=date.today().isoformat())


# ------------------------------------------------------------------ auth --

@marketplace_bp.route("/login", methods=["GET", "POST"])
@limiter.limit("6 per minute; 30 per hour", methods=["POST"])
def login():
    if auth.current_customer():
        return redirect(_safe_next(session.get("mc_next")))
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
            flash("Enter a valid email address.", "danger")
        else:
            try:
                code = auth.request_code(email, request.form.get("name", ""), request.form.get("phone", ""))
            except auth.SignInError as e:
                flash(str(e), "danger")
            else:
                session["mc_pending"] = email
                if current_app.config.get("MARKETPLACE_SHOW_DEV_CODE"):
                    flash(f"Development only: your code is {code}.", "info")
                return redirect(url_for("marketplace.verify"))
    return render_template("marketplace/login.html")


@marketplace_bp.route("/verify", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
def verify():
    email = session.get("mc_pending")
    if not email:
        return redirect(url_for("marketplace.login"))
    if request.method == "POST":
        try:
            customer = auth.verify_code(email, request.form.get("code", ""))
        except auth.SignInError as e:
            flash(str(e), "danger")
        else:
            target = _safe_next(session.get("mc_next"))
            auth.sign_in(customer)
            return redirect(target)
    return render_template("marketplace/verify.html", email=email)


@marketplace_bp.route("/logout", methods=["POST"])
def logout():
    auth.sign_out()
    return redirect(url_for("marketplace.home"))


# --------------------------------------------------------------- booking --

@marketplace_bp.route("/l/<int:listing_id>/book", methods=["POST"])
@limiter.limit("20 per hour", methods=["POST"])
def book(listing_id):
    customer = _login_required()
    if customer is None:
        flash("Sign in to book. We'll bring you straight back.", "info")
        return redirect(url_for("marketplace.login"))
    item = pub.listing_detail(listing_id)
    row = pub.listing_for_booking(listing_id)
    if item is None or row is None:
        abort(404)
    f = request.form
    back = redirect(url_for("marketplace.listing", listing_id=listing_id))
    if f.get("agree") != "1":
        flash("Please accept the terms to continue.", "danger")
        return back
    gstin = (f.get("billing_gstin") or "").strip().upper()
    if gstin and not GSTIN.match(gstin):
        flash("That GSTIN doesn't look right.", "danger")
        return back
    try:
        day = date.fromisoformat(f.get("date", ""))
        with trusted():
            location = row.location
            if item.kind == "room":
                start = mk.local_to_utc(location, day, time.fromisoformat(f.get("start", "")))
                hours = float(f.get("hours", "1"))
                if not 0.5 <= hours <= item.max_length_hours:
                    raise ValueError
                end, units = start + timedelta(hours=hours), 1
            else:
                start = mk.local_to_utc(location, day, time.fromisoformat(item.access_start))
                end = mk.local_to_utc(location, day, time.fromisoformat(item.access_end))
                units = int(f.get("units", "1"))
    except ValueError:
        flash("Check the date, time and quantity you entered.", "danger")
        return back
    with trusted():
        if mk.is_member_of(row.operator_id, customer.email):
            flash(f"You already have an account with {item.seller_name}. Book as a member from their member portal "
                  "for member rates.", "info")
            return back
        try:
            booking = mk.create_booking(
                listing=row, customer=customer, start=start, end=end, units=units,
                guests=int(f.get("guests", "1") or 1), idempotency_key=(f.get("key") or secrets.token_hex(8))[:64],
                payment_method=f.get("payment_method", ""), billing_name=(f.get("billing_name") or "").strip()[:200] or None,
                billing_gstin=gstin or None, allow_membership_contact=f.get("membership_contact") == "1")
        except (mk.MarketplaceError, ValueError) as e:
            db.session.rollback()
            flash(str(e) or "Check the details you entered.", "danger")
            return back
        code = booking.code
    return redirect(url_for("marketplace.booking", code=code))


@marketplace_bp.route("/bookings")
def bookings():
    customer = _login_required()
    if customer is None:
        return redirect(url_for("marketplace.login"))
    return render_template("marketplace/bookings.html", rows=pub.guest_bookings(customer.id))


@marketplace_bp.route("/b/<code>")
def booking(code):
    customer = _login_required()
    if customer is None:
        return redirect(url_for("marketplace.login"))
    item = pub.guest_booking(customer.id, code)
    if item is None:
        abort(404)
    return render_template("marketplace/booking.html", b=item)


def _act(code, action):
    customer = _login_required()
    if customer is None:
        return redirect(url_for("marketplace.login"))
    with trusted():
        row = pub.booking_row(customer.id, code)
        if row is None:
            abort(404)
        try:
            action(row)
        except mk.MarketplaceError as e:
            db.session.rollback()
            flash(str(e), "danger")
    return redirect(url_for("marketplace.booking", code=code))


@marketplace_bp.route("/b/<code>/pay", methods=["POST"])
def booking_pay(code):
    def go(row):
        mk.submit_payment(row, request.form.get("reference", ""))
        flash("Thanks. The space will confirm your payment shortly.", "success")
    return _act(code, go)


@marketplace_bp.route("/b/<code>/cancel", methods=["POST"])
def booking_cancel(code):
    def go(row):
        pct = mk.cancel(row, by_operator=False, reason=request.form.get("reason"))
        flash(f"Booking cancelled. Refund: {pct}%.", "success")
    return _act(code, go)


@marketplace_bp.route("/b/<code>/id", methods=["POST"])
@limiter.limit("10 per hour", methods=["POST"])
def booking_id(code):
    def go(row):
        upload = request.files.get("id_file")
        if upload is None or not upload.filename:
            raise mk.MarketplaceError("Choose a file to upload.")
        mk.upload_id(row, upload)
        flash("ID uploaded. The space will review it before you arrive.", "success")
    return _act(code, go)


@marketplace_bp.route("/b/<code>/upi.png")
def booking_upi(code):
    customer = _login_required()
    if customer is None:
        abort(401)
    with trusted():
        row = pub.booking_row(customer.id, code)
        if row is None or row.status != "held" or row.payment_method != "manual_upi":
            abort(404)
        operator = db.session.get(Operator, row.operator_id)
        details = upi.operator_details(operator)
        uri = upi.upi_uri(details["vpa"], details["payee"], row.total, f"Booking {row.code}")
    if not uri:
        abort(404)
    return Response(upi.qr_png(uri), mimetype="image/png", headers={"Cache-Control": "no-store"})
