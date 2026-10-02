"""Leads pages, registered on both the operator back office (/admin/leads) and the Platform (/platform/leads)."""
from __future__ import annotations

import csv
import io
from datetime import date

from flask import render_template, redirect, url_for, flash, request, abort, jsonify, Response
from flask_login import current_user
from flask_wtf import FlaskForm
from wtforms import StringField, IntegerField, DecimalField, SelectField, TextAreaField, DateField
from wtforms.validators import DataRequired, Length, Optional, NumberRange, Email

from ..extensions import db
from ..models import Lead
from ..services import audit_service
from ..services import leads as svc


class LeadForm(FlaskForm):
    name = StringField("Contact name", validators=[DataRequired(), Length(max=160)])
    company_name = StringField("Company", validators=[Optional(), Length(max=200)])
    phone = StringField("Phone", validators=[Optional(), Length(max=40)])
    email = StringField("Email", validators=[Optional(), Email(), Length(max=255)])
    interest = StringField("Interested in", validators=[Optional(), Length(max=200)])
    seats = IntegerField("Seats", validators=[Optional(), NumberRange(min=1, max=100000)])
    expected_value = DecimalField("Expected value per month (₹)", places=0, validators=[Optional(), NumberRange(min=0)])
    source = SelectField("Source", validators=[Optional()])
    stage = SelectField("Stage", validators=[DataRequired()])
    temperature = SelectField("Temperature", choices=[(k, label) for k, label, _ in svc.TEMPERATURES])
    owner_id = SelectField("Owner", coerce=int)
    next_follow_up = DateField("Next follow-up", validators=[Optional()])
    notes = TextAreaField("Notes", validators=[Optional(), Length(max=4000)])


class WebsiteEnquiryForm(FlaskForm):
    name = StringField("Name", validators=[DataRequired(), Length(max=160)])
    email = StringField("Email", validators=[DataRequired(), Email(), Length(max=255)])
    phone = StringField("Phone", validators=[Optional(), Length(max=40)])
    interest = StringField("Requirement", validators=[Optional(), Length(max=200)])


def _prepare(form: LeadForm, scope: str) -> LeadForm:
    form.source.choices = [("", "Not set")] + [(s, s) for s in svc.SOURCES[scope]]
    form.stage.choices = [(k, label) for k, label, _ in svc.stages(scope)]
    form.owner_id.choices = [(0, "Unassigned")] + [(u.id, u.full_name) for u in svc.owner_choices(scope)]
    return form


def register_lead_routes(bp, scope: str, guard):
    """Add the Leads routes to ``bp``. ``guard`` is the access decorator for this area."""
    name = bp.name

    def get_lead(lead_id: int) -> Lead:
        return svc.lead_query(scope).filter(Lead.id == lead_id).first_or_404()

    def owner_ids() -> set[int]:
        return {u.id for u in svc.owner_choices(scope)}

    @bp.route("/leads")
    @guard
    def leads():
        today = date.today()
        everything = svc.lead_query(scope).order_by(Lead.updated_at.desc()).all()
        owner = request.args.get("owner", type=int)
        source = request.args.get("source", "")
        rows = [l for l in everything
                if (not owner or l.owner_id == owner) and (not source or l.source == source)]
        board = {key: [l for l in rows if l.stage == key] for key, _, _ in svc.board_stages(scope)}
        due = {l.id: svc.due_state(l, today) for l in rows}
        return render_template("leads/board.html", bp=name, scope=scope, leads=rows, board=board, due=due,
                               stages=svc.stages(scope), board_stages=svc.board_stages(scope),
                               stage_tint={k: t for k, _, t in svc.stages(scope)},
                               stage_names={k: n for k, n, _ in svc.stages(scope)},
                               temps={k: (label, tint) for k, label, tint in svc.TEMPERATURES},
                               stats=svc.summary(everything), owners=svc.owner_choices(scope),
                               sources=svc.SOURCES[scope], owner=owner, source=source,
                               view="list" if request.args.get("view") == "list" else "board")

    @bp.route("/leads/new", methods=["GET", "POST"])
    @guard
    def lead_new():
        form = _prepare(LeadForm(), scope)
        if request.method == "GET":
            form.stage.data = svc.stages(scope)[0][0]
            form.owner_id.data = current_user.id if current_user.id in owner_ids() else 0
        if form.validate_on_submit():
            first = svc.stages(scope)[0][0]
            lead = Lead(stage=first)
            _fill(lead, form)
            db.session.add(lead)
            db.session.flush()
            svc.add_activity(lead, "note", "Lead added", current_user)
            if form.stage.data != first:
                svc.move_stage(scope, lead, form.stage.data, current_user)
            audit_service.record("lead.created", "lead", lead.id, {"name": lead.name})
            db.session.commit()
            flash("Lead added.", "success")
            return redirect(url_for(f"{name}.lead_detail", lead_id=lead.id))
        return render_template("leads/form.html", bp=name, scope=scope, form=form, title="Add lead", lead=None)

    def _fill(lead: Lead, form: LeadForm) -> None:
        lead.name = form.name.data.strip()
        lead.company_name = (form.company_name.data or "").strip() or None
        lead.phone = (form.phone.data or "").strip() or None
        lead.email = (form.email.data or "").strip() or None
        lead.interest = (form.interest.data or "").strip() or None
        lead.seats = form.seats.data
        lead.expected_value = form.expected_value.data or 0
        lead.source = form.source.data or None
        lead.temperature = form.temperature.data
        lead.owner_id = form.owner_id.data if form.owner_id.data in owner_ids() else None
        lead.next_follow_up = form.next_follow_up.data
        lead.notes = (form.notes.data or "").strip() or None

    @bp.route("/leads/<int:lead_id>")
    @guard
    def lead_detail(lead_id: int):
        lead = get_lead(lead_id)
        return render_template("leads/detail.html", bp=name, scope=scope, lead=lead,
                               state=svc.due_state(lead, date.today()), stages=svc.stages(scope),
                               stage_tint={k: t for k, _, t in svc.stages(scope)},
                               stage_names={k: n for k, n, _ in svc.stages(scope)},
                               temps={k: (label, tint) for k, label, tint in svc.TEMPERATURES},
                               kinds=svc.ACTIVITY_KINDS)

    @bp.route("/leads/<int:lead_id>/edit", methods=["GET", "POST"])
    @guard
    def lead_edit(lead_id: int):
        lead = get_lead(lead_id)
        form = _prepare(LeadForm(obj=lead), scope)
        if request.method == "GET":
            form.owner_id.data = lead.owner_id or 0
            form.source.data = lead.source or ""
        if form.validate_on_submit():
            _fill(lead, form)
            if form.stage.data != lead.stage:
                svc.move_stage(scope, lead, form.stage.data, current_user)
            db.session.commit()
            flash("Lead updated.", "success")
            return redirect(url_for(f"{name}.lead_detail", lead_id=lead.id))
        return render_template("leads/form.html", bp=name, scope=scope, form=form, title=f"Edit {lead.name}", lead=lead)

    @bp.route("/leads/<int:lead_id>/move", methods=["POST"])
    @guard
    def lead_move(lead_id: int):
        lead = get_lead(lead_id)
        payload = request.get_json(silent=True) or request.form
        stage = (payload.get("stage") or "").strip()
        changed = svc.move_stage(scope, lead, stage, current_user, payload.get("reason"))
        wants_json = request.is_json or request.accept_mimetypes.best == "application/json"
        if not changed and stage not in {k for k, _, _ in svc.stages(scope)}:
            if wants_json:
                return jsonify(ok=False, error="Unknown stage"), 400
            abort(400)
        db.session.commit()
        if wants_json:
            state, text = svc.due_state(lead, date.today())
            return jsonify(ok=True, stage=lead.stage, label=svc.stage_label(scope, lead.stage), due=state, due_text=text)
        flash(f"Moved to {svc.stage_label(scope, lead.stage)}.", "success")
        return redirect(url_for(f"{name}.lead_detail", lead_id=lead.id))

    @bp.route("/leads/<int:lead_id>/note", methods=["POST"])
    @guard
    def lead_note(lead_id: int):
        lead = get_lead(lead_id)
        body = (request.form.get("body") or "").strip()
        kind = request.form.get("kind", "note")
        if kind not in {k for k, _ in svc.ACTIVITY_KINDS}:
            kind = "note"
        if body:
            svc.add_activity(lead, kind, body[:2000], current_user)
            follow_up = request.form.get("next_follow_up")
            if follow_up:
                try:
                    lead.next_follow_up = date.fromisoformat(follow_up)
                except ValueError:
                    flash("That follow-up date was not understood.", "warning")
            db.session.commit()
            flash("Logged.", "success")
        return redirect(url_for(f"{name}.lead_detail", lead_id=lead.id))

    @bp.route("/leads/<int:lead_id>/delete", methods=["POST"])
    @guard
    def lead_delete(lead_id: int):
        lead = get_lead(lead_id)
        audit_service.record("lead.deleted", "lead", lead.id, {"name": lead.name})
        db.session.delete(lead)
        db.session.commit()
        flash("Lead deleted.", "info")
        return redirect(url_for(f"{name}.leads"))

    @bp.route("/leads/export.csv")
    @guard
    def leads_export():
        out = io.StringIO()
        w = csv.writer(out)
        w.writerow(["Name", "Company", "Phone", "Email", "Interested in", "Seats", "Expected per month (INR)",
                    "Source", "Stage", "Temperature", "Owner", "Next follow-up", "Created"])
        for l in svc.lead_query(scope).order_by(Lead.created_at.desc()).all():
            w.writerow([l.name, l.company_name or "", l.phone or "", l.email or "", l.interest or "", l.seats or "",
                        int(l.expected_value or 0), l.source or "", svc.stage_label(scope, l.stage), l.temperature,
                        l.owner.full_name if l.owner else "", l.next_follow_up or "", l.created_at.strftime("%Y-%m-%d")])
        return Response(out.getvalue(), mimetype="text/csv",
                        headers={"Content-Disposition": "attachment; filename=leads.csv"})
