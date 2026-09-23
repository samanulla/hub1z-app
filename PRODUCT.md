# hub1z — Product Feature Document

> India-first, multi-tenant workspace-management platform (Workday-style back office for coworking operators).
> Runs as a single SaaS deployment that serves many coworking businesses ("tenants"), with per-tenant branding, domain mapping, and localisation.
>
> **Competitive frame:** hub1z's peers are multi-operator coworking SaaS backends —
> Nexudus, OfficeRnD Flex, essensys, Yardi Kube, Cobot. Regus/WeWork are not
> platform-layer comparators; in hub1z's own model, a business like that would
> *be* a tenant (like Adyar Space), not the SaaS operator. Regus-style
> tenant-facing features (day passes, meeting credits, community) are still a
> useful benchmark for §4's Admin/Member modules.

---

## 1. Who uses hub1z?

| Persona | Role code | What they do |
| --- | --- | --- |
| Platform Super Admin | `PLATFORM_OWNER` | Runs the SaaS (**hub1z.com**). Auto-seeded on first setup. Invites/provisions tenants, approves/holds/deactivates them, is the only one who can introduce new pricing tiers or create/edit Platform Managers. Sees all tenants. |
| Platform Manager | `PLATFORM_MANAGER` | A real employee/contractor of the platform. Created by the Platform Super Admin with their own login and a hand-picked set of feature grants (`tenants`, `billing`, `reports` — see `PLATFORM_FEATURES`). Granted all features by default ("do most of the work as admin"); the Super Admin can revoke any of them per manager. Can invite/add/approve/hold tenants and use Billing/Reports if granted those features — but can never suspend/deactivate a tenant, define pricing tiers, or create/edit other platform accounts (including its own permissions), even with every feature granted. Those stay Owner-only to block privilege escalation. |
| Tenant Super Admin | `SUPER_ADMIN` | Owner of a coworking business that runs *on* the platform (e.g. Adyar Space, Winn Space) — invited by, or provisioned by, the platform. Always uses their own company domain (e.g. `admin@adyarspace.com`); a `hub1z.com` address is reserved for the platform itself. Full control of their own tenant. |
| Tenant Manager | `MANAGER` | Day-to-day operator, tenant-wide. Invited by the Tenant Super Admin at `/admin/invites/team/new`. Cannot change tenant settings, audit log, or staff salary. |
| Location Manager | `LOCATION_MANAGER` | Same as Tenant Manager but scoped to exactly one of the tenant's locations (a tenant can run several). Invited the same way, with a location picked at invite time — set on `User.managed_location_id`. |
| Company Admin | `COMPANY_ADMIN` | Represents a company customer of the tenant. Manages employees, subscriptions, invoices. |
| Employee | `EMPLOYEE` | Employee of a company customer. Books using company credits. |
| Individual Member | `INDIVIDUAL` | Freelancer / independent member with their own subscription. |

**Platform vs. tenant, in one line:** `hub1z.com` is the SaaS operator's
own domain — only the Platform Super Admin and Platform Managers live there.
Every coworking business is a *tenant*, reachable at its own
`<slug>.hub1z.com` subdomain or a mapped custom domain, and its
admins/managers/employees always use that tenant's own email domain.

---

## 2. Sign-up flows

- **Platform Super Admin** — auto-seeded (`flask seed-demo`, `platform@hub1z.com` / `ChangeMe123!`). Additional Super Admins via `flask create-admin --platform-owner …`.
- **Platform Manager** — created by a Platform Super Admin at `/platform/team/new` (email, password, active flag, and a checkbox per feature in `PLATFORM_FEATURES`). Edited/deactivated at `/platform/team/<id>/edit`. Always Owner-only to create or edit — never delegable.
- **Tenant provisioning (admin-created)** — a Platform Super Admin, or a Platform Manager with the `tenants` feature, creates the tenant company at `/platform/tenants/new` (auto-fills `<slug>.<PLATFORM_BASE_DOMAIN>`, e.g. `adyarspace.hub1z.com`, if primary_domain left blank) or via CLI `flask create-tenant …`. Staff sets the admin's password directly, and the tenant goes live as `ACTIVE` immediately (staff already vetted it). The tenant admin account must use **the tenant's own domain** (e.g. `admin@adyarspace.com`) — never `hub1z.com`.
- **Tenant provisioning (platform-invited)** — a Platform Super Admin, or a Manager with `tenants`, invites a prospective business at `/platform/tenants/invite` (slug, name, admin name/email — no password). The business sets its own password via a signed 7-day link (`/platform/tenants/accept/<token>`) and lands as `TRIAL`. An explicit **Approve** (`/platform/tenants/<id>/approve`, also gated by `tenants`) moves it to `ACTIVE`.
- **Tenant provisioning (self-serve trial)** — `/auth/register/tenant`, public, no platform staff involved. A business picks a slug/name and sets its own admin password right there; lands as `TRIAL` with `trial_ends_at` = now + `TENANT_TRIAL_DAYS` (default 14). Full product access during the trial — this exists specifically so a prospect can experience the platform before anyone talks to them. Login is blocked once `trial_ends_at` passes while status is still `TRIAL` (`Tenant.is_trial_expired`, checked in `auth.login`); a Platform Super Admin/Manager Approving it (`tenants` feature) moves it to `ACTIVE` and lifts the deadline. Distinct from platform-invited above (staff-initiated) and from the tenant-invites-a-member/company flow below (a different level entirely).
- **Tenant admin → their own team** — once a tenant exists, its Tenant Super Admin invites tenant Managers and Location Managers from `/admin/invites/team/new` (email, role, and — for Location Manager — which of the tenant's locations). Always Super-Admin-only to send, never delegable to an existing Manager (same privilege-escalation guard as Platform Manager creation). Invitee sets their own password at `/admin/invites/accept-team/<token>`.
- **Tenant invites a member or company** — a Tenant Manager/Super Admin sends an email invite from `/admin/invites` (individual or company); the invitee sets their own password at `/admin/invites/accept/<token>` or `/admin/invites/accept-company/<token>` (7-day TTL), same signed-link mechanism as the employee invite below.
- **Company (self-serve)** — `/auth/register/company` → PROSPECT company + COMPANY_ADMIN user + auto-email to tenant super admins for approval.
- **Company (admin-created)** — `/admin/companies/new`.
- **Employee** — Company Admin fills name+email at `/company/employees/new`; system emails a signed **invitation link** (7-day TTL). Invitee sets their own password at `/company/invite/<token>`.
- **Individual** — self-serve at `/auth/register`, but that route is **tenant-scoped**: it only resolves inside a specific tenant's subdomain or custom domain (§5). There is no platform-apex sign-up; someone wanting to join a specific space either self-registers on that tenant's own portal or is invited by it (above).

---

## 3. Account management

- **Login** at `/auth/login` (rate-limited 10/min, 30/hr per IP).
- **Password reset** at `/auth/forgot-password` — sends a signed link (2-hour TTL); reset at `/auth/reset-password/<token>`.
- **Password change** at `/auth/change-password` (requires current password).
- **Two-factor auth (TOTP)** at `/auth/2fa/status` — pyotp-based, QR provisioning at `/auth/2fa/setup`. Login flow detects 2FA-enabled users and prompts at `/auth/2fa/login`.
- **Workspace picker** at `/auth/pick-workspace` for users on the apex domain.

---

## 4. Product modules

### Platform (`/platform/*`)
- **Dashboard** — cross-tenant stats; quick links shown only for features the signed-in staffer holds.
- **Tenants** (`tenants` feature) — provision directly (`/platform/tenants/new`, goes live immediately) or invite (`/platform/tenants/invite`, lands as `TRIAL`). Approve a trial tenant, place an active one on **Hold** (soft, reversible) or release a hold — all under the `tenants` feature, so a Manager can do this if granted it. **Suspend/Reactivate** (hard deactivation) is Platform Super Admin-only regardless of grants.
- **Billing** (`billing` feature, `/platform/billing`) — each tenant's plan tier, live usage vs. that tier's resource caps (locations/seats/private offices/rooms), and custom-domain surcharge tracking. Separate from a tenant's own `/admin` billing (what *that tenant* charges its customers).
- **Pricing tiers** (`/platform/tiers`, **Owner-only**) — define/retire tiers (key, display name, monthly price, resource caps). "Introducing a new pricing model" and tier definitions are deliberately not delegable to a Manager, unlike day-to-day tier *assignment* on the Billing page.
- **Reports** (`reports` feature, `/platform/reports`) — cross-tenant analytics: tenant growth, status mix, top tenants by user count.
- **Team** (`/platform/team`, Owner-only) — create/edit Platform Managers and their feature grants.
All actions audit-logged.

**Tenant lifecycle:** `TRIAL` (invited/self-registered, pending approval) → `ACTIVE` ⇄ `HOLD` (shared, reversible) → `SUSPENDED` (Owner-only hard stop) → `CHURNED`. Direct provisioning skips straight to `ACTIVE`.

**Pricing tiers with resource caps** answer "is tiers for tenants needed?" — yes, and now with teeth: each `PricingTier` (seeded: Starter/Growth/Enterprise) caps `max_locations`/`max_seats`/`max_private_offices`/`max_rooms`, enforced at creation time in `/admin/locations`, `/admin/.../seats`, `/admin/.../rooms` (`app/services/tier_limits.py`) — a tenant at its cap gets a clear "upgrade to add more" message instead of the create silently succeeding. The same module also caps **people** (`resource="person"`) at `max_seats` — see §5. A tenant on a `plan_tier` with no matching `PricingTier` row fails open (unlimited), so this never blocks tenants provisioned before tiers existed.

### Admin — tenant back office (`/admin/*`)
- **Locations, Floors, Seats, Rooms** — inventory + amenities + operating hours per location.
- **Companies** — CRUD + KYC document upload (S3 / local / Azure Blob).
- **Invites** (`/admin/invites`) — invite an individual, a company, or (Super Admin-only) a tenant team member (Manager/Location Manager) by email; they set their own password via a signed link. Alternative to self-serve sign-up for people the tenant wants to bring on directly.
- **Pricing Plans** — hot desk / dedicated / private office / all-access / day pass; monthly + daily cycles.
- **Subscriptions** (`/admin/companies/<id>/subscriptions/new`) — tenant admin/manager sets up a company's plan + quantity, and cancels it. Deliberately **not** company self-serve: it used to be (`/company/plans` let a Company Admin instantly subscribe to any plan/quantity), but that was fully disconnected from actual seat inventory the tenant manages — moved here to match how Seat **Allocations** already work (tenant-controlled).
- **Bookings** — seat + room calendars.
- **Billing** — invoices, line items, payments (UPI / NEFT / RTGS / IMPS / Card / Cash / Cheque), credit notes, refunds (with pending → completed/failed lifecycle). **PDF export** at `/admin/invoices/<id>/pdf`.
- **Expenses** — categories, claims, approve/reject/mark-paid workflow.
- **Staff & Payroll** — records, salary history, payroll runs.
- **Email templates** — per-tenant.
- **Reports** — Occupancy, Financials, Subscriptions, People, **Capacity Heatmap** (`/admin/reports/heatmap`) — all Chart.js.
- **System Settings** — tenant identity, tax rate, invoice prefix, formats.
- **Audit log** — filterable by action/actor/date, **CSV export**.
- **Reception** — day-pass QR scan (`/admin/reception`) and visitor check-in/out (`/hub/reception/visitors`).

### Company (`/company/*`)
Dashboard, employees CRUD (with **email invitations**, capped by both the company's own `max_employees` and the tenant's tier-wide people cap — §5), team bookings visibility, invoices, allocations. Subscriptions are **read-only** here (`/company/plans` shows what the tenant offers; subscribing is tenant-controlled — see Admin above).

### Member (`/me/*` and `/hub/*`)
- Dashboard, seat + room bookings, cancel-with-refund.
- **Day passes** — `/me/day-passes` → issue → QR at `/me/day-passes/<id>/qr.png`.
- **Community hub** (`/hub/*`):
  - **Directory** — opt-in profile with headline, bio, skills, LinkedIn.
  - **Announcements** — pinnable, optionally scoped to a location.
  - **Guest passes** — issue a day pass for a visiting client.
  - **Visitor pre-registration** — reception can check them in/out.
  - **Support tickets** — subject/body/priority, admin resolves.
  - **Printing credits** — ledger balance, admin adjusts.
  - **Lockers** — admin CRUD, assign/release per user.
  - **Refer & earn** — creates a code + reward_credits for each referral.

### Booking add-ons (`/book/*`)
Recurring room bookings (daily/weekly patterns), waitlist for full slots.

---

## 5. Multi-tenancy model

- **Shared code, shared DB.** Every business-scoped table has a `tenant_id` FK (`ON DELETE CASCADE`), indexed.
- **Automatic scoping.** A `do_orm_execute` SQLAlchemy listener injects `tenant_id = <current> OR tenant_id IS NULL` on every SELECT. Platform-Owner routes opt out with `.execution_options(skip_tenant_filter=True)`.
- **Tenant resolution.** `before_request` matches the `Host` header against `Tenant.primary_domain` / `Tenant.custom_domain`. `g.tenant_id` cached at request time to avoid ORM-attribute recursion in the listener.
- **Domain access tiers.** Every tenant gets a free `<slug>.hub1z.com` subdomain (`primary_domain`) by default. A tenant can additionally map its own domain (`custom_domain`, e.g. `adyarspace.com`) — the field and UI already exist (`/platform/tenants/<id>/edit`), but **custom domains are explicitly deprioritized for now** — no billing enforcement, no wildcard-cert automation, not a current focus. Revisit later.
- **Resource caps by tier.** `PricingTier` (Owner-managed, `/platform/tiers`) caps how much inventory a tenant's own plan allows: locations, seats, private offices, conference rooms — **and people**. "Number of seats = number of people, always": `max_seats` also caps the tenant's total EMPLOYEE + INDIVIDUAL + COMPANY_ADMIN headcount, so a tenant can't dodge a seat cap by just not buying desks while still piling on member accounts. Enforced in `app/services/tier_limits.py`, wired into every place a person gets attached to a tenant: self-serve individual/company signup, tenant-initiated invites, and a company adding its own employees. See §4.
- **Dedicated deployment mode** via `DEPLOY_MODE=dedicated` + `TENANT_ID=<n>`.
- **Per-tenant branding** — name, logo, brand colour, tagline, support email — surfaced in `base.html`.
- **Per-tenant localisation** — currency, symbol, locale, timezone, date/datetime/time format, tax rate, tax label, invoice prefix, GSTIN, PAN, legal name.
- **Email uniqueness per tenant** — `UniqueConstraint(tenant_id, email)` so `john@gmail.com` can register with Adyar *and* Winnspace as two independent accounts. Platform Owner row (`tenant_id IS NULL`) enforced globally-unique by a partial index.
- **Known gap in auto-scoping.** `Seat`/`ConferenceRoom`/`SeatBooking`/`RoomBooking` have no `tenant_id` of their own — they're scoped only via their `Location` — so the auto-scoping listener (which only filters `TenantScoped` classes) doesn't touch them directly; any query on them needs an explicit `.join(Location)` to be tenant-safe. Fixed where found (admin dashboard stats, tier-limit checks) but not audited across every query site — a fuller audit is worth doing before this goes to production. Also fixed: `/admin/locations/new` wasn't setting `tenant_id` on the new row (same class of bug as the `/admin/companies/new` one fixed in Phase 6) — both now set it explicitly from `g.tenant_id`.

---

## 6. Localisation (India-first defaults)

- **Currency**: INR, symbol `₹`, Indian number grouping (`1,23,45,678`).
- **Timezone**: `Asia/Kolkata`.
- **Date**: `%d-%b-%Y`. **Datetime**: `%d-%b-%Y %I:%M %p`.
- **Tax**: 18% GST default.
- **Payment methods**: UPI / NEFT / RTGS / IMPS / Card / Cash / Cheque.

Every value is per-tenant, editable from Settings.

---

## 7. Security posture

- Passwords hashed with Werkzeug (`pbkdf2:sha256`).
- Flask-Login session cookies (HTTPS-only in production, `SameSite=Lax`).
- CSRF via Flask-WTF on every form.
- **Rate limiting** — Flask-Limiter: login POST 10/min, 30/hr per IP; forgot-password 5/min, 20/hr.
- **Two-factor auth (TOTP)** — pyotp; QR provisioning; verify with 1-window clock drift tolerance.
- **`_safe_next()`** — blocks external redirects, non-absolute paths, and `/auth/logout`.
- **Audit log** — actor/IP/user-agent for every sensitive mutation; filterable + CSV export.
- **Auto-scoping** — defence in depth against cross-tenant data leaks.

---

## 8. Deployment

- **Local dev**: `docker compose up -d db`, then `flask db upgrade && flask seed-demo && flask run`.
- **Email**: Flask-Mail (SMTP) — works with local MailHog or **AWS SES SMTP** (see [.env.example](.env.example)). Set `MAIL_SUPPRESS_SEND=true` for tests.
- **AWS**: EC2 + RDS PostgreSQL + S3 for documents + SES for email. See [`deploy/aws-setup.md`](deploy/aws-setup.md).
- **Storage**: cloud-agnostic (`STORAGE_BACKEND=s3|azure_blob|local`).
- **Reset test data**: see the "Resetting the database" section in [README.md](README.md).

---

## 9. What's shipped (9 phases, 96 tests)

| Phase | Commit | Features |
| --- | --- | --- |
| Foundational | `0e86e5b` → `582a52b` | 55 routes, admin/company/member portals, India-first, 10 audit fixes |
| Multi-tenant | `678abbf` | Tenant model, PLATFORM_OWNER, per-tenant branding + localisation, `/platform/*` |
| Per-tenant email | `b244015` | `UniqueConstraint(tenant_id, email)` + partial index for platform owner |
| Phase 1 | `7abd4be` | Password reset + change UI + workspace picker + SMTP mail (SES-ready) |
| Phase 2 | `833c698` | Employee email invitations + company approval email + tenant slug auto-fill + session hardening + day-pass QR + reception |
| Phase 3 | `5c7bba5` | 2FA (TOTP) + audit filters/CSV + capacity heatmap + PDF invoices + waitlist + recurring bookings |
| Phase 4 | `7284da9` | Guest passes, visitors, community directory, announcements, printing credits, support tickets, lockers, referrals |
| Phase 5 | `2c16af4` | Modern marketing landing + colourful theme + Inter font + role-based sign-in cards + feature grid |
| Phase 6 | `?` | Platform/tenant terminology cleanup (seed no longer conflates them) + `PLATFORM_MANAGER` role with per-feature grants (`tenants`/`billing`/`reports`) + platform Team/Billing/Reports pages + tenant-initiated invites (`/admin/invites`) for individuals and companies |
| Phase 7 | `?` | Rebrand coworkhub.io → **hub1z.com** + platform-invites-tenant flow (`TRIAL` → Approve) + `HOLD` tenant status (Manager-shared, distinct from Owner-only Suspend) + `PricingTier` model with resource caps, enforced on location/seat/room creation, surfaced on Billing + fixed two pre-existing cross-tenant bugs found in the process (see §5 note) |
| Phase 8 | `?` | Self-serve tenant trial sign-up (`/auth/register/tenant`, time-boxed, login blocked on expiry) + tenant-invites-team-member flow (`/admin/invites/team/new` — Manager or Location Manager, the previously-missing piece for multi-location tenants) + "seats = people" tier rule (`resource="person"` in `tier_limits.py`, capped at `max_seats`, enforced on every person-creation path) + seed data trimmed to exactly 3 accounts, clearly printed on `seed-demo` |
| Phase 9 | (this) | Moved company subscriptions from company self-checkout to tenant-controlled (`/admin/companies/<id>/subscriptions/*`) — the old `/company/plans` self-serve subscribe was fully disconnected from actual seat inventory and bypassed every tier cap |

---

## 10. Roadmap (still open, low priority)

- **Custom domains — deprioritized.** The `custom_domain` field and edit UI exist, but billing enforcement, wildcard-cert automation, and further work here are explicitly on hold per product direction — not a current focus.
- **Tier-limit enforcement coverage** — seats/rooms/locations/people are capped today; nothing yet caps the number of tenant staff accounts (Managers/Location Managers) a tenant can invite.
- **All-Access cross-location booking** (mostly plumbed, needs UI polish).
- **Read replicas** for report queries.
- **Mobile-app JWT API** (blueprint stub exists at `/api/v1`).

---

_Last updated: 2026-09-22._
