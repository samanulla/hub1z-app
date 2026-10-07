"""Operator marketplace controls: what to share, price, caps, windows and the bookings that come in."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
import os

from flask import (abort, current_app, flash, g, redirect, render_template, request, send_from_directory,
                   url_for)
from flask_wtf import FlaskForm
from sqlalchemy import func
from wtforms import (BooleanField, DecimalField, IntegerField, SelectField, SelectMultipleField, StringField,
                     SubmitField, TextAreaField)
from wtforms.validators import DataRequired, Length, NumberRange, Optional
from wtforms import widgets

from ...extensions import db
from ...models import ConferenceRoom, Location, MarketplaceBooking, MarketplaceListing, OperatorMarketplaceTerms
from ...models.marketplace import CANCELLATION_PRESETS, PAYMENT_METHODS
from ...services import marketplace as mk
from ...services.storage import storage_service
from ...utils.decorators import manager_or_super_required

DAYS = [(0, "Mon"), (1, "Tue"), (2, "Wed"), (3, "Thu"), (4, "Fri"), (5, "Sat"), (6, "Sun")]
METHOD_LABELS = {"manual_upi": "UPI (operator confirms)", "bank_transfer": "Bank transfer (operator confirms)",
                 "pay_at_venue": "Pay at the space", "razorpay": "Online payment (coming soon)"}
OFFERED_METHODS = [m for m in PAYMENT_METHODS if m != "razorpay"]


class _Checks(SelectMultipleField):
    widget = widgets.ListWidget(prefix_label=False)
    option_widget = widgets.CheckboxInput()


class ListingForm(FlaskForm):
    resource_type = SelectField("What to share", choices=[("room", "Meeting room (hourly)"),
                                                          ("day_access", "Hot desk / day pass (per day)")])
    room_id = SelectField("Room", coerce=int, default=0)
    location_id = SelectField("Location", coerce=int, default=0)
    title = StringField("Listing title", validators=[DataRequired(), Length(max=160)])
    description = TextAreaField("Description", validators=[Optional(), Length(max=2000)])
    approval_mode = SelectField("Booking", choices=[("instant", "Instant booking"),
                                                    ("request", "Request and confirm")])
    price = DecimalField("Marketplace price (excl. GST)", validators=[NumberRange(min=0)],
                         description="Per hour for rooms, per day for day access. Can differ from the member price.")
    gst_rate_pct = DecimalField("GST %", default=Decimal("18"), validators=[NumberRange(min=0, max=40)])
    daily_cap_units = IntegerField("Max passes per day", validators=[Optional(), NumberRange(min=1, max=1000)])
    daily_cap_hours_pct = IntegerField("Max share of open hours per day (%)",
                                       validators=[Optional(), NumberRange(min=1, max=100)])
    days = _Checks("Available days", coerce=int, choices=DAYS, default=[0, 1, 2, 3, 4, 5, 6])
    window_from = StringField("From (HH:MM)", validators=[Optional(), Length(max=5)])
    window_to = StringField("To (HH:MM)", validators=[Optional(), Length(max=5)])
    blackout_dates = TextAreaField("Blackout dates", validators=[Optional()],
                                   description="One date per line, YYYY-MM-DD.")
    min_lead_hours = IntegerField("Minimum notice (hours)", default=2, validators=[NumberRange(min=0, max=720)])
    max_length_hours = IntegerField("Longest booking (hours)", default=8, validators=[NumberRange(min=1, max=168)])
    max_guests = IntegerField("Max guests", validators=[Optional(), NumberRange(min=1, max=500)])
    id_required = BooleanField("Photo ID checked at the space")
    house_rules = TextAreaField("House rules", validators=[Optional(), Length(max=2000)])
    show_description = BooleanField("Show the description publicly", default=True)
    access_instructions = TextAreaField(
        "Access instructions", validators=[Optional(), Length(max=2000)],
        description="Shown to the guest only after the booking is confirmed and paid (or pay at the space).")
    cancellation_preset = SelectField("Cancellation policy",
                                      choices=[(k, v["label"]) for k, v in CANCELLATION_PRESETS.items()])
    submit = SubmitField("Save")

    def validate(self, extra_validators=None):
        ok = super().validate(extra_validators)
        if self.resource_type.data == "room" and not self.room_id.data:
            self.room_id.errors.append("Choose a room.")
            ok = False
        if self.resource_type.data == "day_access":
            if not self.location_id.data:
                self.location_id.errors.append("Choose a location.")
                ok = False
            if not self.daily_cap_units.data:
                self.daily_cap_units.errors.append("Set how many passes you will share each day.")
                ok = False
        if self.resource_type.data == "room" and not self.daily_cap_hours_pct.data:
            self.daily_cap_hours_pct.errors.append("Set the share of the room's hours you will share.")
            ok = False
        for name in ("window_from", "window_to"):
            value = getattr(self, name).data
            if value:
                try:
                    h, m = value.split(":")
                    assert 0 <= int(h) < 24 and 0 <= int(m) < 60
                except (ValueError, AssertionError):
                    getattr(self, name).errors.append("Use HH:MM.")
                    ok = False
        for line in (self.blackout_dates.data or "").splitlines():
            if line.strip():
                try:
                    date.fromisoformat(line.strip())
                except ValueError:
                    self.blackout_dates.errors.append(f"'{line.strip()}' is not a date (YYYY-MM-DD).")
                    ok = False
        return ok


def _terms() -> OperatorMarketplaceTerms:
    terms = OperatorMarketplaceTerms.query.filter_by(operator_id=g.operator_id).first()
    if terms is None:
        terms = OperatorMarketplaceTerms(operator_id=g.operator_id)
        db.session.add(terms)
        db.session.commit()
    return terms


def _fill_choices(form: ListingForm) -> None:
    rooms = (ConferenceRoom.query.filter_by(operator_id=g.operator_id, is_active=True)
             .order_by(ConferenceRoom.name).all())
    form.room_id.choices = [(0, "Choose a room")] + [(r.id, f"{r.name} · {r.location.name}") for r in rooms]
    locations = Location.query.filter_by(operator_id=g.operator_id, is_active=True).order_by(Location.name).all()
    form.location_id.choices = [(0, "Choose a location")] + [(loc.id, loc.name) for loc in locations]


def _apply(form: ListingForm, listing: MarketplaceListing) -> None:
    listing.title = form.title.data.strip()
    listing.description = (form.description.data or "").strip() or None
    listing.approval_mode = form.approval_mode.data
    listing.price = form.price.data
    listing.gst_rate_pct = form.gst_rate_pct.data
    listing.daily_cap_units = form.daily_cap_units.data if listing.resource_type == "day_access" else None
    listing.daily_cap_hours_pct = form.daily_cap_hours_pct.data if listing.resource_type == "room" else None
    days = sorted(form.days.data or [])
    windows = []
    if form.window_from.data or form.window_to.data or len(days) < 7:
        windows = [{"days": days, "from": form.window_from.data or "00:00", "to": form.window_to.data or "23:59"}]
    listing.availability_windows = windows
    listing.blackout_dates = sorted({ln.strip() for ln in (form.blackout_dates.data or "").splitlines() if ln.strip()})
    listing.min_lead_hours = form.min_lead_hours.data
    listing.max_length_hours = form.max_length_hours.data
    listing.guest_rules = {"max_guests": form.max_guests.data, "id_required": bool(form.id_required.data),
                           "house_rules": (form.house_rules.data or "").strip()}
    listing.visibility = {"description": bool(form.show_description.data)}
    listing.access_instructions = (form.access_instructions.data or "").strip() or None
    listing.cancellation_preset = form.cancellation_preset.data


def _form_from(listing: MarketplaceListing) -> ListingForm:
    windows = (listing.availability_windows or [{}])[0]
    rules = listing.guest_rules or {}
    form = ListingForm(obj=listing, data={
        "days": windows.get("days", [0, 1, 2, 3, 4, 5, 6]),
        "window_from": windows.get("from", "") if listing.availability_windows else "",
        "window_to": windows.get("to", "") if listing.availability_windows else "",
        "blackout_dates": "\n".join(listing.blackout_dates or []),
        "max_guests": rules.get("max_guests"), "id_required": rules.get("id_required", False),
        "house_rules": rules.get("house_rules", ""),
        "show_description": (listing.visibility or {}).get("description", True),
        "room_id": listing.room_id or 0, "location_id": listing.location_id})
    return form


def register_marketplace_routes(bp):

    def _gate():
        if not current_app.config.get("MARKETPLACE_ENABLED"):
            abort(404)

    def _own_listing(listing_id: int) -> MarketplaceListing:
        listing = MarketplaceListing.query.filter_by(id=listing_id, operator_id=g.operator_id).first()
        if listing is None:
            abort(404)
        return listing

    def _own_booking(booking_id: int) -> MarketplaceBooking:
        booking = MarketplaceBooking.query.filter_by(id=booking_id, operator_id=g.operator_id).first()
        if booking is None:
            abort(404)
        return booking

    @bp.route("/marketplace")
    @manager_or_super_required
    def marketplace():
        _gate()
        terms = _terms()
        listings = (MarketplaceListing.query.filter_by(operator_id=g.operator_id)
                    .order_by(MarketplaceListing.created_at.desc()).all())
        counts = dict(db.session.query(MarketplaceBooking.status, func.count())
                      .filter(MarketplaceBooking.operator_id == g.operator_id)
                      .group_by(MarketplaceBooking.status).all())
        return render_template("admin/marketplace/index.html", terms=terms, listings=listings, counts=counts,
                               method_labels=METHOD_LABELS, offered=OFFERED_METHODS)

    @bp.route("/marketplace/settings", methods=["POST"])
    @manager_or_super_required
    def marketplace_settings():
        _gate()
        terms = _terms()
        terms.enabled = request.form.get("enabled") == "1"
        methods = [m for m in request.form.getlist("payment_methods") if m in OFFERED_METHODS]
        if not methods:
            flash("Choose at least one way for guests to pay.", "warning")
            return redirect(url_for("admin.marketplace"))
        terms.payment_methods = methods
        try:
            comp = Decimal(request.form.get("compensation") or "0")
            if not Decimal(0) <= comp <= Decimal(100):
                raise ValueError
        except (ArithmeticError, ValueError):
            flash("Compensation must be between 0 and 100.", "warning")
            return redirect(url_for("admin.marketplace"))
        terms.operator_cancel_compensation_pct = comp
        if terms.enabled and not terms.accepted_terms_at:
            terms.accepted_terms_at = datetime.utcnow()
        db.session.commit()
        flash("Marketplace settings saved.", "success")
        return redirect(url_for("admin.marketplace"))

    @bp.route("/marketplace/listings/new", methods=["GET", "POST"])
    @manager_or_super_required
    def marketplace_listing_new():
        _gate()
        form = ListingForm()
        _fill_choices(form)
        if form.validate_on_submit():
            kind = form.resource_type.data
            if kind == "room":
                room = ConferenceRoom.query.filter_by(id=form.room_id.data, operator_id=g.operator_id).first()
                if room is None:
                    abort(404)
                location_id, room_id = room.location_id, room.id
            else:
                if Location.query.filter_by(id=form.location_id.data, operator_id=g.operator_id).first() is None:
                    abort(404)
                location_id, room_id = form.location_id.data, None
            listing = MarketplaceListing(operator_id=g.operator_id, resource_type=kind, location_id=location_id,
                                         room_id=room_id, status="draft")
            _apply(form, listing)
            db.session.add(listing)
            db.session.commit()
            flash("Listing saved as a draft. Nothing is public until you publish it.", "success")
            return redirect(url_for("admin.marketplace"))
        return render_template("admin/marketplace/listing_form.html", form=form, title="New listing", listing=None)

    @bp.route("/marketplace/listings/<int:listing_id>/edit", methods=["GET", "POST"])
    @manager_or_super_required
    def marketplace_listing_edit(listing_id):
        _gate()
        listing = _own_listing(listing_id)
        form = _form_from(listing) if request.method == "GET" else ListingForm()
        _fill_choices(form)
        if request.method == "POST":
            form.resource_type.data = listing.resource_type
            form.room_id.data = listing.room_id or 0
            form.location_id.data = listing.location_id
        if form.validate_on_submit():
            _apply(form, listing)
            db.session.commit()
            flash("Listing updated. Existing bookings keep the terms they were made under.", "success")
            return redirect(url_for("admin.marketplace"))
        return render_template("admin/marketplace/listing_form.html", form=form, title="Edit listing",
                               listing=listing)

    @bp.route("/marketplace/listings/<int:listing_id>/status", methods=["POST"])
    @manager_or_super_required
    def marketplace_listing_status(listing_id):
        _gate()
        listing = _own_listing(listing_id)
        status = request.form.get("status", "")
        if status == "live":
            terms = _terms()
            if not (terms.enabled and terms.accepted_terms_at):
                flash("Turn on the marketplace and accept the terms first.", "warning")
                return redirect(url_for("admin.marketplace"))
            if not terms.kyc_approved:
                flash("Hub1z needs to approve your marketplace access before listings can go live.", "warning")
                return redirect(url_for("admin.marketplace"))
        try:
            mk.set_listing_status(listing, status)
        except mk.MarketplaceError as e:
            flash(str(e), "warning")
        else:
            flash({"live": "Listing is live.", "paused": "Listing paused: no new bookings, existing ones stand.",
                   "unlisted": "Listing removed. Undecided requests were declined.",
                   "draft": "Listing moved back to draft."}[status], "success")
        return redirect(url_for("admin.marketplace"))

    @bp.route("/marketplace/bookings")
    @manager_or_super_required
    def marketplace_bookings():
        _gate()
        status = request.args.get("status", "open")
        q = MarketplaceBooking.query.filter_by(operator_id=g.operator_id)
        groups = {"open": ("requested", "held", "confirmed", "checked_in"), "requests": ("requested",),
                  "past": ("completed", "no_show", "cancelled_customer", "cancelled_operator", "declined", "expired")}
        if status in groups:
            q = q.filter(MarketplaceBooking.status.in_(groups[status]))
        rows = q.order_by(MarketplaceBooking.start_at.desc()).limit(300).all()
        return render_template("admin/marketplace/bookings.html", rows=rows, status=status,
                               method_labels=METHOD_LABELS)

    @bp.route("/marketplace/bookings/<int:booking_id>/id-document")
    @manager_or_super_required
    def marketplace_id_document(booking_id):
        _gate()
        booking = _own_booking(booking_id)
        if not booking.id_document_key:
            abort(404)
        if current_app.config.get("STORAGE_BACKEND", "local") == "local":
            response = send_from_directory(os.path.abspath(current_app.config["LOCAL_STORAGE_DIR"]),
                                           booking.id_document_key, download_name=booking.id_document_name)
        else:
            response = redirect(storage_service.signed_url(booking.id_document_key, ttl_seconds=300, scope="operator",
                                                           filename=booking.id_document_name))
        response.headers["Cache-Control"] = "no-store"
        return response

    @bp.route("/marketplace/bookings/<int:booking_id>/<action>", methods=["POST"])
    @manager_or_super_required
    def marketplace_booking_action(booking_id, action):
        _gate()
        booking = _own_booking(booking_id)
        reason = (request.form.get("reason") or "").strip() or None
        try:
            if action == "approve":
                mk.approve(booking)
                flash("Request approved.", "success")
            elif action == "decline":
                mk.decline(booking, reason)
                flash("Request declined.", "success")
            elif action == "confirm_payment":
                mk.confirm_payment(booking)
                flash("Payment confirmed. The guest can now see the access details.", "success")
            elif action == "cancel":
                pct = mk.cancel(booking, by_operator=True, reason=reason)
                flash(f"Booking cancelled; the guest is refunded {pct}%.", "success")
            elif action == "check_in":
                mk.check_in(booking)
                flash("Guest checked in.", "success")
            elif action == "no_show":
                mk.mark_no_show(booking)
                flash("Marked as a no-show.", "success")
            elif action == "complete":
                mk.complete(booking)
                flash("Booking completed.", "success")
            elif action == "approve_id":
                mk.review_id(booking, True)
                flash("ID approved. The guest can now see the access details.", "success")
            elif action == "reject_id":
                mk.review_id(booking, False, reason)
                flash("ID rejected. The guest was asked to upload a valid one.", "success")
            elif action == "reject_id_venue":
                try:
                    refund = int(request.form.get("refund") or 0)
                except ValueError:
                    refund = 0
                pct = mk.reject_id_at_venue(booking, reason or "", refund)
                flash(f"Guest turned away; booking cancelled with a {pct}% refund.", "success")
            else:
                abort(404)
        except mk.MarketplaceError as e:
            db.session.rollback()
            flash(str(e), "warning")
        return redirect(request.referrer or url_for("admin.marketplace_bookings"))
