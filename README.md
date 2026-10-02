# hub1z — Coworking Space Portal

A production-ready Flask application for running a WeWork-style coworking space. Supports
multi-operator SaaS-style workflows for platform admins, subscribing companies, employees,
and individual members.

**Configured out of the box for India** — INR (₹), Indian number grouping (12,34,56,789),
`Asia/Kolkata` timezone, `%d-%b-%Y` date format, and GST 18%. Every one of these is
editable from the super-admin **System settings** page, so you can run the same codebase
in any region.

## Feature summary

| Area | Capabilities |
|------|--------------|
| **Auth** | Email/password login, role-based access (Platform Super Admin, Platform Manager with per-feature grants, Operator Super Admin, Operator Manager, Location Manager, Company Admin, Employee, Individual), password reset hooks |
| **Locations** | Multi-city, multi-building, multi-floor hierarchy with amenities and operating hours |
| **Workspaces** | Hot desks, dedicated desks, private offices, and conference rooms with capacity, amenities, hourly/daily/monthly rates |
| **Companies** | Company onboarding, KYC document uploads (S3), employee roster, seat/office allocations, credit pools |
| **Subscriptions** | Pricing plans (Hot Desk, Dedicated Desk, Private Office, All-Access, Custom), monthly billing cycles, prorated changes, meeting-room credits |
| **Bookings** | Real-time seat booking, conference room booking with conflict detection, recurring bookings, check-in/check-out, cancellation policy |
| **Admin console** | Manage locations, floors, seats, rooms, pricing plans, companies, invoices, documents, occupancy analytics |
| **Platform operator lifecycle** | Configurable Growth trial, continued access after expiry, operator-staff billing notice, and paid activation only after confirmed payment. Hold/release under the operators grant; Suspend/Reactivate under the separate operator_suspension grant. Payments never remove a suspension. |
| **Operator team** | Operator Super Admin invites Manager (operator-wide) or Location Manager (scoped to one of the operator's locations) — the only way to create these logins; never delegable to an existing Manager |
| **Pricing tiers** | Configurable Starter/Growth/Enterprise prices, annual discounts, contracted seats, locations, staff, open-manual-lead and storage allowances. Paid feature/add-on enforcement, Owner-only plan selection and payment-confirmed activation. Active contracted seats drive billing, not member headcount or physical inventory. |
| **Back office** | Staff members, salary structures, monthly payroll runs, expense management (categories, receipts, approvals), credit notes, refunds, editable email templates |
| **Reports** | Occupancy (booking volume, top rooms, per-location inventory), Financials (revenue vs expenses trend, AR aging, invoice status), Subscriptions (MRR/ARR, plan mix, top customers), People (staff by department, new members, headcount) |
| **Localisation** | Configurable currency (defaults ₹ INR + Indian grouping), timezone (defaults Asia/Kolkata), date/datetime formats (defaults `%d-%b-%Y`), tax label + rate (defaults GST 18%), business identity (GSTIN, PAN, invoice prefix) — all editable by super admin |
| **Company console** | Onboard/offboard employees, allocate seats, view invoices, manage credits, upload company documents |
| **Employee/Individual** | Book seats and rooms, view bookings, download invoices, manage profile |
| **Billing** | Auto-generated monthly invoices, per-booking usage charges, credit tracking, downloadable PDFs (stub) |
| **Scheduled operations** | `flask run-scheduled-jobs` materializes recurring room bookings, generates idempotent monthly invoices, and runs the monthly credit cycle (`flask credits-cycle`: expire old credits, start pending allocation changes, grant this month's credits) and the no-show release (`flask release-no-shows`: frees rooms nobody checked in to and closes finished meetings); run `run-scheduled-jobs` daily and `release-no-shows` every 5 minutes from cron, EventBridge, or Azure Scheduler |
| **Documents** | Platform/operator-scoped document storage for contracts, KYC, invoices, expenses, and floor maps; separate S3 bucket roots with cloud-agnostic local/Azure support |
| **Notifications** | Booking confirmations & reminders (email hooks; extend with SES/SendGrid) |
| **Public SaaS website** | Platform features and pricing pages, regional operator signup defaults, and operator microsites for spaces, memberships, live availability, and manual UPI/bank payment instructions |
| **APIs** | REST endpoints for mobile/kiosk clients (JWT stub) |

### Pricing rollout: stages 1-3

Apply `flask db upgrade` through revision `e2f7a9c4b106` (Docker Compose does this on start), then configure `/platform/tiers` and `/platform/catalog`.
New tiers are drafts without prices. Public pricing is off until explicitly enabled;
only active, public, effective tiers are shown, with Scale excluded. Annual pricing
uses 12 monthly payments less the configured percentage discount.

Platform Managers need separate `pricing`, `payment_setup`, `operator_suspension`
and `documents` grants. Team management remains Owner-only. Hub1z tax and invoice
defaults are configured at `/platform/payment-details`. Saving a UPI ID generates
a downloadable QR; no image upload is required. Invoice QRs include the outstanding
balance, but scanning never confirms payment automatically.

Unpaid existing operators receive a fresh configurable trial (default 14 days).
Expiry does not block login or remove trial features. The billing banner is shown
only to operator staff and stays dismissed until their next login. Companies and
members neither see this banner nor choose/pay Hub1z plans.

Operator Owners select plans and add-ons at `/admin/hub1z-billing/plans`. A request
issues a GST invoice due on receipt; features activate only after full payment.
Hub1z Finance can record UPI, GPay, bank, cash or other payments, or accept a reported
payment. Partial payments reduce the balance without activating the requested plan.
When an operator reports a payment, staff with the `billing` grant see a "Payments to
confirm" card on the platform dashboard, a notice on every platform page and a Finance
badge, and `PLATFORM_SUPPORT_EMAIL` receives an email.
Upgrades charge the remaining-day difference and keep the renewal date. Downgrades
and cycle changes apply at renewal, subject to current usage fitting the new limits.

Run `flask run-scheduled-jobs` daily for advance renewal invoices and monthly seat/location
overage invoices in arrears, including on annual plans. Unpaid renewals produce notices,
not automatic suspension. Paid prices/features are snapshotted; catalog edits do not
silently rewrite existing contracts.

Virtual Office/NOC, White Label and Extra Storage (5 GB per unit) are separately paid
add-ons, including on Enterprise. At renewal an Owner can cancel any add-on or reduce its
units; an unpaid renewal invoice is repriced immediately, and a change is refused once
the next renewal is paid or part-paid. Unbuilt services remain Coming Soon. Staff accounts,
open manual leads, storage and configured seat/location policies are enforced;
website enquiries are always saved and excluded from the manual lead allowance.
Legacy Scale contracts and rollback columns are preserved.

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

Open <http://localhost:8000/auth/login> and sign in as the platform owner,
`platform@hub1z.com` / `ChangeMe123!` (lands on `/platform/`). Run
`flask --app wsgi.py create-operator ...` or provision an operator from
`/platform/` before using operator and member workflows.

Useful commands:

```bash
docker compose logs -f web
docker compose ps
docker compose down
```

PostgreSQL is published on host port `5433` by default to avoid conflicting
with a locally installed server. Set `POSTGRES_PORT` before starting Compose to
override it. Database data and uploaded files persist in named Docker volumes.

### Testing each role locally

Each role signs in on its own host. Browsers resolve `*.localhost` to your
machine, so no DNS or VM is needed. Start with `localhost` as the platform apex
and seed one login per role (development only; refuses to run in production):

```bash
PLATFORM_BASE_DOMAIN=localhost docker compose up -d --build --wait
docker compose exec web flask --app wsgi.py seed-personas
```

| Role | Sign in at | Login | Lands on |
|---|---|---|---|
| Platform owner (hub1z) | <http://localhost:8000/auth/login> | `PLATFORM_OWNER_EMAIL` / `PLATFORM_OWNER_PASSWORD` (defaults `platform@hub1z.com` / `ChangeMe123!`) | `/platform/` |
| Platform manager | <http://localhost:8000/auth/login> | `manager@hub1z.com` / `DemoPass123!` | `/platform/` |
| Operator owner | <http://demo.localhost:8000/auth/login> | `owner@demospace.com` / `DemoPass123!` | `/admin/` |
| Operator manager | <http://demo.localhost:8000/auth/login> | `manager@demospace.com` / `DemoPass123!` | `/admin/` |
| Location manager | <http://demo.localhost:8000/auth/login> | `location@demospace.com` / `DemoPass123!` | `/admin/` |
| Company admin (company signed up with the operator) | <http://demo.localhost:8000/auth/login> | `admin@acmeco.com` / `DemoPass123!` | `/company/` |
| Employee (added by the company admin) | <http://demo.localhost:8000/auth/login> | `employee@acmeco.com` / `DemoPass123!` | `/me/` |
| Individual (added by the operator) | <http://demo.localhost:8000/auth/login> | `individual@demospace.com` / `DemoPass123!` | `/me/` |

A second operator (`other.localhost`, owner `owner@otherspace.com`) is seeded so
you can confirm nothing crosses between operators. A login only works on its
own host: an operator user on another operator's host or on the apex, and the
platform owner on an operator host, are all refused. `tests/test_role_paths.py`
and `tests/test_operator_isolation.py` cover the same paths automatically.

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

# 5. Seed the platform owner only
flask --app wsgi.py seed-demo

# 6. Run
flask --app wsgi.py run --debug
```

Default platform owner: `platform@hub1z.com` / `ChangeMe123!`.
`flask seed-demo` creates only this platform account; it does not create an
operator, company, member, location, inventory, or sample billing data.
**Change the password before promoting this environment.**

After the platform owner signs in, provision an operator from `/platform/` or
use `create-operator`. The operator owner then creates locations, plans,
companies, members, and operator staff from that workspace.

A business can try hub1z itself, free, at `/auth/register/operator` — no
platform staff involved. It lands as a `TRIAL` operator with a
trial clock configured at `/platform/tiers` (default 14 days on Growth). Login
and trial features continue after expiry while payment is pending. Staff can
also provision an operator at `/platform/operators/new` or from the CLI;
approval does not replace payment-confirmed plan activation:

```powershell
flask --app wsgi.py create-operator `
    --slug adyarspace `
    --name "Adyar Space" `
    --primary-domain adyarspace.hub1z.com `
    --admin-email admin@adyarspace.com `
    --admin-password ChangeMe123!
```

Every operator gets that free `<slug>.hub1z.com` subdomain. Mapping an operator
to its own custom domain (e.g. `adyarspace.com`) — typically a paid add-on —
is set afterwards from `/platform/operators/<id>/edit` (`custom_domain` field);
the CLI doesn't take a `--custom-domain` flag.

## Bootstrapping configuration

These env vars control app startup (see `.env.example` for the full list):

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `postgresql+psycopg2://coworkhub:coworkhub@localhost:5432/hub1z_db` | Postgres connection string. |
| `SECRET_KEY` | *(required)* | Flask session signing key. Generate a fresh one for prod. |
| `BOOTSTRAP_ADMIN_EMAIL` | `admin@adyarspace.com` | Email of the sample **operator's** Super Admin that `seed-demo` creates (not the platform super admin — that's always `platform@hub1z.com`). |
| `BOOTSTRAP_ADMIN_PASSWORD` | `ChangeMe123!` | Password for the seeded operator Super Admin. |
| `DEPLOY_MODE` | `shared` | `shared` = one deployment serves many operators (Host-based routing). `dedicated` = one operator per deployment. |
| `OPERATOR_ID` | *(unset)* | Only used when `DEPLOY_MODE=dedicated` — pins this deployment to a specific operator row. |
| `PLATFORM_BASE_DOMAIN` | `hub1z.com` | The platform's own apex domain. Operator subdomains are `<slug>.<this>`; reserved so no operator slug can collide with it. |
| `OPERATOR_TRIAL_DAYS` | `14` | Legacy trial-duration fallback; current trial duration and tier are configured at `/platform/tiers`. Expiry does not block login. |
| `STORAGE_BACKEND` | `local` | `local` \| `s3` \| `azure_blob` for document uploads. |
| `TIMEZONE` | `Asia/Kolkata` | Fallback timezone if the operator's setting is missing. |
| `MAIL_*` | *(unset)* | SMTP config for outgoing email. |
| `MAIL_REDIRECT_TO` | `admin@hub1z.com` | Every email to an address outside `MAIL_REDIRECT_KEEP_DOMAINS` is delivered here instead, with the intended recipient in the subject and an `X-Original-To` header. This protects SES approval from bounces; set it empty to deliver normally. Password-reset and invite links reach this inbox only, not the real user. |
| `MAIL_REDIRECT_KEEP_DOMAINS` | `hub1z.com` | Comma-separated recipient domains that are always delivered as addressed (for example `support@hub1z.com`). |
| `PLATFORM_SUPPORT_EMAIL` | `support@hub1z.com` | Receives a notice whenever an operator reports a payment to Hub1z, plus support tickets for operators without their own support address. |

Additional Platform Owner accounts can be created without running `seed-demo`:

```powershell
flask --app wsgi.py create-admin --email you@hub1z.com --password ChangeMe123! --platform-owner
```

## Resetting the database (clear test / synthetic data)

> **One-time reset after the operator-isolation release.** Migrations were
> re-baselined into a single `baseline` revision and every table was renamed
> from `tenant` to `operator`. A database created by the older migrations cannot
> be upgraded in place: recreate it (steps below, or `docker compose down -v`).
> Environment variables were renamed too: `TENANT_ID` -> `OPERATOR_ID` and
> `TENANT_TRIAL_DAYS` -> `OPERATOR_TRIAL_DAYS`; update the VM's `.env`.

If you've been poking around and want to wipe everything back to a clean seed
state — including test operators, users, bookings, invoices, etc. — do this:

```powershell
# 1) drop and recreate the DB (fastest and 100% clean)
docker compose exec db psql -U coworkhub -d postgres -c "DROP DATABASE hub1z_db;"
docker compose exec db psql -U coworkhub -d postgres -c "CREATE DATABASE hub1z_db;"

# 2) rerun migrations
Remove-Item Env:\FLASK_ENV -ErrorAction SilentlyContinue
$env:DATABASE_URL = "postgresql+psycopg2://coworkhub:coworkhub@localhost:5432/hub1z_db"
flask --app wsgi.py db upgrade

# 3) reseed the default operator + demo accounts
flask --app wsgi.py seed-demo
```

Or, if you just want to blow away a single test operator (e.g. `adyar`) without
touching the rest, use the platform-owner UI at `/platform/operators` and delete
it — the `ON DELETE CASCADE` on every `operator_id` FK will remove all of its
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
