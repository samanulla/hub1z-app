"""Operator Credits pages: the pool, allocations, rules and the activity log."""
from __future__ import annotations

from flask import flash, g, redirect, render_template, request, url_for
from flask_login import current_user

from ...extensions import db
from ...models import (
    Company, CompanyStatus, CreditAllocation, CreditLedger, CreditLot, CreditSettings, LedgerType,
    RoomCategory, SeatBand, Subscription, SubscriptionStatus, User, UserRole,
)
from ...services import audit_service, credit_service
from ...services.credit_service import CreditError
from ...utils.decorators import manager_or_super_required
from .credit_forms import (
    AllocateForm, BonusForm, CreditSettingsForm, RoomCategoryForm, SeatBandForm,
)


def _subject_choices() -> list[tuple[str, str]]:
    companies = Company.query.filter_by(status=CompanyStatus.ACTIVE).order_by(Company.name).all()
    people = User.query.filter_by(role=UserRole.INDIVIDUAL, is_active=True).order_by(User.full_name).all()
    return ([(f"c:{c.id}", f"Company \u00b7 {c.name}") for c in companies]
            + [(f"u:{u.id}", f"Individual \u00b7 {u.full_name}") for u in people])


def _parse_subject(value: str) -> dict:
    kind, _, sid = value.partition(":")
    return {"company_id": int(sid) if kind == "c" else None, "user_id": int(sid) if kind == "u" else None}


def _flash_errors(form) -> None:
    for errors in form.errors.values():
        for e in errors:
            flash(e, "danger")


def register_credit_routes(bp):

    @bp.route("/credits")
    @manager_or_super_required
    def credits_overview():
        oid = g.operator_id
        credit_service.seed_default_categories(oid)
        db.session.commit()
        pool = credit_service.pool_summary(oid)
        usage = pool["usage"]

        allocations = {(a.company_id, a.user_id): a for a in CreditAllocation.query.all()}
        rows = []
        for c in Company.query.filter_by(status=CompanyStatus.ACTIVE).order_by(Company.name).all():
            seats = sum(s.quantity for s in Subscription.query.filter_by(
                company_id=c.id, status=SubscriptionStatus.ACTIVE).all())
            rows.append(_row(oid, "Company", c.name, f"c:{c.id}", allocations.get((c.id, None)),
                             usage.get((c.id, None)), seats, {"company_id": c.id}))
        for a in [a for a in allocations.values() if a.user_id]:
            rows.append(_row(oid, "Individual", a.user.full_name, f"u:{a.user_id}", a,
                             usage.get((None, a.user_id)), None, {"user_id": a.user_id}))

        allocate_form, bonus_form = AllocateForm(), BonusForm()
        allocate_form.subject.choices = bonus_form.subject.choices = _subject_choices()
        pre = request.args.get("subject")
        if pre:
            allocate_form.subject.data = bonus_form.subject.data = pre

        segments = [
            {"key": "used", "label": "Used", "value": pool["used"]},
            {"key": "reserved", "label": "Reserved (booked ahead)", "value": pool["reserved"]},
            {"key": "blocked", "label": "Blocked", "value": 0},
            {"key": "available", "label": "Allocated, still free", "value": pool["available"]},
            {"key": "unallocated", "label": "Not allocated yet", "value": pool["unallocated"]},
            {"key": "reserve", "label": "Kept for new signups", "value": pool["reserve"]},
        ]
        return render_template("admin/credits/overview.html", pool=pool, segments=segments, rows=rows,
                               allocate_form=allocate_form, bonus_form=bonus_form,
                               settings=CreditSettings.for_operator(oid))

    def _row(oid, kind, name, key, alloc, use, seats, subject):
        bal = credit_service.balance(oid, **subject)
        use = use or {"used": 0, "reserved": 0}
        return {
            "kind": kind, "name": name, "key": key, "seats": seats,
            "suggested": credit_service.suggest_credits(oid, seats) if seats else None,
            "monthly": alloc.monthly_credits if alloc else None,
            "pending": alloc.pending_monthly_credits if alloc else None,
            "pending_from": alloc.pending_from if alloc else None,
            "used": use["used"], "reserved": use["reserved"], "bal": bal,
        }

    @bp.route("/credits/allocate", methods=["POST"])
    @manager_or_super_required
    def credits_allocate():
        form = AllocateForm()
        form.subject.choices = _subject_choices()
        if not form.validate_on_submit():
            _flash_errors(form)
            return redirect(url_for("admin.credits_overview"))
        try:
            result = credit_service.allocate(g.operator_id, monthly=form.monthly_credits.data,
                                             actor=current_user, **_parse_subject(form.subject.data))
            db.session.commit()
        except CreditError as e:
            db.session.rollback()
            flash(str(e), "danger")
            return redirect(url_for("admin.credits_overview", subject=form.subject.data))
        audit_service.record("credits.allocated", "credit_allocation", None,
                             {"subject": form.subject.data, "monthly": result["credits"]})
        flash(f"Allocated {result['credits']} credits a month (starts {result['starts']}).", "success")
        if result["warning"]:
            flash(result["warning"], "warning")
        return redirect(url_for("admin.credits_overview"))

    @bp.route("/credits/bonus", methods=["POST"])
    @manager_or_super_required
    def credits_bonus():
        form = BonusForm()
        form.subject.choices = _subject_choices()
        if not form.validate_on_submit():
            _flash_errors(form)
            return redirect(url_for("admin.credits_overview"))
        try:
            credit_service.grant_bonus(g.operator_id, credits=form.credits.data, actor=current_user,
                                       note=form.note.data or None, **_parse_subject(form.subject.data))
            db.session.commit()
        except CreditError as e:
            db.session.rollback()
            flash(str(e), "danger")
            return redirect(url_for("admin.credits_overview"))
        audit_service.record("credits.bonus", "credit_lot", None,
                             {"subject": form.subject.data, "credits": form.credits.data})
        flash(f"Gave {form.credits.data} bonus credits. They expire at the end of this month.", "success")
        return redirect(url_for("admin.credits_overview"))

    # ---------------------------------------------------------- settings --
    @bp.route("/credits/settings", methods=["GET", "POST"])
    @manager_or_super_required
    def credits_settings():
        oid = g.operator_id
        settings = CreditSettings.for_operator(oid)
        form = CreditSettingsForm(obj=settings)
        if form.validate_on_submit():
            form.populate_obj(settings)
            db.session.commit()
            audit_service.record("credits.settings", "credit_settings", settings.id, {})
            flash("Credit settings saved.", "success")
            return redirect(url_for("admin.credits_settings"))
        credit_service.seed_default_categories(oid)
        db.session.commit()
        categories = RoomCategory.query.order_by(RoomCategory.credits_per_slot, RoomCategory.name).all()
        bands = SeatBand.query.order_by(SeatBand.min_seats).all()
        return render_template("admin/credits/settings.html", form=form, categories=categories, bands=bands,
                               category_form=RoomCategoryForm(), band_form=SeatBandForm())

    @bp.route("/credits/categories/new", methods=["POST"])
    @manager_or_super_required
    def credits_category_new():
        form = RoomCategoryForm()
        if form.validate_on_submit():
            if RoomCategory.query.filter_by(name=form.name.data.strip()).first():
                flash("A category with that name already exists.", "danger")
            else:
                db.session.add(RoomCategory(operator_id=g.operator_id, name=form.name.data.strip(),
                                            credits_per_slot=form.credits_per_slot.data,
                                            hourly_rate=form.hourly_rate.data, is_active=form.is_active.data))
                db.session.commit()
                flash("Category added.", "success")
        else:
            _flash_errors(form)
        return redirect(url_for("admin.credits_settings"))

    @bp.route("/credits/categories/<int:category_id>", methods=["GET", "POST"])
    @manager_or_super_required
    def credits_category_edit(category_id: int):
        category = RoomCategory.query.get_or_404(category_id)
        form = RoomCategoryForm(obj=category)
        if form.validate_on_submit():
            clash = RoomCategory.query.filter(RoomCategory.name == form.name.data.strip(),
                                              RoomCategory.id != category.id).first()
            if clash:
                flash("A category with that name already exists.", "danger")
            else:
                form.populate_obj(category)
                category.name = category.name.strip()
                db.session.commit()
                flash("Category updated.", "success")
                return redirect(url_for("admin.credits_settings"))
        return render_template("admin/credits/form.html", form=form, title=f"Edit category \u00b7 {category.name}",
                               back=url_for("admin.credits_settings"))

    @bp.route("/credits/bands/new", methods=["POST"])
    @manager_or_super_required
    def credits_band_new():
        form = SeatBandForm()
        if not form.validate_on_submit():
            _flash_errors(form)
        elif credit_service.band_overlaps(g.operator_id, form.min_seats.data, form.max_seats.data):
            flash("That seat range overlaps an existing band.", "danger")
        else:
            db.session.add(SeatBand(operator_id=g.operator_id, min_seats=form.min_seats.data,
                                    max_seats=form.max_seats.data, monthly_credits=form.monthly_credits.data))
            db.session.commit()
            flash("Seat band added. It applies to companies subscribing from now on.", "success")
        return redirect(url_for("admin.credits_settings"))

    @bp.route("/credits/bands/<int:band_id>/delete", methods=["POST"])
    @manager_or_super_required
    def credits_band_delete(band_id: int):
        db.session.delete(SeatBand.query.get_or_404(band_id))
        db.session.commit()
        flash("Seat band removed.", "info")
        return redirect(url_for("admin.credits_settings"))

    # ---------------------------------------------------------- activity --
    @bp.route("/credits/activity")
    @manager_or_super_required
    def credits_activity():
        q = CreditLedger.query.join(CreditLot, CreditLedger.lot_id == CreditLot.id)
        subject = request.args.get("subject", "")
        kind = request.args.get("type", "")
        if subject:
            parsed = _parse_subject(subject)
            q = q.filter(CreditLot.company_id == parsed["company_id"]) if parsed["company_id"] \
                else q.filter(CreditLot.user_id == parsed["user_id"])
        if kind in {t.value for t in LedgerType}:
            q = q.filter(CreditLedger.entry_type == LedgerType(kind))
        entries = q.order_by(CreditLedger.id.desc()).limit(200).all()
        return render_template("admin/credits/activity.html", entries=entries, subject=subject, kind=kind,
                               subjects=_subject_choices(), types=[t.value for t in LedgerType])
