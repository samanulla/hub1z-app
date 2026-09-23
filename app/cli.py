"""Flask CLI commands: create users, provision tenants, seed demo data."""
from __future__ import annotations

from datetime import date, time
from decimal import Decimal

import click
from flask import Flask
from flask.cli import with_appcontext

from .extensions import db
from .models import (
    User, UserRole, Company, CompanyStatus,
    Location, Floor, Seat, SeatType, ConferenceRoom,
    PricingPlan, PlanType, BillingCycle, Subscription, SubscriptionStatus,
    Amenity, RoomAmenity,
    Tenant, TenantStatus,
)


def register_cli(app: Flask) -> None:
    app.cli.add_command(create_admin_cmd)
    app.cli.add_command(seed_demo_cmd)
    app.cli.add_command(create_tenant_cmd)


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


@click.command("seed-demo")
@with_appcontext
def seed_demo_cmd() -> None:
    """Populate DB with default tenant + sample data."""
    from flask import current_app

    # Sample tenant — a coworking business ("Adyar Space") that lives on the
    # platform, not the platform itself. Its people get their own company
    # domain (adyarspace.com); hub1z.com is reserved for the platform.
    tenant = Tenant.query.filter_by(slug="adyarspace").first()
    if tenant is None:
        tenant = Tenant(
            slug="adyarspace", name="Adyar Space",
            tagline="A workspace that scales with your team.",
            primary_domain="adyarspace.hub1z.com", status=TenantStatus.ACTIVE,
            brand_color="#0f766e", support_email="hello@adyarspace.com",
            plan_tier="growth",  # comfortably covers the seeded inventory below
        )
        db.session.add(tenant)
        db.session.commit()
        click.echo(f"Seeded sample tenant: {tenant.slug}")
    tid = tenant.id

    po_email = "platform@hub1z.com"
    if not User.query.filter_by(email=po_email).first():
        po = User(email=po_email, full_name="Platform Super Admin",
                  role=UserRole.PLATFORM_OWNER, is_active=True, email_verified=True)
        po.set_password("ChangeMe123!")
        db.session.add(po)
        click.echo(f"Seeded platform super admin: {po_email}")

    email = current_app.config["BOOTSTRAP_ADMIN_EMAIL"]
    if not User.query.filter_by(email=email).first():
        admin = User(tenant_id=tid, email=email, full_name="Tenant Admin",
                     role=UserRole.SUPER_ADMIN, is_active=True, email_verified=True)
        admin.set_password(current_app.config["BOOTSTRAP_ADMIN_PASSWORD"])
        db.session.add(admin)
        click.echo(f"Seeded tenant super admin: {email}")

    for n in ["Wi-Fi", "Coffee", "Printing", "Phone booths", "Kitchen", "Shower", "Bike storage"]:
        if not Amenity.query.filter_by(name=n).first():
            db.session.add(Amenity(name=n))
    for n in ["TV Screen", "Whiteboard", "Video Conference", "Speakerphone"]:
        if not RoomAmenity.query.filter_by(name=n).first():
            db.session.add(RoomAmenity(name=n))
    db.session.flush()

    loc = Location.query.filter_by(code="BLR-01").first()
    if not loc:
        loc = Location(
            tenant_id=tid, name="Adyar Space Bengaluru — Indiranagar", code="BLR-01",
            address_line1="100 Feet Road", city="Bengaluru", state="KA",
            country="IN", postal_code="560038", timezone="Asia/Kolkata",
            open_time=time(7, 0), close_time=time(22, 0),
        )
        db.session.add(loc); db.session.flush()
        ground = Floor(location_id=loc.id, level=1, name="Ground — Lounge")
        l5 = Floor(location_id=loc.id, level=5, name="Level 5 — Hot Desks")
        l6 = Floor(location_id=loc.id, level=6, name="Level 6 — Dedicated Desks")
        l7 = Floor(location_id=loc.id, level=7, name="Level 7 — Private Offices")
        db.session.add_all([ground, l5, l6, l7]); db.session.flush()
        for i in range(1, 21):
            db.session.add(Seat(location_id=loc.id, floor_id=l5.id,
                                code=f"L5-HD-{i:03d}", seat_type=SeatType.HOT_DESK,
                                hourly_rate=Decimal("150"), daily_rate=Decimal("900"),
                                monthly_rate=Decimal("12000")))
        for i in range(1, 11):
            db.session.add(Seat(location_id=loc.id, floor_id=l6.id,
                                code=f"L6-DD-{i:03d}", seat_type=SeatType.DEDICATED_DESK,
                                monthly_rate=Decimal("22000")))
        for i in range(1, 6):
            db.session.add(Seat(location_id=loc.id, floor_id=l7.id,
                                code=f"L7-PO-{i:03d}", seat_type=SeatType.PRIVATE_OFFICE,
                                capacity=4, monthly_rate=Decimal("85000")))
        db.session.add_all([
            ConferenceRoom(location_id=loc.id, floor_id=ground.id, code="G-BOARD",
                           name="The Boardroom", capacity=12,
                           hourly_rate=Decimal("2400"), credit_cost_per_hour=2),
            ConferenceRoom(location_id=loc.id, floor_id=l5.id, code="L5-CAUV",
                           name="Cauvery", capacity=6,
                           hourly_rate=Decimal("1200"), credit_cost_per_hour=1),
            ConferenceRoom(location_id=loc.id, floor_id=l5.id, code="L5-KRSH",
                           name="Krishna", capacity=4,
                           hourly_rate=Decimal("800"), credit_cost_per_hour=1),
            ConferenceRoom(location_id=loc.id, floor_id=l7.id, code="L7-EXEC",
                           name="Executive Suite", capacity=8,
                           hourly_rate=Decimal("1800"), credit_cost_per_hour=2),
        ])
        click.echo(f"Seeded location {loc.code}")

    plans_seed = [
        ("Hot Desk Monthly", PlanType.HOT_DESK, BillingCycle.MONTHLY, Decimal("12000"), 8, 1),
        ("Dedicated Desk", PlanType.DEDICATED_DESK, BillingCycle.MONTHLY, Decimal("22000"), 20, 1),
        ("Private Office (4-person)", PlanType.PRIVATE_OFFICE, BillingCycle.MONTHLY, Decimal("85000"), 40, 1),
        ("All Access", PlanType.ALL_ACCESS, BillingCycle.MONTHLY, Decimal("18000"), 12, 0),
        ("Day Pass", PlanType.DAY_PASS, BillingCycle.DAILY, Decimal("900"), 0, 1),
    ]
    for name, ptype, cycle, price, credits, max_loc in plans_seed:
        if not PricingPlan.query.filter_by(name=name).first():
            db.session.add(PricingPlan(
                tenant_id=tid, name=name, plan_type=ptype, billing_cycle=cycle,
                base_price=price, included_meeting_credits=credits, max_locations=max_loc,
            ))

    if not Company.query.filter_by(name="Acme Robotics").first():
        acme = Company(tenant_id=tid, name="Acme Robotics",
                       legal_name="Acme Robotics Inc.",
                       billing_email="billing@acme.example",
                       industry="Hardware", status=CompanyStatus.ACTIVE, max_employees=25)
        db.session.add(acme); db.session.flush()
        ca = User(tenant_id=tid, email="jane@acme.example", full_name="Jane Doe",
                  role=UserRole.COMPANY_ADMIN, company_id=acme.id, is_active=True)
        ca.set_password("ChangeMe123!")
        db.session.add(ca)
        plan = PricingPlan.query.filter_by(name="Dedicated Desk").first()
        if plan:
            db.session.add(Subscription(
                tenant_id=tid, plan_id=plan.id, company_id=acme.id, quantity=5,
                unit_price=plan.base_price, start_date=date.today(),
                status=SubscriptionStatus.ACTIVE,
                meeting_credits_balance=plan.included_meeting_credits * 5,
            ))
        click.echo("Seeded demo company Acme Robotics")

    db.session.commit()

    click.echo("")
    click.echo("=" * 60)
    click.echo("hub1z demo environment ready. Sign in at /auth/login:")
    click.echo(f"  Platform Super Admin:  {po_email} / ChangeMe123!")
    click.echo(f"  Tenant Super Admin:    {email} / ChangeMe123!  ({tenant.name})")
    click.echo(f"  Company Admin:         jane@acme.example / ChangeMe123!  (Acme Robotics)")
    click.echo("=" * 60)
