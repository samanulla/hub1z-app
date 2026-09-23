"""Platform team: Platform Super Admin manages Platform Manager accounts.

Creating/editing a Platform Manager's login and permissions is always
Owner-only — never delegable via a permission grant — so a Manager can never
escalate their own (or a peer's) access.
"""
from __future__ import annotations

from flask import render_template, redirect, url_for, flash

from ...extensions import db
from ...models import User, UserRole, PLATFORM_FEATURES
from ...services import audit_service
from ...utils.decorators import platform_owner_required
from .forms import PlatformManagerForm


def _apply_permissions(form: PlatformManagerForm, user: User) -> None:
    keys = [key for key, _, _ in PLATFORM_FEATURES if getattr(form, f"perm_{key}").data]
    user.set_platform_permissions(keys)


def register_team_routes(bp):

    @bp.route("/team")
    @platform_owner_required
    def team_list():
        staff = (User.query.execution_options(skip_tenant_filter=True)
                 .filter(User.role.in_([UserRole.PLATFORM_OWNER, UserRole.PLATFORM_MANAGER]))
                 .order_by(User.role.desc(), User.full_name).all())
        return render_template("platform/team_list.html", staff=staff,
                               features=PLATFORM_FEATURES)

    @bp.route("/team/new", methods=["GET", "POST"])
    @platform_owner_required
    def manager_new():
        form = PlatformManagerForm()
        if form.validate_on_submit():
            email = form.email.data.lower().strip()
            if User.query.execution_options(skip_tenant_filter=True) \
                         .filter_by(email=email).first():
                flash("A user with that email already exists.", "warning")
                return render_template("platform/manager_form.html", form=form,
                                       title="New Platform Manager", features=PLATFORM_FEATURES)
            if not form.password.data:
                flash("A password is required for a new Platform Manager.", "warning")
                return render_template("platform/manager_form.html", form=form,
                                       title="New Platform Manager", features=PLATFORM_FEATURES)

            u = User(
                email=email,
                full_name=form.full_name.data.strip(),
                role=UserRole.PLATFORM_MANAGER,
                is_active=form.is_active.data,
                email_verified=True,
            )
            u.set_password(form.password.data)
            _apply_permissions(form, u)
            db.session.add(u)
            db.session.commit()
            audit_service.record("platform_manager.created", "user", u.id,
                                 {"email": u.email, "permissions": u.get_platform_permissions()})
            flash(f"Platform Manager {u.email} created.", "success")
            return redirect(url_for("platform.team_list"))
        return render_template("platform/manager_form.html", form=form,
                               title="New Platform Manager", features=PLATFORM_FEATURES)

    @bp.route("/team/<int:user_id>/edit", methods=["GET", "POST"])
    @platform_owner_required
    def manager_edit(user_id: int):
        u = (User.query.execution_options(skip_tenant_filter=True)
             .filter_by(id=user_id, role=UserRole.PLATFORM_MANAGER).first_or_404())
        form = PlatformManagerForm(obj=u)
        if not form.is_submitted():
            # Checkbox fields have no matching User attribute for obj= to
            # prefill from — set them from the stored permission list instead.
            for key, _, _ in PLATFORM_FEATURES:
                getattr(form, f"perm_{key}").data = key in u.get_platform_permissions()

        if form.validate_on_submit():
            email = form.email.data.lower().strip()
            existing = (User.query.execution_options(skip_tenant_filter=True)
                        .filter(User.email == email, User.id != u.id).first())
            if existing:
                flash("A user with that email already exists.", "warning")
                return render_template("platform/manager_form.html", form=form,
                                       title=f"Edit {u.full_name}", manager=u, features=PLATFORM_FEATURES)

            u.email = email
            u.full_name = form.full_name.data.strip()
            u.is_active = form.is_active.data
            if form.password.data:
                u.set_password(form.password.data)
            _apply_permissions(form, u)
            db.session.commit()
            audit_service.record("platform_manager.updated", "user", u.id,
                                 {"email": u.email, "permissions": u.get_platform_permissions()})
            flash(f"{u.full_name} updated.", "success")
            return redirect(url_for("platform.team_list"))
        return render_template("platform/manager_form.html", form=form,
                               title=f"Edit {u.full_name}", manager=u, features=PLATFORM_FEATURES)

    @bp.route("/team/<int:user_id>/deactivate", methods=["POST"])
    @platform_owner_required
    def manager_deactivate(user_id: int):
        u = (User.query.execution_options(skip_tenant_filter=True)
             .filter_by(id=user_id, role=UserRole.PLATFORM_MANAGER).first_or_404())
        u.is_active = False
        db.session.commit()
        audit_service.record("platform_manager.deactivated", "user", u.id, {"email": u.email})
        flash(f"{u.full_name} deactivated.", "info")
        return redirect(url_for("platform.team_list"))

    @bp.route("/team/<int:user_id>/activate", methods=["POST"])
    @platform_owner_required
    def manager_activate(user_id: int):
        u = (User.query.execution_options(skip_tenant_filter=True)
             .filter_by(id=user_id, role=UserRole.PLATFORM_MANAGER).first_or_404())
        u.is_active = True
        db.session.commit()
        audit_service.record("platform_manager.activated", "user", u.id, {"email": u.email})
        flash(f"{u.full_name} activated.", "success")
        return redirect(url_for("platform.team_list"))
