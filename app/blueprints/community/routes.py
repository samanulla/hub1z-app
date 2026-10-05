"""Community/premium features blueprint (Phase 4).

Guest passes, visitors, community directory, announcements, printing credits,
support tickets, lockers, referrals — thin CRUD + list views.
"""
from __future__ import annotations

from datetime import date, datetime

from flask import (Blueprint, render_template, request, redirect, url_for,
                   flash, g, abort)
from flask_login import current_user, login_required

from ...extensions import db
from ...models import (
    GuestPass, GuestPassStatus,
    Visitor, VisitorStatus,
    CommunityProfile,
    Announcement,
    PrintingLedger,
    SupportTicket, TicketStatus, TicketPriority,
    Locker, LockerStatus,
    Referral, ReferralStatus,
    Location, User, UserRole,
)
from ...utils.decorators import (
    member_required, admin_required, company_admin_required,
)
from ...services import audit_service, mail_service


community_bp = Blueprint("community", __name__,
                         template_folder="../../templates")


# ================== Guest passes ==================

@community_bp.route("/guest-passes", methods=["GET", "POST"])
@login_required
def guest_passes():
    """Members and company admins can issue guest passes."""
    if request.method == "POST":
        try:
            loc_id = int(request.form["location_id"])
            visit_date = date.fromisoformat(request.form.get("visit_date")
                                            or date.today().isoformat())
        except (KeyError, ValueError):
            flash("Invalid guest pass.", "warning")
            return redirect(url_for("community.guest_passes"))
        gp = GuestPass(
            operator_id=getattr(g, "operator_id", None),
            issuer_id=current_user.id,
            company_id=current_user.company_id,
            location_id=loc_id,
            guest_name=(request.form.get("guest_name") or "").strip(),
            guest_email=(request.form.get("guest_email") or None),
            visit_date=visit_date,
            code=GuestPass.new_code(),
            status=GuestPassStatus.ISSUED,
        )
        if not gp.guest_name:
            flash("Guest name is required.", "warning")
            return redirect(url_for("community.guest_passes"))
        db.session.add(gp); db.session.commit()
        flash(f"Guest pass issued for {gp.guest_name}. Code: {gp.code}", "success")
        return redirect(url_for("community.guest_passes"))

    mine = (GuestPass.query.filter_by(issuer_id=current_user.id)
                            .order_by(GuestPass.visit_date.desc()).limit(50).all())
    locations = Location.query.filter_by(is_active=True).all()
    return render_template("community/guest_passes.html",
                           passes=mine, locations=locations, today=date.today())


# ================== Visitor pre-registration ==================

@community_bp.route("/visitors", methods=["GET", "POST"])
@login_required
def visitors():
    if request.method == "POST":
        try:
            loc_id = int(request.form["location_id"])
            expected = datetime.fromisoformat(request.form["expected_at"])
        except (KeyError, ValueError):
            flash("Invalid visitor.", "warning")
            return redirect(url_for("community.visitors"))
        v = Visitor(
            operator_id=getattr(g, "operator_id", None),
            host_user_id=current_user.id,
            location_id=loc_id,
            name=(request.form.get("name") or "").strip(),
            email=request.form.get("email"),
            phone=request.form.get("phone"),
            company=request.form.get("company"),
            purpose=request.form.get("purpose"),
            expected_at=expected,
            status=VisitorStatus.PENDING,
        )
        if not v.name:
            flash("Visitor name is required.", "warning")
            return redirect(url_for("community.visitors"))
        db.session.add(v); db.session.commit()
        flash(f"Visitor {v.name} pre-registered.", "success")
        return redirect(url_for("community.visitors"))

    mine = (Visitor.query.filter_by(host_user_id=current_user.id)
                          .order_by(Visitor.expected_at.desc()).limit(50).all())
    locations = Location.query.filter_by(is_active=True).all()
    return render_template("community/visitors.html",
                           visitors=mine, locations=locations)


@community_bp.route("/visitors/<int:vid>/check-in", methods=["POST"])
@admin_required
def visitor_check_in(vid: int):
    v = Visitor.query.get_or_404(vid)
    v.status = VisitorStatus.CHECKED_IN
    v.checked_in_at = datetime.utcnow()
    db.session.commit()
    flash(f"{v.name} checked in.", "success")
    return redirect(url_for("community.visitors_reception"))


@community_bp.route("/visitors/<int:vid>/check-out", methods=["POST"])
@admin_required
def visitor_check_out(vid: int):
    v = Visitor.query.get_or_404(vid)
    v.status = VisitorStatus.CHECKED_OUT
    v.checked_out_at = datetime.utcnow()
    db.session.commit()
    flash(f"{v.name} checked out.", "info")
    return redirect(url_for("community.visitors_reception"))


@community_bp.route("/reception/visitors")
@admin_required
def visitors_reception():
    """Reception view: today's expected + already-checked-in visitors."""
    today = date.today()
    expected = (Visitor.query
                       .filter(Visitor.status.in_([VisitorStatus.PENDING,
                                                    VisitorStatus.CHECKED_IN]))
                       .order_by(Visitor.expected_at).limit(200).all())
    return render_template("community/visitors_reception.html",
                           visitors=expected, today=today)


# ================== Community directory ==================

@community_bp.route("/community")
@login_required
def directory():
    profiles = (CommunityProfile.query.filter_by(is_public=True)
                                        .order_by(CommunityProfile.created_at.desc())
                                        .limit(200).all())
    return render_template("community/directory.html", profiles=profiles)


@community_bp.route("/community/profile", methods=["GET", "POST"])
@login_required
def edit_profile():
    p = CommunityProfile.query.filter_by(user_id=current_user.id).first()
    if p is None:
        p = CommunityProfile(operator_id=getattr(g, "operator_id", None),
                             user_id=current_user.id)
        db.session.add(p); db.session.commit()

    if request.method == "POST":
        p.headline = (request.form.get("headline") or "").strip() or None
        p.bio = request.form.get("bio")
        p.skills = request.form.get("skills")
        p.linkedin_url = request.form.get("linkedin_url")
        p.is_public = bool(request.form.get("is_public"))
        db.session.commit()
        flash("Profile saved.", "success")
        return redirect(url_for("community.edit_profile"))
    return render_template("community/edit_profile.html", profile=p)


# ================== Announcements ==================

@community_bp.route("/announcements")
@login_required
def announcements():
    posts = (Announcement.query
                          .order_by(Announcement.is_pinned.desc(),
                                    Announcement.published_at.desc())
                          .limit(50).all())
    from ...services.notifications import announcement_visible
    return render_template("community/announcements.html", posts=[post for post in posts if announcement_visible(current_user, post)])


@community_bp.route("/announcements/<int:post_id>")
@login_required
def announcement_detail(post_id):
    from ...services.notifications import announcement_visible
    post = Announcement.query.get_or_404(post_id)
    if not announcement_visible(current_user, post):
        abort(404)
    return render_template("community/announcements.html", posts=[post])


@community_bp.route("/announcements/new", methods=["GET", "POST"])
@admin_required
def announcement_new():
    if request.method == "POST":
        a = Announcement(
            operator_id=getattr(g, "operator_id", None),
            author_id=current_user.id,
            location_id=int(request.form["location_id"])
                if request.form.get("location_id") else None,
            title=(request.form.get("title") or "").strip(),
            body=(request.form.get("body") or "").strip(),
            is_pinned=bool(request.form.get("is_pinned")),
        )
        if not (a.title and a.body):
            flash("Title and body are required.", "warning")
            return redirect(url_for("community.announcement_new"))
        if a.location_id and not Location.query.filter_by(id=a.location_id, operator_id=g.operator_id).first():
            abort(404)
        db.session.add(a)
        db.session.flush()
        from ...services.notifications import announcement_added
        announcement_added(a)
        db.session.commit()
        audit_service.record("announcement.created", "announcement", a.id,
                             {"title": a.title})
        flash("Announcement posted.", "success")
        return redirect(url_for("community.announcements"))
    locations = Location.query.filter_by(is_active=True).all()
    return render_template("community/announcement_form.html",
                           locations=locations)


# ================== Printing credits ==================

@community_bp.route("/printing")
@login_required
def printing():
    entries = (PrintingLedger.query.filter_by(user_id=current_user.id)
                                    .order_by(PrintingLedger.created_at.desc())
                                    .limit(100).all())
    balance = sum(e.delta for e in entries) if entries else 0
    return render_template("community/printing.html",
                           entries=entries, balance=balance)


@community_bp.route("/printing/adjust", methods=["POST"])
@admin_required
def printing_adjust():
    try:
        uid = int(request.form["user_id"])
        delta = int(request.form["delta"])
    except (KeyError, ValueError):
        flash("Invalid entry.", "warning")
        return redirect(url_for("community.printing"))
    db.session.add(PrintingLedger(
        operator_id=getattr(g, "operator_id", None),
        user_id=uid, delta=delta,
        note=(request.form.get("note") or "").strip() or None,
    ))
    db.session.commit()
    flash("Printing ledger updated.", "success")
    return redirect(url_for("community.printing"))


# ================== Support tickets ==================

def _notify_support(ticket) -> None:
    """Route a new ticket's notification to the operator's own support
    email if they've set one, otherwise the platform's fallback address."""
    from flask import current_app
    operator = getattr(g, "operator", None)
    recipient = (operator.support_email if operator and operator.support_email
                else current_app.config["PLATFORM_SUPPORT_EMAIL"])
    try:
        mail_service.send(
            subject=f"New support ticket: {ticket.subject}",
            recipient=recipient,
            template="support_ticket_notify",
            ticket=ticket, submitter=current_user,
        )
    except Exception as e:  # noqa: BLE001
        current_app.logger.warning("support ticket notify failed: %s", e)

@community_bp.route("/tickets", methods=["GET", "POST"])
@login_required
def tickets():
    if request.method == "POST":
        t = SupportTicket(
            operator_id=getattr(g, "operator_id", None),
            submitter_id=current_user.id,
            location_id=int(request.form["location_id"])
                if request.form.get("location_id") else None,
            subject=(request.form.get("subject") or "").strip(),
            body=(request.form.get("body") or "").strip(),
            priority=TicketPriority(request.form.get("priority", "normal")),
            status=TicketStatus.OPEN,
        )
        if not (t.subject and t.body):
            flash("Subject and description are required.", "warning")
            return redirect(url_for("community.tickets"))
        if t.location_id and not Location.query.filter_by(id=t.location_id, operator_id=g.operator_id).first():
            abort(404)
        db.session.add(t)
        db.session.flush()
        from ...services.notifications import ticket_changed
        ticket_changed(t, new=True)
        db.session.commit()
        _notify_support(t)
        flash("Ticket submitted.", "success")
        return redirect(url_for("community.tickets"))

    if current_user.is_admin:
        rows = SupportTicket.query.order_by(SupportTicket.created_at.desc()).limit(200).all()
    else:
        rows = SupportTicket.query.filter_by(submitter_id=current_user.id) \
                                    .order_by(SupportTicket.created_at.desc()).all()
    locations = Location.query.filter_by(is_active=True).all()
    return render_template("community/tickets.html",
                           tickets=rows, locations=locations,
                           priorities=list(TicketPriority))


@community_bp.route("/tickets/<int:tid>/resolve", methods=["POST"])
@admin_required
def ticket_resolve(tid: int):
    t = SupportTicket.query.get_or_404(tid)
    t.status = TicketStatus.RESOLVED
    t.resolved_at = datetime.utcnow()
    db.session.flush()
    from ...services.notifications import ticket_changed
    ticket_changed(t)
    db.session.commit()
    audit_service.record("ticket.resolved", "ticket", t.id, {})
    flash("Ticket resolved.", "success")
    return redirect(url_for("community.tickets"))


# ================== Lockers ==================

@community_bp.route("/lockers", methods=["GET", "POST"])
@admin_required
def lockers():
    if request.method == "POST":
        try:
            loc_id = int(request.form["location_id"])
        except (KeyError, ValueError):
            abort(400)
        db.session.add(Locker(
            operator_id=getattr(g, "operator_id", None),
            location_id=loc_id,
            code=(request.form.get("code") or "").strip(),
            monthly_rate=request.form.get("monthly_rate") or 0,
            status=LockerStatus.AVAILABLE,
        ))
        db.session.commit()
        flash("Locker added.", "success")
        return redirect(url_for("community.lockers"))
    all_lockers = Locker.query.order_by(Locker.location_id, Locker.code).all()
    locations = Location.query.filter_by(is_active=True).all()
    return render_template("community/lockers.html",
                           lockers=all_lockers, locations=locations)


@community_bp.route("/lockers/<int:lid>/assign", methods=["POST"])
@admin_required
def locker_assign(lid: int):
    l = Locker.query.get_or_404(lid)
    try:
        uid = int(request.form["user_id"])
    except (KeyError, ValueError):
        abort(400)
    l.assigned_user_id = uid
    l.assigned_at = date.today()
    l.status = LockerStatus.ASSIGNED
    db.session.commit()
    flash("Locker assigned.", "success")
    return redirect(url_for("community.lockers"))


@community_bp.route("/lockers/<int:lid>/release", methods=["POST"])
@admin_required
def locker_release(lid: int):
    l = Locker.query.get_or_404(lid)
    l.assigned_user_id = None
    l.assigned_at = None
    l.status = LockerStatus.AVAILABLE
    db.session.commit()
    flash("Locker released.", "info")
    return redirect(url_for("community.lockers"))


# ================== Referrals ==================

@community_bp.route("/referrals", methods=["GET", "POST"])
@login_required
def referrals():
    if request.method == "POST":
        email = (request.form.get("referred_email") or "").strip().lower()
        if not email:
            flash("Email is required.", "warning")
            return redirect(url_for("community.referrals"))
        r = Referral(
            operator_id=getattr(g, "operator_id", None),
            referrer_id=current_user.id,
            referred_email=email,
            code=Referral.new_code(),
            reward_credits=int(request.form.get("reward_credits") or 5),
            status=ReferralStatus.PENDING,
        )
        db.session.add(r); db.session.commit()
        flash(f"Referral link created. Code: {r.code}", "success")
        return redirect(url_for("community.referrals"))
    mine = (Referral.query.filter_by(referrer_id=current_user.id)
                           .order_by(Referral.created_at.desc()).all())
    return render_template("community/referrals.html", referrals=mine)
