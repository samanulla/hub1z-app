# hub1z — Product Feature Document

> India-first, multi-operator workspace-management platform (Workday-style back office for coworking operators).
> Runs as a single SaaS deployment that serves many coworking businesses ("operators"), with per-operator branding, domain mapping, and localisation.
>
> **Competitive frame:** hub1z's peers are multi-operator coworking SaaS backends —
> Nexudus, OfficeRnD Flex, essensys, Yardi Kube, Cobot. Regus/WeWork are not
> platform-layer comparators; in hub1z's own model, a business like that would
> *be* an operator (like Adyar Space), not the SaaS operator. Regus-style
> operator-facing features (day passes, meeting credits, community) are still a
> useful benchmark for §4's Admin/Member modules.

---

## 1. Who uses hub1z?

| Persona | Role code | What they do |
| --- | --- | --- |
| Platform Super Admin | `PLATFORM_OWNER` | Runs the SaaS (**hub1z.com**). Invites/provisions operators and delegates pricing, payment setup, billing, suspension and documents separately. Platform team/permission administration and attendance correction remain Owner-only. Sees all operators. |
| Platform Manager | `PLATFORM_MANAGER` | Platform staff with explicit per-feature grants. Can manage pricing, payment setup, billing, documents or suspension only when granted that feature. Cannot administer platform accounts, change permissions or correct platform attendance. |
| Operator Super Admin | `SUPER_ADMIN` | Owner of a coworking business that runs *on* the platform (e.g. Adyar Space, Winn Space) — invited by, or provisioned by, the platform. Always uses their own company domain (e.g. `admin@adyarspace.com`); a `hub1z.com` address is reserved for the platform itself. Full control of their own operator. |
| Operator Manager | `MANAGER` | Day-to-day manager, operator-wide. Invited by the Operator Super Admin at `/admin/invites/team/new`. Cannot change operator settings, audit log, or staff salary. |
| Location Manager | `LOCATION_MANAGER` | Same as Operator Manager but scoped to exactly one of the operator's locations (an operator can run several). Invited the same way, with a location picked at invite time — set on `User.managed_location_id`. |
| Company Admin | `COMPANY_ADMIN` | Represents a company customer of the operator. Manages employees, subscriptions, invoices. |
| Employee | `EMPLOYEE` | Employee of a company customer. Books using company credits. |
| Individual Member | `INDIVIDUAL` | Freelancer / independent member with their own subscription. |

**Platform vs. operator, in one line:** `hub1z.com` is the SaaS operator's
own domain — only the Platform Super Admin and Platform Managers live there.
Every coworking business is a *operator*, reachable at its own
`<slug>.hub1z.com` subdomain or a mapped custom domain, and its
admins/managers/employees always use that operator's own email domain.

---

## 2. Sign-up flows

- **Platform Super Admin** — auto-seeded (`flask seed-demo`, `platform@hub1z.com` / `ChangeMe123!`). Additional Super Admins via `flask create-admin --platform-owner …`.
- **Platform Manager** — created by a Platform Super Admin at `/platform/team/new` (email, password, active flag, and a checkbox per feature in `PLATFORM_FEATURES`). Edited/deactivated at `/platform/team/<id>/edit`. Always Owner-only to create or edit — never delegable.
- **Operator provisioning (admin-created)** — platform staff with `operators` create the business at `/platform/operators/new` or via `flask create-operator …` and set the Owner password. Provisioning does not grant a paid contract: new operators receive trial entitlements until full payment confirms a selected plan. The Owner uses the operator's own email domain, never the platform's.
- **Operator provisioning (platform-invited)** — a Platform Super Admin, or a Manager with `operators`, invites a prospective business at `/platform/operators/invite` (slug, name, admin name/email — no password). The business sets its own password via a signed 7-day link (`/platform/operators/accept/<token>`) and lands as `TRIAL`. An explicit **Approve** (`/platform/operators/<id>/approve`, also gated by `operators`) moves it to `ACTIVE`.
- **Operator provisioning (self-serve trial)** — `/auth/register/operator`, public. A business picks its slug/name and Owner password, then receives the configured trial tier and duration (default Growth for 14 days). Login and trial features remain available after expiry until a paid plan is selected and fully paid. Only operator staff see the billing notice; company admins and members do not. Approval is separate from payment-confirmed plan activation.
- **Operator admin → their own team** — once an operator exists, its Operator Super Admin invites operator Managers and Location Managers from `/admin/invites/team/new` (email, role, and — for Location Manager — which of the operator's locations). Always Super-Admin-only to send, never delegable to an existing Manager (same privilege-escalation guard as Platform Manager creation). Invitee sets their own password at `/admin/invites/accept-team/<token>`.
- **Operator invites a member or company** — an Operator Manager/Super Admin sends an email invite from `/admin/invites` (individual or company); the invitee sets their own password at `/admin/invites/accept/<token>` or `/admin/invites/accept-company/<token>` (7-day TTL), same signed-link mechanism as the employee invite below.
- **Company (self-serve)** — `/auth/register/company` → PROSPECT company + COMPANY_ADMIN user + auto-email to operator super admins for approval.
- **Company (admin-created)** — `/admin/companies/new`.
- **Employee** — Company Admin fills name+email at `/company/employees/new`; system emails a signed **invitation link** (7-day TTL). Invitee sets their own password at `/company/invite/<token>`.
- **Individual** — self-serve at `/auth/register`, but that route is **operator-scoped**: it only resolves inside a specific operator's subdomain or custom domain (§5). There is no platform-apex sign-up; someone wanting to join a specific space either self-registers on that operator's own portal or is invited by it (above).

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
- **Dashboard** — cross-operator stats; quick links shown only for features the signed-in staffer holds.
- **Operators** (`operators` feature) — provision directly (`/platform/operators/new`, goes live immediately) or invite (`/platform/operators/invite`, lands as `TRIAL`). Approve trials and Hold/release under `operators`. Suspend/Reactivate requires the separate `operator_suspension` grant, including status changes through the operator edit form.
- **Billing** (`billing` feature, `/platform/billing`) — operator subscriptions, contracted seat and location usage, negotiated terms and pricing snapshots. Separate from an operator's own `/admin` billing to customers.
- **Pricing tiers** (`pricing` feature, `/platform/tiers`) — configure Starter/Growth/Enterprise prices, annual discount, limits, included features, trial settings and public visibility. Missing tiers are seeded as unpriced drafts; Scale is not advertised.
- **Catalog** (`pricing` feature, `/platform/catalog`) — fixed feature codes with editable names, descriptions, prices and availability. Always-on features, lockable plan features, paid add-ons and usage services are separate. Unbuilt services cannot be advertised as available; Razorpay and WhatsApp remain Coming Soon.
- **Payment and tax setup** (`payment_setup` feature, `/platform/payment-details`) — Hub1z payment details, GST state/rate, SAC, invoice prefix and payment terms. A saved UPI ID generates the QR without an upload. Plan invoices calculate CGST/SGST or IGST and show confirmed receipts and outstanding balances.
- **Documents** (`documents` feature) — platform documents, separately delegable from billing.
- **Reports** (`reports` feature, `/platform/reports`) — cross-operator analytics: operator growth, status mix, top operators by user count.
- **Team** (`/platform/team`, Owner-only) — create/edit Platform Managers and their feature grants.
- **Leads** (`leads` feature, `/platform/leads`) — the Platform's own pipeline of prospective operators (New, Demo booked, Trial running, Negotiation, Won/Lost) with board and list views, follow-ups, history and CSV export. Stored with no operator, so operators never see them.
- **Attendance** (`/platform/attendance`) — the Hub1z team's check-in/out. The Owner sees the team log; the Owner and Managers with `reports` also see head-counts per operator (no names).
All actions audit-logged.

### Public website
- **Platform discovery** — `/features`, `/features/<slug>`, and `/pricing` explain the operator product and published pricing tiers.
- **Operator microsites** — each operator homepage links to `/spaces`, `/membership`, and `/availability`, using that operator's locations, active plans, and current resource snapshot.
- **Regional signup** — self-serve operator signup captures country and applies initial currency, locale, and timezone defaults; these can be edited later.
- **UPI payments (no gateway)** — every open invoice has a UPI QR with the payee and amount filled in (`/company/invoices`, `/me/invoices` for individuals), plus Google Pay and bank details. The payer reports the payment; the operator confirms it on the invoice. Operators pay Hub1z the same way from `/admin/hub1z-billing`, using the Hub1z payment details the Platform Owner sets at `/platform/payment-details`; Hub1z confirms on the Finance page. Razorpay (cards, netbanking, automatic confirmation, paid into the operator's own Razorpay account) is shown as coming soon.

**Operator lifecycle:** `TRIAL` → `ACTIVE` ⇄ `HOLD` → `SUSPENDED` → `CHURNED`. Operational status and paid subscription status are separate; staff approval/provisioning does not activate unpaid plan features. Payment does not release an explicit hold or suspension.

**Pricing rollout, stages 1-3 (local review):** configurable Starter/Growth/Enterprise tiers, feature catalog, delegated grants, tax setup, retained-access trials, paid subscriptions and quota enforcement are implemented. Public pricing remains opt-in; Scale is excluded publicly but legacy contracts are preserved. Annual prices are 12 months less the configured discount. Always-on features are read-only; optional features are configurable on ordinary tiers, while Enterprise includes all lockable features without automatically including paid add-ons.

Only the operator Owner selects Hub1z plans at `/admin/hub1z-billing/plans`. Plan/add-on requests issue invoices due on receipt; partial payments do not activate features. Finance confirms UPI/GPay/bank/cash/other payments, optionally with a reference, or accepts reported payments through the same activation path. Upgrades charge the remaining-day difference and preserve renewal dates. Downgrades and cycle changes are scheduled at renewal and blocked if current usage exceeds the target allowances. Base plans/add-ons bill in advance; extra contracted seats/locations bill monthly in arrears. Renewal invoices are issued ahead of time; overdue payment does not auto-suspend an operator, and paying does not remove an explicit suspension.

Virtual Office/NOC, White Label and Extra Storage (5 GB units) are separate paid add-ons, also on Enterprise. At renewal an Owner can cancel any add-on or reduce its units (repricing an unpaid renewal invoice; refused once the next renewal is paid or part-paid). Unbuilt integrations and live PAN/GSTIN checks remain Coming Soon. Staff, open-manual-lead and storage quotas are enforced; website enquiries are always saved without consuming manual lead capacity. Paid contracts retain snapshots rather than silently adopting catalog edits. Unpaid existing operators receive a fresh rollout trial; paid history and suspended status are preserved.

When an operator reports a payment to Hub1z, platform staff with the `billing` grant see it as a "Payments to confirm" card on the platform dashboard, a notice on every platform page, a badge on Finance, and an email to `PLATFORM_SUPPORT_EMAIL`. One pending report per invoice is allowed; a later duplicate for an already-paid invoice is closed rather than counted twice. Hub1z invoices, credit notes and refund advices carry the Hub1z logo.

**Outgoing email:** while SES approval is pending, every email to an address outside `MAIL_REDIRECT_KEEP_DOMAINS` (default `hub1z.com`) is delivered to `MAIL_REDIRECT_TO` (default `admin@hub1z.com`) with the intended recipient shown in the subject. Set `MAIL_REDIRECT_TO` empty to deliver normally.

### Admin — operator back office (`/admin/*`)
- **Locations, Floors, Seats, Rooms** — inventory + amenities + operating hours per location.
- **Companies** — CRUD + KYC document upload (S3 / local / Azure Blob).
- **Invites** (`/admin/invites`) — invite an individual, a company, or (Super Admin-only) an operator team member (Manager/Location Manager) by email; they set their own password via a signed link. Alternative to self-serve sign-up for people the operator wants to bring on directly.
- **Pricing Plans** — hot desk / dedicated / private office / all-access / day pass; monthly + daily cycles.
- **Subscriptions** (`/admin/companies/<id>/subscriptions/new`) — operator admin/manager sets up a company's plan + quantity, and cancels it. Deliberately **not** company self-serve: it used to be (`/company/plans` let a Company Admin instantly subscribe to any plan/quantity), but that was fully disconnected from actual seat inventory the operator manages — moved here to match how Seat **Allocations** already work (operator-controlled).
- **Bookings** — seat + room calendars.
- **Billing** — invoices, line items, payments (UPI / NEFT / RTGS / IMPS / Card / Cash / Cheque), credit notes, refunds (with pending → completed/failed lifecycle). **PDF export** at `/admin/invoices/<id>/pdf`.
- **Expenses** — categories, claims, approve/reject/mark-paid workflow.
- **Staff & Payroll** — records, salary history, payroll runs.
- **Email templates** — per-operator.
- **Reports** — Occupancy, Financials, Subscriptions, People, **Capacity Heatmap** (`/admin/reports/heatmap`) — all Chart.js.
- **System Settings** — operator identity, tax rate, invoice prefix, formats.
- **Workspace settings** — Operator Super Admin selects the primary location; its address is snapshotted onto new invoices.
- **Audit log** — filterable by action/actor/date, **CSV export**.
- **Reception** — day-pass QR scan (`/admin/reception`) and visitor check-in/out (`/hub/reception/visitors`).
- **Leads** (`/admin/leads`) — the operator's own enquiry pipeline (New, Contacted, Tour booked, Proposal sent, Won/Lost): board with drag-and-drop, list, follow-ups due, conversion, history notes, CSV export.
- **Attendance** (`/admin/attendance`) — who is in the space (members and team), a filterable log with CSV export, manual check-in, and QR check-in with no hardware: a signed **location QR** (printed poster, or a rotating code on a reception screen) is scanned with the person's own phone camera and opens `/checkin/<token>`; a personal **member QR** (`/checkin/pass`) is scanned by reception with the browser camera (`/admin/attendance/scan`). Posters can be retired from `/admin/attendance/qr`.
- **Mail & parcels** (`/admin/parcels`) — reception logs letters, parcels and courier documents for a person or a company; the recipient is emailed a 6-digit pickup code; hand-over (with optional code check), return to sender and reminders. Members see theirs at `/me/parcels`, company admins at `/company/parcels`.
- **Virtual office** — a plan type with no desk. Active virtual office clients (and the operator) download a No Objection Certificate for GST and ROC registration (`/company/subscriptions/<id>/address-letter.pdf`).
- **Alerts** (`/admin/alerts`, plus "Needs attention" on the dashboard) — agreements ending within 60 days, lock-ins ending within 30, move-outs, rate revisions, overdue invoices, payments to confirm, parcels waiting over 3 days and lead follow-ups. The hourly scheduler emails each new item once: a digest to the operator team, renewal reminders and overdue payment reminders (with the UPI link) to the customer.
- **Installable phone app** — every site is a Progressive Web App (`/manifest.webmanifest`, `/sw.js`): operator sites install with the operator's name and colour, the Platform as Hub1z, with shortcuts to Check in, Book and Calendar.

### Company (`/company/*`)
Dashboard, employees CRUD (with **email invitations**, subject to the company's own `max_employees`), team bookings visibility, invoices, allocations. Subscriptions are **read-only** here (`/company/plans` shows what the operator offers; subscribing is operator-controlled — see Admin above). Company admins do not select or pay for Hub1z operator plans.

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

## 5. Multi-operator model

- **Shared code, shared DB.** Every business-scoped table has a `operator_id` FK (`ON DELETE CASCADE`), indexed.
- **Automatic scoping.** A `do_orm_execute` SQLAlchemy listener injects `operator_id = <current> OR operator_id IS NULL` on every SELECT. Platform-Owner routes opt out with `.execution_options(skip_operator_filter=True)`.
- **Operator resolution.** `before_request` matches the `Host` header against `Operator.primary_domain` / `Operator.custom_domain`. `g.operator_id` cached at request time to avoid ORM-attribute recursion in the listener.
- **Domain access tiers.** Every operator gets a free `<slug>.hub1z.com` subdomain. New custom-domain changes through the portal require the paid White Label add-on; legacy mappings remain intact. DNS and certificate automation remain outside this rollout.
- **SaaS pricing usage.** Active contracted seats and locations determine billing, independently of inventory and customer headcount. Configured staff, open-manual-lead and storage limits are enforced, along with seat/location overage policies. Public website enquiries bypass the manual lead allowance and are saved before notification emails are attempted.
- **Dedicated deployment mode** via `DEPLOY_MODE=dedicated` + `OPERATOR_ID=<n>`.
- **Per-operator branding** — name, logo, brand colour, tagline, support email — surfaced in `base.html`.
- **Per-operator localisation** — currency, symbol, locale, timezone, date/datetime/time format, tax rate, tax label, invoice prefix, GSTIN, PAN, legal name.
- **Email uniqueness per operator** — `UniqueConstraint(operator_id, email)` so `john@gmail.com` can register with Adyar *and* Winnspace as two independent accounts. Platform Owner row (`operator_id IS NULL`) enforced globally-unique by a partial index.
- **Known gap in auto-scoping.** `Seat`/`ConferenceRoom`/`SeatBooking`/`RoomBooking` have no `operator_id` of their own — they're scoped only via their `Location` — so the auto-scoping listener (which only filters `OperatorScoped` classes) doesn't touch them directly; any query on them needs an explicit `.join(Location)` to be operator-safe. Fixed where found (admin dashboard stats, tier-limit checks) but not audited across every query site — a fuller audit is worth doing before this goes to production. Also fixed: `/admin/locations/new` wasn't setting `operator_id` on the new row (same class of bug as the `/admin/companies/new` one fixed in Phase 6) — both now set it explicitly from `g.operator_id`.

---

## 6. Localisation (India-first defaults)

- **Currency**: INR, symbol `₹`, Indian number grouping (`1,23,45,678`).
- **Timezone**: `Asia/Kolkata`.
- **Date**: `%d-%b-%Y`. **Datetime**: `%d-%b-%Y %I:%M %p`.
- **Tax**: 18% GST default.
- **Payment methods**: UPI / NEFT / RTGS / IMPS / Card / Cash / Cheque.

Every value is per-operator, editable from Settings.

---

## 7. Security posture

- Passwords hashed with Werkzeug (`pbkdf2:sha256`).
- Flask-Login session cookies (HTTPS-only in production, `SameSite=Lax`).
- CSRF via Flask-WTF on every form.
- **Rate limiting** — Flask-Limiter: login POST 10/min, 30/hr per IP; forgot-password 5/min, 20/hr.
- **Two-factor auth (TOTP)** — pyotp; QR provisioning; verify with 1-window clock drift tolerance.
- **`_safe_next()`** — blocks external redirects, non-absolute paths, and `/auth/logout`.
- **Audit log** — actor/IP/user-agent for every sensitive mutation; filterable + CSV export.
- **Auto-scoping** — defence in depth against cross-operator data leaks.

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
| Multi-operator | `678abbf` | Operator model, PLATFORM_OWNER, per-operator branding + localisation, `/platform/*` |
| Per-operator email | `b244015` | `UniqueConstraint(operator_id, email)` + partial index for platform owner |
| Phase 1 | `7abd4be` | Password reset + change UI + workspace picker + SMTP mail (SES-ready) |
| Phase 2 | `833c698` | Employee email invitations + company approval email + operator slug auto-fill + session hardening + day-pass QR + reception |
| Phase 3 | `5c7bba5` | 2FA (TOTP) + audit filters/CSV + capacity heatmap + PDF invoices + waitlist + recurring bookings |
| Phase 4 | `7284da9` | Guest passes, visitors, community directory, announcements, printing credits, support tickets, lockers, referrals |
| Phase 5 | `2c16af4` | Modern marketing landing + colourful theme + Inter font + role-based sign-in cards + feature grid |
| Phase 6 | `?` | Platform/operator terminology cleanup (seed no longer conflates them) + `PLATFORM_MANAGER` role with per-feature grants (`operators`/`billing`/`reports`) + platform Team/Billing/Reports pages + operator-initiated invites (`/admin/invites`) for individuals and companies |
| Phase 7 | `?` | Rebrand coworkhub.io → **hub1z.com** + platform-invites-operator flow (`TRIAL` → Approve) + `HOLD` operator status (Manager-shared, distinct from Owner-only Suspend) + `PricingTier` model with resource caps, enforced on location/seat/room creation, surfaced on Billing + fixed two pre-existing cross-operator bugs found in the process (see §5 note) |
| Phase 8 | `?` | Self-serve operator trial sign-up (`/auth/register/operator`, time-boxed, login blocked on expiry) + operator-invites-team-member flow (`/admin/invites/team/new` — Manager or Location Manager, the previously-missing piece for multi-location operators) + "seats = people" tier rule (`resource="person"` in `tier_limits.py`, capped at `max_seats`, enforced on every person-creation path) + seed data trimmed to exactly 3 accounts, clearly printed on `seed-demo` |
| Phase 9 | (this) | Moved company subscriptions from company self-checkout to operator-controlled (`/admin/companies/<id>/subscriptions/*`) — the old `/company/plans` self-serve subscribe was fully disconnected from actual seat inventory and bypassed every tier cap |

---

## 10. Roadmap (still open, low priority)

- **Custom-domain automation** — White Label gates new portal mappings; automated DNS/certificate provisioning remains deferred.
- **Pricing rollout** — stages 1-3 are live. Accounting Sync, API/Webhooks, GST E-Invoicing, Featured Listing, Razorpay, WhatsApp and live PAN/GSTIN checks remain Coming Soon.
- **All-Access cross-location booking** (mostly plumbed, needs UI polish).
- **Scheduled operations** — `flask run-scheduled-jobs` creates concrete recurring room bookings and runs idempotent monthly billing; production deployments should invoke it from cron/EventBridge/Azure Scheduler.
- **Read replicas** for report queries.
- **Mobile-app JWT API** (blueprint stub exists at `/api/v1`).

---

_Last updated: 2026-09-22._
