"""Flask CLI commands: create users, provision operators, seed demo data."""
from __future__ import annotations

import click
from flask import Flask
from flask.cli import with_appcontext

from .config import ProductionConfig, get_config
from .extensions import db
from .services import credit_service
from .models import (
    User, UserRole, Operator, OperatorStatus, Company, CompanyStatus,
    Location, Floor, Seat, SeatType, ConferenceRoom, CreditAllocation, RoomCategory, SeatBand,
)


def register_cli(app: Flask) -> None:
    app.cli.add_command(create_admin_cmd)
    app.cli.add_command(seed_demo_cmd)
    app.cli.add_command(seed_personas_cmd)
    app.cli.add_command(create_operator_cmd)
    app.cli.add_command(run_scheduled_jobs_cmd)
    app.cli.add_command(credits_cycle_cmd)
    app.cli.add_command(release_no_shows_cmd)
    app.cli.add_command(update_platform_owner_email_cmd)


@click.command("credits-cycle")
@click.option("--date", "on", default=None, help="Run as of YYYY-MM-DD; defaults to today.")
@with_appcontext
def credits_cycle_cmd(on: str | None) -> None:
    """Expire old credits, start pending allocation changes and grant this month's credits (safe to re-run)."""
    from datetime import datetime
    today = datetime.strptime(on, "%Y-%m-%d").date() if on else None
    r = credit_service.run_all_cycles(today)
    click.echo(f"Credit cycle: {r['granted']} monthly grant(s), {r['changed']} allocation change(s), "
               f"{r['expired']} lot(s) expired.")


@click.command("release-no-shows")
@with_appcontext
def release_no_shows_cmd() -> None:
    """Free rooms nobody checked in to and close finished meetings. Run every few minutes."""
    from .services.booking_service import release_no_shows
    r = release_no_shows()
    click.echo(f"Released {r['released']} no-show room booking(s); completed {r['completed']}.")


@click.command("run-scheduled-jobs")
@click.option("--month", default=None, help="Billing month as YYYY-MM; defaults to the current month.")
@with_appcontext
def run_scheduled_jobs_cmd(month: str | None) -> None:
    """Materialize recurring bookings and generate idempotent invoices."""
    from datetime import datetime
    from .services.billing_service import run_agreement_jobs, run_monthly_billing
    from .services.booking_service import materialize_recurring_room_bookings, release_no_shows

    target_month = datetime.strptime(f"{month}-01", "%Y-%m-%d").date() if month else None
    bookings = materialize_recurring_room_bookings()
    agreements = run_agreement_jobs()
    invoices = run_monthly_billing(target_month)
    credits = credit_service.run_all_cycles()
    no_shows = release_no_shows()
    click.echo(f"Created {bookings} recurring booking(s); generated {len(invoices)} invoice(s); "
               f"agreements: {agreements['ended']} ended, {agreements['proposed']} rate revision(s) proposed; "
               f"credits: {credits['granted']} granted, {credits['expired']} expired; "
               f"{no_shows['released']} no-show(s) released.")


@click.command("create-admin")
@click.option("--email", required=True)
@click.option("--password", required=True)
@click.option("--name", default="Platform Admin")
@click.option("--platform-owner/--operator-super-admin", default=True)
@click.option("--operator-slug", default=None, help="Operator the super admin belongs to (required with --operator-super-admin).")
@with_appcontext
def create_admin_cmd(email: str, password: str, name: str, platform_owner: bool, operator_slug: str | None) -> None:
    if User.query.filter_by(email=email).first():
        click.echo(f"User {email} already exists.")
        return
    op = None
    if not platform_owner:
        op = Operator.query.filter_by(slug=operator_slug).first() if operator_slug else None
        if op is None:
            click.echo("--operator-slug of an existing operator is required with --operator-super-admin.")
            return
    role = UserRole.PLATFORM_OWNER if platform_owner else UserRole.SUPER_ADMIN
    u = User(operator_id=op.id if op else None, email=email, full_name=name, role=role,
             is_active=True, email_verified=True)
    u.set_password(password)
    db.session.add(u)
    db.session.commit()
    click.echo(f"Created {role.value}: {email}")


@click.command("create-operator")
@click.option("--slug", required=True)
@click.option("--name", required=True)
@click.option("--primary-domain", required=True)
@click.option("--admin-email", required=True)
@click.option("--admin-password", required=True)
@click.option("--admin-name", default="Operator Admin")
@with_appcontext
def create_operator_cmd(slug, name, primary_domain, admin_email, admin_password, admin_name):
    if Operator.query.filter_by(slug=slug).first():
        click.echo(f"Operator slug {slug} already exists.")
        return
    t = Operator(slug=slug, name=name, primary_domain=primary_domain,
               status=OperatorStatus.ACTIVE)
    db.session.add(t)
    db.session.flush()
    u = User(operator_id=t.id, email=admin_email, full_name=admin_name,
             role=UserRole.SUPER_ADMIN, is_active=True, email_verified=True)
    u.set_password(admin_password)
    db.session.add(u)
    db.session.commit()
    click.echo(f"Provisioned operator '{name}' ({slug}). Admin: {admin_email}")


@click.command("update-platform-owner-email")
@click.option("--new-email", required=True, help="Email address to move the Platform Owner account to.")
@click.option("--old-email", default=None,
              help="Existing Platform Owner email to rename. Defaults to PLATFORM_OWNER_EMAIL config.")
@with_appcontext
def update_platform_owner_email_cmd(new_email: str, old_email: str | None) -> None:
    """Rename an existing Platform Owner's login email in place."""
    from flask import current_app

    old_email = old_email or current_app.config["PLATFORM_OWNER_EMAIL"]
    user = (User.query.execution_options(skip_operator_filter=True)
            .filter_by(email=old_email, role=UserRole.PLATFORM_OWNER).first())
    if not user:
        click.echo(f"No Platform Owner found with email {old_email}.")
        return
    if User.query.execution_options(skip_operator_filter=True).filter_by(email=new_email).first():
        click.echo(f"A user with email {new_email} already exists.")
        return
    user.email = new_email
    db.session.commit()
    click.echo(f"Platform Owner email updated: {old_email} -> {new_email}")
    click.echo("Remember to set PLATFORM_OWNER_EMAIL in .env to the new address.")


PERSONA_PASSWORD = "DemoPass123!"


@click.command("seed-personas")
@with_appcontext
def seed_personas_cmd() -> None:
    """Development/testing only: one login per role, plus a second operator to check isolation."""
    from decimal import Decimal
    from urllib.parse import urlparse
    from flask import current_app

    # The flask CLI overrides app.debug, so decide from the configured environment instead.
    if issubclass(get_config(), ProductionConfig):
        raise click.ClickException("seed-personas creates known passwords; it only runs in development/testing.")

    base = current_app.config["PLATFORM_BASE_DOMAIN"]
    port = urlparse(current_app.config["APP_BASE_URL"]).port
    suffix = f":{port}" if port else ""

    def ensure_user(email, name, role, operator=None, company=None, password=PERSONA_PASSWORD):
        if User.query.filter_by(email=email).first():
            return
        u = User(operator_id=operator.id if operator else None, email=email, full_name=name, role=role,
                 company_id=company.id if company else None, is_active=True, email_verified=True)
        u.set_password(password)
        db.session.add(u)

    def ensure_operator(slug, name):
        op = Operator.query.filter_by(slug=slug).first()
        if op:
            return op
        op = Operator(slug=slug, name=name, primary_domain=f"{slug}.{base}", status=OperatorStatus.ACTIVE)
        db.session.add(op)
        db.session.flush()
        loc = Location(operator_id=op.id, name=f"{name} HQ", code="HQ", address_line1="1 Demo Street",
                       city="Bengaluru", country="IN", timezone="Asia/Kolkata")
        db.session.add(loc)
        db.session.flush()
        floor = Floor(operator_id=op.id, location_id=loc.id, level=1, name="Ground")
        db.session.add(floor)
        db.session.flush()
        db.session.flush()
        credit_service.seed_default_categories(op.id)
        standard = RoomCategory.query.filter_by(operator_id=op.id, name="Standard").first()
        db.session.add_all([
            Seat(operator_id=op.id, location_id=loc.id, floor_id=floor.id, code="D1",
                 seat_type=SeatType.HOT_DESK, hourly_rate=Decimal("100")),
            ConferenceRoom(operator_id=op.id, location_id=loc.id, floor_id=floor.id, code="R1",
                           name="Board Room", capacity=8, hourly_rate=Decimal("500"),
                           category_id=standard.id),
        ])
        return op

    po_email, po_password = current_app.config["PLATFORM_OWNER_EMAIL"], current_app.config["PLATFORM_OWNER_PASSWORD"]
    ensure_user(po_email, "Platform Owner", UserRole.PLATFORM_OWNER, password=po_password)

    demo = ensure_operator("demo", "Demo Space")
    acme = Company.query.filter_by(operator_id=demo.id, name="Acme Co").first()
    if acme is None:
        acme = Company(operator_id=demo.id, name="Acme Co", billing_email="billing@acmeco.com",
                       status=CompanyStatus.ACTIVE)
        db.session.add(acme)
        db.session.flush()
    ensure_user("owner@demospace.com", "Demo Owner", UserRole.SUPER_ADMIN, demo)
    ensure_user("admin@acmeco.com", "Acme Admin", UserRole.COMPANY_ADMIN, demo, acme)
    ensure_user("employee@acmeco.com", "Acme Employee", UserRole.EMPLOYEE, demo, acme)
    ensure_user("individual@demospace.com", "Ivy Individual", UserRole.INDIVIDUAL, demo)
    db.session.flush()
    if not SeatBand.query.filter_by(operator_id=demo.id).first():
        db.session.add_all([SeatBand(operator_id=demo.id, min_seats=1, max_seats=10, monthly_credits=20),
                            SeatBand(operator_id=demo.id, min_seats=11, max_seats=25, monthly_credits=30)])
    if not CreditAllocation.query.filter_by(operator_id=demo.id, company_id=acme.id).first():
        credit_service.allocate(demo.id, company_id=acme.id, monthly=20)
    ivy = User.query.filter_by(email="individual@demospace.com").first()
    if not CreditAllocation.query.filter_by(operator_id=demo.id, user_id=ivy.id).first():
        credit_service.allocate(demo.id, user_id=ivy.id, monthly=4)

    other = ensure_operator("other", "Other Space")
    if not Company.query.filter_by(operator_id=other.id, name="Other Co").first():
        db.session.add(Company(operator_id=other.id, name="Other Co", billing_email="billing@otherspace.com",
                               status=CompanyStatus.ACTIVE))
    ensure_user("owner@otherspace.com", "Other Owner", UserRole.SUPER_ADMIN, other)
    db.session.commit()

    rows = [
        ("Platform owner", f"{base}", po_email, po_password),
        ("Operator owner", f"demo.{base}", "owner@demospace.com", PERSONA_PASSWORD),
        ("Company admin", f"demo.{base}", "admin@acmeco.com", PERSONA_PASSWORD),
        ("Employee (by company)", f"demo.{base}", "employee@acmeco.com", PERSONA_PASSWORD),
        ("Individual", f"demo.{base}", "individual@demospace.com", PERSONA_PASSWORD),
        ("Other operator owner", f"other.{base}", "owner@otherspace.com", PERSONA_PASSWORD),
    ]
    for role, host, email, password in rows:
        click.echo(f"{role:<22} http://{host}{suffix}/auth/login  {email} / {password}")


@click.command("seed-demo")
@with_appcontext
def seed_demo_cmd() -> None:
    """Create only the platform owner for a fresh installation."""
    from flask import current_app

    po_email = current_app.config["PLATFORM_OWNER_EMAIL"]
    if not User.query.execution_options(skip_operator_filter=True).filter_by(email=po_email).first():
        po = User(email=po_email, full_name="Platform Owner",
                  role=UserRole.PLATFORM_OWNER, is_active=True, email_verified=True)
        po.set_password(current_app.config["PLATFORM_OWNER_PASSWORD"])
        db.session.add(po)
        click.echo(f"Seeded platform super admin: {po_email}")
    db.session.commit()

    click.echo("Hub1z platform bootstrap complete. No operator or sample customer data was created.")
    click.echo(f"Platform Owner: {po_email}")
