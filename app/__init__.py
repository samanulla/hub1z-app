"""Application factory."""
from __future__ import annotations

import os
from flask import Flask, render_template, redirect, url_for, abort, g, request
from flask_login import current_user
from dotenv import load_dotenv

from .config import get_config
from .extensions import db, migrate, login_manager, csrf, mail, limiter
from .services.storage import storage_service
from .services.formatting import register_formatting
from .services import tenant_resolver

load_dotenv()


def create_app(config_override: dict | None = None) -> Flask:
    app = Flask(__name__, instance_relative_config=False)
    app.config.from_object(get_config())
    if config_override:
        app.config.update(config_override)

    _init_extensions(app)
    _register_blueprints(app)
    _register_cli(app)
    _register_error_handlers(app)
    _register_context(app)
    _register_root_routes(app)
    register_formatting(app)
    tenant_resolver.install(app)

    return app


def _init_extensions(app: Flask) -> None:
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)
    mail.init_app(app)
    limiter.init_app(app)
    storage_service.init(app)

    from .models.user import User

    @login_manager.user_loader
    def load_user(user_id: str):
        return db.session.get(User, int(user_id))


def _register_blueprints(app: Flask) -> None:
    from .blueprints.auth import auth_bp
    from .blueprints.admin import admin_bp
    from .blueprints.company import company_bp
    from .blueprints.member import member_bp
    from .blueprints.booking import booking_bp
    from .blueprints.api import api_bp
    from .blueprints.platform import platform_bp
    from .blueprints.community import community_bp

    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(admin_bp, url_prefix="/admin")
    app.register_blueprint(company_bp, url_prefix="/company")
    app.register_blueprint(member_bp, url_prefix="/me")
    app.register_blueprint(booking_bp, url_prefix="/book")
    app.register_blueprint(api_bp, url_prefix="/api/v1")
    app.register_blueprint(platform_bp, url_prefix="/platform")
    app.register_blueprint(community_bp, url_prefix="/hub")

    # API blueprint is stateless — exempt from CSRF (uses tokens)
    csrf.exempt(api_bp)


def _register_cli(app: Flask) -> None:
    from .cli import register_cli
    register_cli(app)


def _register_error_handlers(app: Flask) -> None:
    @app.errorhandler(403)
    def forbidden(e):
        return render_template("errors/403.html"), 403

    @app.errorhandler(404)
    def not_found(e):
        return render_template("errors/404.html"), 404

    @app.errorhandler(500)
    def server_error(e):
        return render_template("errors/500.html"), 500


def _register_context(app: Flask) -> None:
    @app.context_processor
    def inject_globals():
        from flask import g
        return {
            "app_name": app.config.get("APP_NAME", "hub1z"),
            "tenant": getattr(g, "tenant", None),
        }


def _register_root_routes(app: Flask) -> None:
    def tenant_public_data():
        from datetime import datetime, timedelta
        from .models import (Location, PricingPlan, SeatBooking, RoomBooking,
                             BookingStatus)

        tenant = getattr(g, "tenant", None)
        if tenant is None:
            abort(404)

        locations = Location.query.filter_by(is_active=True).order_by(Location.name).all()
        plans = PricingPlan.query.filter_by(is_active=True).order_by(PricingPlan.base_price).all()
        now = datetime.utcnow()
        later = now + timedelta(hours=1)
        availability = []
        for location in locations:
            seats = [seat for seat in location.seats if seat.is_active]
            rooms = [room for room in location.rooms if room.is_active]
            seat_ids = [seat.id for seat in seats]
            room_ids = [room.id for room in rooms]
            booked_seats = (SeatBooking.query
                            .filter(SeatBooking.seat_id.in_(seat_ids))
                            .filter(SeatBooking.status.in_([BookingStatus.CONFIRMED, BookingStatus.CHECKED_IN]))
                            .filter(SeatBooking.start_at < later, SeatBooking.end_at > now)
                            .count()) if seat_ids else 0
            booked_rooms = (RoomBooking.query
                            .filter(RoomBooking.room_id.in_(room_ids))
                            .filter(RoomBooking.status.in_([BookingStatus.CONFIRMED, BookingStatus.CHECKED_IN]))
                            .filter(RoomBooking.start_at < later, RoomBooking.end_at > now)
                            .count()) if room_ids else 0
            availability.append({
                "location": location,
                "seat_count": len(seats),
                "room_count": len(rooms),
                "available_seats": max(0, len(seats) - booked_seats),
                "available_rooms": max(0, len(rooms) - booked_rooms),
            })
        return {
            "tenant": tenant,
            "locations": locations,
            "plans": plans,
            "availability": availability,
        }

    @app.route("/")
    def index():
        if current_user.is_authenticated:
            return redirect(url_for("auth.post_login_redirect"))
        from flask import g
        if getattr(g, "tenant", None):
            return render_template("public/landing.html", **tenant_public_data())
        # No tenant resolved (the platform's own apex domain) — a coworking
        # business's own site, not the SaaS platform's marketing page.
        from .models import PricingTier
        tiers = PricingTier.query.filter_by(is_active=True).order_by(PricingTier.id).all()
        return render_template("public/platform_landing.html", tiers=tiers)

    @app.route("/features")
    def public_features():
        features = [
            ("bookings", "Bookings and availability", "Let members reserve desks and rooms with live conflict detection, recurring rules, waitlists, and check-in workflows."),
            ("memberships", "Memberships and community", "Manage plans, credits, companies, employees, day passes, visitors, announcements, and member support in one place."),
            ("billing", "Billing that fits your operation", "Run subscriptions, invoices, credit notes, refunds, expenses, and India-first tax settings without stitching together spreadsheets."),
            ("multi-location", "One workspace across locations", "Keep locations, floors, resources, managers, pricing, and reporting connected as your coworking brand expands."),
            ("operator-tools", "Operator tools", "Give managers the dashboards, audit history, reports, payroll, expenses, and reception workflows they need every day."),
            ("security", "Tenant-safe by design", "Use role-based access, tenant isolation, two-factor authentication, rate limiting, and audit trails across the platform."),
        ]
        return render_template("public/features.html", features=features)

    @app.route("/features/<slug>")
    def public_feature_detail(slug: str):
        feature_pages = {
            "bookings": ("Bookings and availability", "Turn every desk and room into a simple, bookable experience.", [
                "Hot desks, dedicated desks, private offices, and meeting rooms",
                "Real-time conflict detection and quoting",
                "Recurring room bookings, waitlists, and cancellation refunds",
                "Day passes, QR check-in, visitors, and reception workflows",
            ]),
            "memberships": ("Memberships and community", "Give individuals and teams a better way to belong to your space.", [
                "Monthly, daily, all-access, private office, and day-pass plans",
                "Company credits, employee invitations, allocations, and invoices",
                "Community directory, announcements, guest passes, lockers, and support tickets",
            ]),
            "billing": ("Billing that fits your operation", "Keep the money trail clear while you grow.", [
                "Recurring subscription invoices and usage charges",
                "GST-ready tenant settings, credit notes, refunds, and PDF exports",
                "Manual payment records for UPI, bank transfer, cards, cash, and cheque",
            ]),
            "multi-location": ("One workspace across locations", "Expand without creating a new operating system for every site.", [
                "Shared members, plans, and reporting across locations",
                "Location Managers scoped to their own site",
                "Per-location floors, resources, amenities, pricing, and availability",
            ]),
            "operator-tools": ("Operator tools", "A calmer back office for the work behind hospitality.", [
                "Occupancy, financial, subscription, people, and capacity reports",
                "Payroll, expenses, staff records, and email templates",
                "Reception, visitor check-in, audit logs, and document storage",
            ]),
            "security": ("Tenant-safe by design", "The platform boundary is part of the product.", [
                "Role-based access for platform, tenant, company, and member users",
                "Tenant-scoped data, audit logging, CSRF protection, and rate limiting",
                "TOTP two-factor authentication and secure invitation flows",
            ]),
        }
        page = feature_pages.get(slug)
        if page is None:
            abort(404)
        return render_template("public/feature_detail.html", slug=slug,
                               title=page[0], description=page[1], bullets=page[2])

    @app.route("/pricing")
    def public_pricing():
        from .models import PricingTier
        currency = (request.args.get("currency") or "INR").upper()
        if currency not in {"INR", "USD"}:
            currency = "INR"
        billing = request.args.get("billing", "monthly")
        if billing not in {"monthly", "annual"}:
            billing = "monthly"
        currency_meta = {"INR": ("₹", 1.0), "USD": ("$", 0.012)}
        symbol, rate = currency_meta[currency]
        descriptions = {
            "starter": "A space finding its feet.",
            "growth": "An established single site.",
            "scale": "A larger or multi-floor site.",
            "enterprise": "500+ members or multi-city.",
        }
        feature_sets = {
            "starter": ["1 location", "Bookings, resources and floor plans", "Invoicing and credit notes", "Member portal"],
            "growth": ["Bookings, resources and floor plans", "Recurring billing and credit notes", "Manual payment details", "CRM-ready member portal", "Email support"],
            "scale": ["Multi-location operations", "Recurring billing and reports", "Operator roles and audit log", "Member portal and community", "Priority support"],
            "enterprise": ["Multiple locations", "Advanced access and audit controls", "API-ready operations", "White-label member experience", "Multi-entity billing"],
        }
        plans = []
        for tier in PricingTier.query.filter_by(is_active=True).order_by(PricingTier.id).all():
            monthly = float(tier.monthly_price) * rate if tier.monthly_price is not None else None
            annual = monthly * 10 if monthly is not None else None
            plans.append({
                "tier": tier, "monthly": monthly, "annual": annual,
                "price": annual / 12 if billing == "annual" and annual is not None else monthly,
                "description": descriptions.get(tier.key, "A flexible plan for growing operators."),
                "features": feature_sets.get(tier.key, [
                    f"{tier.max_locations if tier.max_locations is not None else 'Unlimited'} locations",
                    "Bookings, memberships and billing", "Operator reports and member portal",
                ]),
                "popular": tier.key == "growth",
            })
        return render_template("public/pricing.html", plans=plans,
                               currency=currency, currency_symbol=symbol, billing=billing)

    @app.route("/legal")
    def public_legal_imprint():
        sections = [
            ("Who runs this platform",
             ["Hub1z is operated by Hub1z Technologies Private Limited, a company incorporated in India. "
              "Hub1z provides software that coworking operators use to run their own spaces; each operator "
              "listed on this platform remains the independent legal operator of their physical location(s).",
              "Registered office: to be completed with the legal entity's registered address before "
              "production launch. CIN and GSTIN are published on operator invoices and in the billing "
              "section of the operator dashboard."]),
            ("Contact", [
                "General enquiries: hello@hub1z.com",
                "Support: support@hub1z.com",
                "For a specific coworking location, use the contact details published on that operator's "
                "microsite rather than the platform contact above — Hub1z does not manage day-to-day "
                "floor operations."]),
            ("Grievance Officer", [
                "As required under Indian information technology rules, a designated Grievance Officer "
                "reviews complaints about content or conduct on the platform. Reach the Grievance Officer "
                "at grievance@hub1z.com; we aim to acknowledge complaints within a few working days."]),
        ]
        return render_template("public/legal_page.html", eyebrow="Legal", title="Legal & Imprint",
                               updated="September 2026",
                               intro="Company and contact details for the entity behind the Hub1z platform.",
                               sections=sections)

    @app.route("/terms")
    def public_terms():
        sections = [
            ("1. Scope of these Terms",
             ["These Terms of Service govern access to and use of the Hub1z platform by coworking operators "
              "(\"Operators\"), the companies and individuals they host (\"Members\"), and visitors to our "
              "public pages. Each Operator's own house rules and membership agreement govern the physical "
              "use of their space and sit alongside, not instead of, these Terms."]),
            ("2. Accounts",
             ["You must provide accurate information when creating an account and keep your login credentials "
              "confidential. Operators are responsible for the accounts of the staff and managers they invite "
              "into their workspace, and for removing access promptly when a person leaves the team."]),
            ("3. Operator Subscriptions and Billing",
             ["Operators subscribe to a pricing tier that determines platform features and usage limits. "
              "Fees are billed in advance on a recurring basis in the currency and cycle selected at sign-up. "
              "Unless stated otherwise on the pricing page, fees are non-refundable once a billing period has "
              "started, though we will pro-rate or credit fees where a service outage on our part clearly "
              "prevented normal use."]),
            ("4. Acceptable Use",
             ["You agree not to misuse the platform: no attempts to break tenant isolation between Operators, "
              "no scraping or reverse engineering, no uploading unlawful content, and no using the booking or "
              "messaging tools to spam members outside their own workspace."]),
            ("5. Data and Content Ownership",
             ["Operators own the member, booking, and financial data they create using the platform. Hub1z "
              "processes this data to provide the service and does not sell it. See our Privacy Policy for "
              "details on how member data is handled."]),
            ("6. Service Availability",
             ["We work to keep the platform available and will publish planned maintenance windows in "
              "advance where practical. Hub1z is not liable for downtime caused by factors outside our "
              "reasonable control, including third-party cloud infrastructure outages."]),
            ("7. Termination",
             ["Either party may close an Operator account by giving notice as described in the pricing "
              "agreement. We may suspend accounts that breach these Terms, misuse the platform, or fail to "
              "pay outstanding fees, after reasonable notice where the breach is not urgent."]),
            ("8. Limitation of Liability",
             ["To the extent permitted by law, Hub1z's liability for any claim arising from use of the "
              "platform is limited to the fees paid by the relevant Operator in the twelve months preceding "
              "the claim. Hub1z is not liable for indirect or consequential losses."]),
            ("9. Governing Law",
             ["These Terms are governed by the laws of India, and disputes are subject to the exclusive "
              "jurisdiction of the courts at the location of Hub1z's registered office."]),
            ("10. Changes to these Terms",
             ["We may update these Terms as the platform evolves. Material changes will be notified to "
              "Operators by email or in-app notice at least 14 days before taking effect."]),
        ]
        return render_template("public/legal_page.html", eyebrow="Legal", title="Terms of Service",
                               updated="September 2026",
                               intro="These terms describe how coworking operators and their members may use "
                                     "the Hub1z platform.",
                               sections=sections)

    @app.route("/privacy")
    def public_privacy():
        sections = [
            ("1. What this policy covers",
             ["This policy explains how Hub1z Technologies Private Limited collects, uses, and protects "
              "personal data belonging to Operators, their staff, Members, and visitors to our public pages, "
              "in connection with running the Hub1z platform."]),
            ("2. Information we collect",
             ["Account details such as name, email, phone number, and role; workspace data such as bookings, "
              "membership plans, invoices, and documents uploaded by an Operator; and technical data such as "
              "IP address, browser type, and basic usage logs needed to keep the platform secure and "
              "reliable."]),
            ("3. How we use information",
             ["To operate booking, billing, and membership features; to send transactional emails such as "
              "invites, invoices, and password resets; to keep the platform secure against abuse; and to "
              "improve the product based on aggregate, de-identified usage patterns."]),
            ("4. Who we share data with",
             ["We share data with sub-processors that help us run the platform — for example, cloud hosting, "
              "email delivery, and payment or storage providers — under contracts that require them to "
              "protect data at least as strongly as this policy. We do not sell personal data."]),
            ("5. Tenant isolation",
             ["Hub1z is a multi-tenant platform: each Operator's data is logically separated from every "
              "other Operator, and Members only see data belonging to the workspace they belong to."]),
            ("6. Data retention",
             ["We retain data for as long as an Operator account is active, plus a limited period afterward "
              "to meet accounting, tax, and legal obligations, after which it is deleted or anonymised."]),
            ("7. Security",
             ["We use role-based access control, encryption in transit, tenant-scoped database access, and "
              "audit logging. No system is perfectly secure, and we encourage Operators to enable two-factor "
              "authentication for admin accounts."]),
            ("8. Your rights",
             ["Depending on applicable law, you may request access to, correction of, or deletion of your "
              "personal data. Operators should raise member data requests through their workspace admin; "
              "everyone else can reach us directly at privacy@hub1z.com."]),
            ("9. Cookies",
             ["We use a small number of cookies to keep you signed in and to understand basic usage of our "
              "public pages. See our Cookie Policy for the full list and how to manage preferences."]),
            ("10. Changes to this policy",
             ["We will post updates here and, for material changes, notify Operators by email or in-app "
              "notice."]),
            ("11. Contact and Grievance Officer",
             ["For privacy questions or requests, contact privacy@hub1z.com. Data subjects in India may also "
              "contact our Grievance Officer at grievance@hub1z.com under applicable Indian data protection "
              "law."]),
        ]
        return render_template("public/legal_page.html", eyebrow="Legal", title="Privacy Policy",
                               updated="September 2026",
                               intro="How Hub1z collects, uses, and protects personal data on the platform.",
                               sections=sections)

    @app.route("/cookies")
    def public_cookies():
        sections = [
            ("What cookies are",
             ["Cookies are small text files stored in your browser that help a website remember who you are "
              "between visits and how you use its pages."]),
            ("Cookies we use",
             ["Essential cookies keep you signed in and remember your workspace so booking and billing "
              "pages work correctly; these cannot be switched off without breaking core functionality. "
              "Preference cookies remember small choices such as your selected currency on the pricing page. "
              "We use a lightweight, privacy-respecting analytics cookie to understand which public pages "
              "are useful, without building cross-site advertising profiles."]),
            ("Third-party cookies",
             ["Some pages embed third-party assets, such as font or icon delivery networks, that may set "
              "their own minimal cookies as part of normal web delivery. We do not use third-party "
              "advertising cookies."]),
            ("Managing your preferences",
             ["Most browsers let you block or delete cookies through their settings. Blocking essential "
              "cookies will prevent you from staying signed in to a workspace."]),
            ("Changes to this policy",
             ["We will update this page if the cookies we use change materially."]),
            ("Contact",
             ["Questions about cookies can be sent to privacy@hub1z.com."]),
        ]
        return render_template("public/legal_page.html", eyebrow="Legal", title="Cookie Policy",
                               updated="September 2026",
                               intro="What cookies Hub1z uses on its public and workspace pages, and how to "
                                     "manage them.",
                               sections=sections)

    @app.route("/spaces")
    def public_spaces():
        return render_template("public/tenant_spaces.html", **tenant_public_data())

    @app.route("/membership")
    def public_membership():
        return render_template("public/tenant_membership.html", **tenant_public_data())

    @app.route("/availability")
    def public_availability():
        return render_template("public/tenant_availability.html", **tenant_public_data())

    @app.route("/healthz")
    def healthz():
        return {"status": "ok"}, 200

    from flask import send_from_directory, abort as flask_abort

    @app.route("/downloads/<path:key>")
    def local_download(key: str):
        """Local-mode file downloads. Cloud modes use signed URLs and skip this route."""
        if app.config.get("STORAGE_BACKEND") != "local":
            flask_abort(404)
        if not current_user.is_authenticated:
            flask_abort(401)
        return send_from_directory(app.config["LOCAL_STORAGE_DIR"], key, as_attachment=True)
