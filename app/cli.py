"""Flask CLI commands: create users, provision tenants, seed demo data."""
from __future__ import annotations

import click
from flask import Flask
from flask.cli import with_appcontext

from .extensions import db
from .models import User, UserRole, Tenant, TenantStatus


def register_cli(app: Flask) -> None:
    app.cli.add_command(create_admin_cmd)
    app.cli.add_command(seed_demo_cmd)
    app.cli.add_command(create_tenant_cmd)
    app.cli.add_command(run_scheduled_jobs_cmd)
    app.cli.add_command(update_platform_owner_email_cmd)


@click.command("run-scheduled-jobs")
@click.option("--month", default=None, help="Billing month as YYYY-MM; defaults to the current month.")
@with_appcontext
def run_scheduled_jobs_cmd(month: str | None) -> None:
    """Materialize recurring bookings and generate idempotent invoices."""
    from datetime import datetime
    from .services.billing_service import run_monthly_billing
    from .services.booking_service import materialize_recurring_room_bookings

    target_month = datetime.strptime(f"{month}-01", "%Y-%m-%d").date() if month else None
    bookings = materialize_recurring_room_bookings()
    invoices = run_monthly_billing(target_month)
    click.echo(f"Created {bookings} recurring booking(s); generated {len(invoices)} invoice(s).")


@click.command("create-admin")
@click.option("--email", required=True)
@click.option("--password", required=True)
@click.option("--name", default="Platform Admin")
@click.option("--platform-owner/--tenant-super-admin", default=True)
@with_appcontext
def create_admin_cmd(email: str, password: str, name: str, platform_owner: bool) -> None:
    if User.query.filter_by(email=email).first():
        click.echo(f"User {email} already exists.")
        return
    role = UserRole.PLATFORM_OWNER if platform_owner else UserRole.SUPER_ADMIN
    u = User(email=email, full_name=name, role=role,
             is_active=True, email_verified=True)
    u.set_password(password)
    db.session.add(u)
    db.session.commit()
    click.echo(f"Created {role.value}: {email}")


@click.command("create-tenant")
@click.option("--slug", required=True)
@click.option("--name", required=True)
@click.option("--primary-domain", required=True)
@click.option("--admin-email", required=True)
@click.option("--admin-password", required=True)
@click.option("--admin-name", default="Tenant Admin")
@with_appcontext
def create_tenant_cmd(slug, name, primary_domain, admin_email, admin_password, admin_name):
    if Tenant.query.filter_by(slug=slug).first():
        click.echo(f"Tenant slug {slug} already exists.")
        return
    t = Tenant(slug=slug, name=name, primary_domain=primary_domain,
               status=TenantStatus.ACTIVE)
    db.session.add(t)
    db.session.flush()
    u = User(tenant_id=t.id, email=admin_email, full_name=admin_name,
             role=UserRole.SUPER_ADMIN, is_active=True, email_verified=True)
    u.set_password(admin_password)
    db.session.add(u)
    db.session.commit()
    click.echo(f"Provisioned tenant '{name}' ({slug}). Admin: {admin_email}")


@click.command("update-platform-owner-email")
@click.option("--new-email", required=True, help="Email address to move the Platform Owner account to.")
@click.option("--old-email", default=None,
              help="Existing Platform Owner email to rename. Defaults to PLATFORM_OWNER_EMAIL config.")
@with_appcontext
def update_platform_owner_email_cmd(new_email: str, old_email: str | None) -> None:
    """Rename an existing Platform Owner's login email in place."""
    from flask import current_app

    old_email = old_email or current_app.config["PLATFORM_OWNER_EMAIL"]
    user = (User.query.execution_options(skip_tenant_filter=True)
            .filter_by(email=old_email, role=UserRole.PLATFORM_OWNER).first())
    if not user:
        click.echo(f"No Platform Owner found with email {old_email}.")
        return
    if User.query.execution_options(skip_tenant_filter=True).filter_by(email=new_email).first():
        click.echo(f"A user with email {new_email} already exists.")
        return
    user.email = new_email
    db.session.commit()
    click.echo(f"Platform Owner email updated: {old_email} -> {new_email}")
    click.echo("Remember to set PLATFORM_OWNER_EMAIL in .env to the new address.")


@click.command("seed-demo")
@with_appcontext
def seed_demo_cmd() -> None:
    """Create only the platform owner for a fresh installation."""
    from flask import current_app

    po_email = current_app.config["PLATFORM_OWNER_EMAIL"]
    if not User.query.execution_options(skip_tenant_filter=True).filter_by(email=po_email).first():
        po = User(email=po_email, full_name="Platform Owner",
                  role=UserRole.PLATFORM_OWNER, is_active=True, email_verified=True)
        po.set_password(current_app.config["PLATFORM_OWNER_PASSWORD"])
        db.session.add(po)
        click.echo(f"Seeded platform super admin: {po_email}")
    db.session.commit()

    click.echo("Hub1z platform bootstrap complete. No operator or sample customer data was created.")
    click.echo(f"Platform Owner: {po_email}")
