# hub1z — Coworking Space Portal

A production-ready Flask application for running a WeWork-style coworking space. Supports
multi-tenant SaaS-style workflows for platform admins, subscribing companies, employees,
and individual members.

**Configured out of the box for India** — INR (₹), Indian number grouping (12,34,56,789),
`Asia/Kolkata` timezone, `%d-%b-%Y` date format, and GST 18%. Every one of these is
editable from the super-admin **System settings** page, so you can run the same codebase
in any region.

## Feature summary

| Area | Capabilities |
|------|--------------|
| **Auth** | Email/password login, role-based access (Platform Super Admin, Platform Manager with per-feature grants, Tenant Super Admin, Tenant Manager, Location Manager, Company Admin, Employee, Individual), password reset hooks |
| **Locations** | Multi-city, multi-building, multi-floor hierarchy with amenities and operating hours |
| **Workspaces** | Hot desks, dedicated desks, private offices, and conference rooms with capacity, amenities, hourly/daily/monthly rates |
| **Companies** | Company onboarding, KYC document uploads (S3), employee roster, seat/office allocations, credit pools |
| **Subscriptions** | Pricing plans (Hot Desk, Dedicated Desk, Private Office, All-Access, Custom), monthly billing cycles, prorated changes, meeting-room credits |
| **Bookings** | Real-time seat booking, conference room booking with conflict detection, recurring bookings, check-in/check-out, cancellation policy |
| **Admin console** | Manage locations, floors, seats, rooms, pricing plans, companies, invoices, documents, occupancy analytics |
| **Platform tenant lifecycle** | Invite a tenant or self-serve free trial (both land `TRIAL`) → Approve (`ACTIVE`), or provision directly (skips straight to `ACTIVE`); Hold/release (reversible, delegable to a Platform Manager) vs. Suspend/Reactivate (hard stop, Platform Super Admin only); trial login blocked once its deadline passes |
| **Tenant team** | Tenant Super Admin invites Manager (tenant-wide) or Location Manager (scoped to one of the tenant's locations) — the only way to create these logins; never delegable to an existing Manager |
| **Pricing tiers** | Owner-managed tiers (Starter/Growth/Enterprise seeded) with resource caps — max locations/seats/private offices/conference rooms, **and people** ("seats = people, always": total employees + individuals + company admins is capped at `max_seats` too) — enforced on every creation path, not just seats |
| **Back office** | Staff members, salary structures, monthly payroll runs, expense management (categories, receipts, approvals), credit notes, refunds, editable email templates |
| **Reports** | Occupancy (booking volume, top rooms, per-location inventory), Financials (revenue vs expenses trend, AR aging, invoice status), Subscriptions (MRR/ARR, plan mix, top customers), People (staff by department, new members, headcount) |
| **Localisation** | Configurable currency (defaults ₹ INR + Indian grouping), timezone (defaults Asia/Kolkata), date/datetime formats (defaults `%d-%b-%Y`), tax label + rate (defaults GST 18%), business identity (GSTIN, PAN, invoice prefix) — all editable by super admin |
| **Company console** | Onboard/offboard employees, allocate seats, view invoices, manage credits, upload company documents |
| **Employee/Individual** | Book seats and rooms, view bookings, download invoices, manage profile |
| **Billing** | Auto-generated monthly invoices, per-booking usage charges, credit tracking, downloadable PDFs (stub) |
| **Scheduled operations** | `flask run-scheduled-jobs` materializes recurring room bookings and generates idempotent monthly invoices; run it from cron, EventBridge, or Azure Scheduler |
| **Documents** | Platform/operator-scoped document storage for contracts, KYC, invoices, expenses, and floor maps; separate S3 bucket roots with cloud-agnostic local/Azure support |
| **Notifications** | Booking confirmations & reminders (email hooks; extend with SES/SendGrid) |
| **Public SaaS website** | Platform features and pricing pages, regional tenant signup defaults, and tenant microsites for spaces, memberships, live availability, and manual UPI/bank payment instructions |
| **APIs** | REST endpoints for mobile/kiosk clients (JWT stub) |

## Tech stack

- **Framework:** Flask 3 + Blueprints + Application Factory
- **ORM:** SQLAlchemy 2 + Flask-Migrate (Alembic)
- **Auth:** Flask-Login + Werkzeug password hashing
- **Forms:** Flask-WTF (CSRF, validation)
- **DB:** PostgreSQL (all environments — in-memory SQLite is used only by the pytest suite)
- **Object storage:** AWS S3 (boto3) with abstraction ready for Azure Blob
- **Frontend:** Server-rendered Jinja2 + Bootstrap 5 + Alpine.js
- **Runtime:** Gunicorn on Docker
- **Secrets:** `.env` locally, AWS Secrets Manager / Azure Key Vault in prod

## Project layout

```
cowork-app/
├── app/
│   ├── __init__.py            # App factory
│   ├── extensions.py          # Shared extension instances
│   ├── config.py              # Env-based configuration
│   ├── cli.py                 # Flask CLI commands (seed, create-admin)
│   ├── models/                # SQLAlchemy models
│   ├── blueprints/            # Feature modules
│   │   ├── auth/
│   │   ├── admin/
│   │   ├── company/
│   │   ├── member/            # Employees + individuals
│   │   ├── booking/
│   │   └── api/
│   ├── services/              # Business logic (booking, pricing, storage, billing)
│   ├── templates/
│   ├── static/
│   └── utils/
├── migrations/                # Created by `flask db init`
├── tests/
├── deploy/                    # AWS/Azure infra hints
├── .env.example
├── requirements.txt
├── wsgi.py
├── Dockerfile
├── docker-compose.yml
└── README.md
```

## Quick start (local)

### Docker (recommended)

Build the app, start PostgreSQL, apply migrations, and seed the demo accounts:

```bash
docker compose up --build -d
```

Open <http://localhost:8000/auth/login> and sign in as the platform super
admin, `platform@hub1z.com` / `ChangeMe123!` (lands on `/platform/`), or as
the sample tenant's admin, `admin@adyarspace.com` / `ChangeMe123!` (lands on
`/admin/`). See [Seeded demo accounts](#seeded-demo-accounts) below.

Useful commands:

```bash
docker compose logs -f web
docker compose ps
docker compose down
```

PostgreSQL is published on host port `5433` by default to avoid conflicting
with a locally installed server. Set `POSTGRES_PORT` before starting Compose to
override it. Database data and uploaded files persist in named Docker volumes.

### Python on the host

Prerequisite: a running PostgreSQL 14+ instance. The fastest way is the bundled
container:

```bash
# Start Postgres in the background
docker compose up -d db
```

Or point `DATABASE_URL` at any existing Postgres you already have.

```bash
# 1. Create virtualenv
python -m venv .venv
source .venv/bin/activate

# 2. Install deps
pip install -r requirements.txt

# 3. Copy env file and edit if needed
cp .env.example .env

# 4. Initialize DB schema
flask --app wsgi.py db upgrade

# 5. Seed sample data + super admin
flask --app wsgi.py seed-demo

# 6. Run
flask --app wsgi.py run --debug
```

Default platform super admin: `platform@hub1z.com` / `ChangeMe123!`.
A sample tenant (Adyar Space) admin is also seeded — see the table below.

## Seeded demo accounts

`flask seed-demo` creates exactly one account per level — platform, tenant,
company — and prints them in a clean summary block at the end of the
command. **Change all passwords before promoting this environment.**

Two separate worlds get seeded: the **platform** (hub1z.com, the SaaS
operator) and one **tenant** (Adyar Space, a coworking business running on
the platform, seeded on the `growth` pricing tier). A tenant's people always
use the tenant's own domain — never a `hub1z.com` address, which is reserved
for platform accounts.

| Role | Email | Password | Lands on | What they can do |
|------|-------|----------|----------|------------------|
| **Platform Super Admin** | `platform@hub1z.com` | `ChangeMe123!` | `/platform/` | Provision/invite/approve/hold tenants; suspend/deactivate them; define pricing tiers; create Platform Managers. Does not touch per-tenant business data. |
| Tenant Super Admin (Adyar Space) | `admin@adyarspace.com` | `ChangeMe123!` | `/admin/` (via `adyarspace.hub1z.com`) | Full access to the Adyar Space tenant. Locations, pricing plans, staff terminations, payroll approvals, invoice voids, credit-note cancellations, refund settlements, email-template deletion, inviting tenant Managers/Location Managers. |
| Company Admin (Acme Robotics) | `jane@acme.example` | `ChangeMe123!` | `/company/` | Manage Acme's employees (capped by both Acme's own `max_employees` and the tenant's tier-wide people cap, see below), view invoices/allocations/subscriptions. Subscriptions themselves are tenant-set (`/admin/companies/<id>/subscriptions`), not company self-serve. |

Not seeded, but available from the UI: **Tenant Manager** / **Location
Manager** (Tenant Super Admin invites from `/admin/invites/team/new` — a
Location Manager is scoped to one of the tenant's locations, picked at
invite time) and **Platform Manager** (Platform Super Admin invites from
`/platform/team/new`).

Platform Managers and tenant Managers/Location Managers are never delegable
to create — only a Platform/Tenant Super Admin can create one or edit its
permissions, even one already holding every feature grant, so nobody can
escalate their own access.

Sign in at `/auth/login`. Individual and company self-registration
(`/auth/register`, `/auth/register/company`) are **tenant-scoped**: they only
work when reached via that tenant's own subdomain or custom domain, never the
platform apex. A tenant can also invite a specific person, company, or team
member directly from `/admin/invites` — the invitee sets their own password
via an emailed link, same mechanism as the existing employee invite.

A business can try hub1z itself, free, at `/auth/register/tenant` — no
platform staff involved. It lands as a `TRIAL` tenant with a
`TENANT_TRIAL_DAYS`-day clock (default 14; env-configurable); login is
blocked once that clock runs out until a Platform Super Admin/Manager
**Approves** it. Staff can otherwise provision a tenant directly (goes live
as `ACTIVE` immediately) at `/platform/tenants/new` or from the CLI:

```powershell
flask --app wsgi.py create-tenant `
    --slug adyarspace `
    --name "Adyar Space" `
    --primary-domain adyarspace.hub1z.com `
    --admin-email admin@adyarspace.com `
    --admin-password ChangeMe123!
```

Every tenant gets that free `<slug>.hub1z.com` subdomain. Mapping a tenant
to its own custom domain (e.g. `adyarspace.com`) — typically a paid add-on —
is set afterwards from `/platform/tenants/<id>/edit` (`custom_domain` field);
the CLI doesn't take a `--custom-domain` flag.

## Bootstrapping configuration

These env vars control app startup (see `.env.example` for the full list):

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `postgresql+psycopg2://coworkhub:coworkhub@localhost:5432/coworkhub` | Postgres connection string. |
| `SECRET_KEY` | *(required)* | Flask session signing key. Generate a fresh one for prod. |
| `BOOTSTRAP_ADMIN_EMAIL` | `admin@adyarspace.com` | Email of the sample **tenant's** Super Admin that `seed-demo` creates (not the platform super admin — that's always `platform@hub1z.com`). |
| `BOOTSTRAP_ADMIN_PASSWORD` | `ChangeMe123!` | Password for the seeded tenant Super Admin. |
| `DEPLOY_MODE` | `shared` | `shared` = one deployment serves many tenants (Host-based routing). `dedicated` = one tenant per deployment. |
| `TENANT_ID` | *(unset)* | Only used when `DEPLOY_MODE=dedicated` — pins this deployment to a specific tenant row. |
| `PLATFORM_BASE_DOMAIN` | `hub1z.com` | The platform's own apex domain. Tenant subdomains are `<slug>.<this>`; reserved so no tenant slug can collide with it. |
| `TENANT_TRIAL_DAYS` | `14` | How long a self-serve tenant trial (`/auth/register/tenant`) lasts before login is blocked pending platform Approval. |
| `STORAGE_BACKEND` | `local` | `local` \| `s3` \| `azure_blob` for document uploads. |
| `TIMEZONE` | `Asia/Kolkata` | Fallback timezone if the tenant's setting is missing. |
| `MAIL_*` | *(unset)* | SMTP config for outgoing email. |

Additional Platform Owner accounts can be created without running `seed-demo`:

```powershell
flask --app wsgi.py create-admin --email you@hub1z.com --password ChangeMe123! --platform-owner
```

## Resetting the database (clear test / synthetic data)

If you've been poking around and want to wipe everything back to a clean seed
state — including test tenants, users, bookings, invoices, etc. — do this:

```powershell
# 1) drop and recreate the DB (fastest and 100% clean)
docker compose exec db psql -U coworkhub -d postgres -c "DROP DATABASE coworkhub;"
docker compose exec db psql -U coworkhub -d postgres -c "CREATE DATABASE coworkhub;"

# 2) rerun migrations
Remove-Item Env:\FLASK_ENV -ErrorAction SilentlyContinue
$env:DATABASE_URL = "postgresql+psycopg2://coworkhub:coworkhub@localhost:5432/coworkhub"
flask --app wsgi.py db upgrade

# 3) reseed the default tenant + demo accounts
flask --app wsgi.py seed-demo
```

Or, if you just want to blow away a single test tenant (e.g. `adyar`) without
touching the rest, use the platform-owner UI at `/platform/tenants` and delete
it — the `ON DELETE CASCADE` on every `tenant_id` FK will remove all of its
users, companies, locations, invoices, and bookings.

## Deploying to AWS

See [`deploy/aws-setup.md`](deploy/aws-setup.md) for a step-by-step production
setup guide covering VPC, security groups, RDS PostgreSQL, S3, SES, IAM
policies, EC2 with the Docker image, Route 53 + ACM, CloudWatch Logs, and
optional ALB / Auto Scaling / ECS Fargate paths.

## Hosting

**AWS (target now)**
- App: ECS Fargate or Elastic Beanstalk running the provided Dockerfile
- DB: RDS PostgreSQL
- Files: S3 bucket (see `STORAGE_BACKEND=s3`)
- Secrets: SSM Parameter Store / Secrets Manager (mapped to env vars)
- CDN: CloudFront for static assets

**Azure (future)**
- App: Azure Container Apps or App Service (same container image)
- DB: Azure Database for PostgreSQL Flexible Server
- Files: switch `STORAGE_BACKEND=azure_blob` (implementation stub included)
- Secrets: Key Vault → env vars via App Service references

The `StorageService` abstracts blob storage so switching clouds is a config change.

## Environment variables

See `.env.example` for the full list. Key ones:

| Var | Purpose |
|-----|---------|
| `FLASK_ENV` | `development` / `production` |
| `SECRET_KEY` | Flask session/CSRF key |
| `DATABASE_URL` | SQLAlchemy URI (Postgres in prod) |
| `STORAGE_BACKEND` | `s3` \| `azure_blob` \| `local` |
| `AWS_S3_BUCKET` | Document bucket |
| `AWS_REGION` | AWS region |
| `AZURE_STORAGE_CONNECTION_STRING` | For Azure mode |
| `MAIL_*` | SMTP settings |

## Roadmap / stubbed for extension

- Stripe/Razorpay integration for card payments
- SES/SendGrid transactional email
- Mobile app JWT auth (`app/blueprints/api`)
- Visitor management & QR check-in
- Slack/Teams notifications
- Occupancy heatmap analytics

## License

MIT
