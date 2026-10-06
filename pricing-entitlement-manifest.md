# Hub1z Pricing and Entitlement Manifest v1

Date: 2026-10-05
Audience: the engineering agent (Copilot) working in the Hub1z repo.
Status: product-owner recommendation. Items marked **[CONFIRM]** need the owner's approval before they affect any customer.

## 0. How to use this document

1. This is a specification. Do not change customer access, prices, tenant bindings or public pricing as a result of reading it.
2. Create the offers below as **draft** (unpublished) offer versions using the entitlement foundation already built. Do not create tenant bindings. Keep shadow comparison and enforcement flags **off**.
3. Use existing catalog codes wherever they exist (listed in section 4). Where a code is missing, propose one and flag it.
4. Never advertise or sell anything in section 7 (not built). The pricing page may render only built capabilities.
5. When done, report back using the checklist in section 9.

Source analysis: `feature-entitlement-inventory.md` (99 capability rows). Seats and locations are metered already and are only referenced here for prices and limits.

---

## 1. Price ladder (INR per month, excluding 18% GST)

| Tier | Included locations | Included seats | Price | Per seat | Extra seat | Extra location | Max locations on tier |
|---|---|---|---|---|---|---|---|
| **Starter** | 1 | 50 | **2,999** | 60 | 55 | not available (upgrade) | 1 |
| **Growth** | 3 | 150 | **7,999** | 53 | 49 | 1,999 | 6 |
| **Scale** (early access) | 8 | 400 | **19,999** | 50 | 45 | 1,499 | 15 |
| **Enterprise** | 15 | 1,000 | **from 44,999** (contact) | 45 | 35 | 999 | custom |

- **Annual billing:** 2 months free, i.e. 10 x monthly. Starter 29,990, Growth 79,990, Scale 199,990 per year. Equivalent to 2,499 / 6,666 / 16,666 per month.
- **Overage never beats the next tier** (verified):
  - Starter at 150 seats = 2,999 + 100 x 55 = 8,499, more than Growth at 7,999.
  - Growth at 400 seats = 7,999 + 250 x 49 = 20,249, more than Scale at 19,999.
  - Scale at 1,000 seats = 19,999 + 600 x 45 = 46,999, more than Enterprise at 44,999.
- **Seat grace (soft threshold):** floor(1.10 x allowance), i.e. Starter 50 to 55, Growth 150 to 165, Scale 400 to 440, Enterprise 1,000 to 1,100. Grace lasts up to 7 days **[CONFIRM]**. Never switch off a live centre.
- **Locations get no percentage grace.** A second location is never authorised by rounding.
- **Check before publishing:** gross margin at 2,999. Variable costs are support time, storage and email.

### Allowances per tier

| Item | Starter | Growth | Scale | Enterprise |
|---|---|---|---|---|
| Staff accounts | 3 | unlimited | unlimited | unlimited |
| Document storage | 5 GB | 25 GB | 100 GB | custom |
| Open manual leads | 250 | unlimited | unlimited | unlimited |

- Unlimited must be an **explicit value on each meter**. Never infer it from a feature bundle (the legacy `all_features` flag conflates the two and must not be used for new offers).
- **Staff counting policy [CONFIRM]:** count active staff accounts plus pending staff invitations. Exclude deactivated accounts. The current code counts stored role rows, including inactive, so this needs a small change.

---

## 2. Positioning against the market (for the pricing page copy)

At 100 seats Starter costs 2,999 + 50 x 55 = **5,749**. DeskOS Basic is 7,999 for the same size. Archie and Nexudus are roughly 18,500 to 18,700 at 100 seats. Cobot is roughly 46,000. Do not claim feature parity with any competitor beyond what is built.

---

## 3. Corrections to earlier proposals (do not implement the earlier versions)

| Earlier idea | Finding | Decision |
|---|---|---|
| WhatsApp utility messages included in every tier | No WhatsApp transport exists, only click-to-chat links | Remove |
| Accounting sync in Growth | Coming Soon, not built | Roadmap only |
| Razorpay, e-invoicing as add-ons | Not built. Invoicing supports one seller GSTIN | Roadmap only |
| API and webhooks in Scale | Only 5 session-authenticated booking endpoints exist | Roadmap only |
| "White-label app" | Product is a branded PWA, not a native app | Say "white-label web portal / PWA" |
| Franchise/sub-tenant, SSO, sandbox, SLA in Enterprise | None exist | Enterprise stays custom, no published feature list |
| Per-VO-client billing | VO clients are also counted as seats (double counting) | Fix seat counter first (section 6) |

---

## 4. Capability manifest

Legend: `S` Starter, `G` Growth, `Sc` Scale, `E` Enterprise. "Core" means never removed by a commercial change.

### 4a. Included in every tier (Starter and above)

| Capability / catalog code | Notes |
|---|---|
| `bookings`, `calendar`, meeting-room credits | Existing obligations (history, cancel, check-in) stay accessible if new sales are ever disabled |
| `gst_invoices`, `pdf_documents` | GST split and PDFs. Not IRN e-invoicing |
| `upi_payments` | Manual QR and confirmation. Not a gateway |
| Static location QR check-in, manual attendance entry | Basic check-in stays in Starter |
| `member_app` (installable PWA) | |
| `parcels`, `inapp_alerts` | |
| `leads`, `lead_email_alerts` | Manual open leads capped at 250 on Starter |
| `basic_reports` | |
| People, company and member administration, announcements, directory, support tickets | |
| **`payment_reminders`** (overdue payment reminder emails) | **Moved down from Growth.** Collections is the core value and the cost is email only **[CONFIRM]** |
| Audit capture and audit viewer | Core. Viewer stays available. Only the CSV export is premium |

### 4b. Growth and above

| Capability / catalog code | Tier |
|---|---|
| `payroll`, `expenses` | G+ |
| `attendance_reports` (history beyond 7 days) and `attendance_export` (CSV) | G+. Both must obey the same history window (see section 6) |
| `rotating_qr_screen` | G+ |
| `advanced_reports` (people analytics, booking heatmap) | G+. Split into separate keys if possible |
| `alert_digests` | G+ |
| `lead_export` | G+ **[CONFIRM]** |
| `audit_export` | G+ |
| Unlimited staff accounts, 25 GB storage | G+ |
| Up to 6 locations, extra locations at 1,999 | G |

### 4c. Scale (early access) and above

| Capability | Notes |
|---|---|
| 8 locations / 400 seats, 100 GB storage | Capacity |
| White-label web portal / PWA with custom domain and "Powered by" removal | Same benefit key as the White Label add-on (section 5). Tier-included and purchased must resolve identically |
| Network reports across the operator's own locations | Same operator only. Not franchise or cross-operator |
| E-invoicing, API and webhooks | **Included at no extra cost when they ship.** Do not list as available now |

### 4d. Enterprise

15 locations / 1,000 seats. Everything else (SSO, sandbox, franchise management, SLA) is a scoped conversation and not published as a feature.

### 4e. Suggested machine-readable form

```yaml
offers:
  starter_v2:    {price_inr_month: 2999,  seats: 50,   locations: 1,  staff: 3,         storage_gb: 5,   open_leads: 250,  extra_seat: 55, extra_location: null, max_locations: 1,  status: draft}
  growth_v2:     {price_inr_month: 7999,  seats: 150,  locations: 3,  staff: unlimited, storage_gb: 25,  open_leads: unlimited, extra_seat: 49, extra_location: 1999, max_locations: 6,  status: draft}
  scale_v1:      {price_inr_month: 19999, seats: 400,  locations: 8,  staff: unlimited, storage_gb: 100, open_leads: unlimited, extra_seat: 45, extra_location: 1499, max_locations: 15, status: draft, label: early_access}
  enterprise_v1: {price_inr_month_from: 44999, seats: 1000, locations: 15, staff: unlimited, extra_seat: 35, extra_location: 999, status: draft, sales: contact}
grants:
  all_tiers:   [bookings, calendar, gst_invoices, pdf_documents, upi_payments, member_app, parcels, inapp_alerts, leads, lead_email_alerts, basic_reports, payment_reminders]
  growth_plus: [payroll, expenses, attendance_reports, attendance_export, rotating_qr_screen, advanced_reports, alert_digests, lead_export, audit_export]
  scale_plus:  [white_label]
protected_core: [auth, tenant_isolation, two_factor, password_reset, audit_capture, financial_settlement_and_history, billing_recovery]
```

---

## 5. Add-ons (any paid tier; never during trial)

The existing add-on purchase check already requires an active paid base subscription, a built and available module, a positive price and quantity from 1 to 100. Keep that rule.

| Add-on | Price (INR/month unless stated) | Status | Rule |
|---|---|---|---|
| Extra storage | **149 per 5 GB unit** (existing unit) | Sellable now | Blocks new uploads over the allowance only. Downloads and deletes always work. No auto-purge |
| White Label (web/PWA, custom domain) | **2,499** | Sellable now, with caveats below | Same key as Scale inclusion. A Scale customer never buys it again. Included in Scale |
| Virtual Office & NOC | **1,499 including 25 active VO clients, then 39 per extra client** | **Hold until VO gauge fixed** (section 6) | Unit = distinct active legal party with a VO agreement, per operator |
| Assisted onboarding | **4,999 one-time per location (2,499 per extra location)**, free with annual Growth and above | Service order, not a feature unlock | Needs a standalone order and fulfilment workflow before selling |

- White Label price is **lower than my earlier 4,999 proposal** because only web/PWA/domain branding exists, not a native app **[CONFIRM]**.
- White Label scope caveat: DNS and certificate automation is incomplete, an existing custom domain keeps resolving after expiry, and the email footer is not fully white-labelled. Define the continuity policy: after expiry, keep the domain resolving for a notified transition period and remove premium branding.
- Do not charge existing customers for the basic logo/colours/microsite they already have. A premium **Branded Web Portal** add-on is on hold until its scope beyond existing branding is defined.

---

## 6. Prerequisites before selling or enforcing

1. **Seat double counting.** `active_contracted_seats()` sums all active subscription quantities, including virtual-office contracts. Stop counting VO clients as seats prospectively, with a new meter revision. Do not rewrite historical invoices.
2. **VO active-client gauge.** Add a gauge of distinct active VO parties. Also gate subscribing to an existing VO plan. Today only plan create/edit and the NOC letter are gated.
3. **Independent grants.** Boolean features and numeric limits must be separate grants. `all_features` must not make Enterprise-style caps unlimited.
4. **Attendance coherence.** The CSV export currently ignores the 7-day report clamp. Apply the same history policy to both.
5. **Shared-reader leaks to decide:** financial reports still read expense data when expenses are off. Staff detail can show salary data when payroll is off. Generic document downloads outlive the feature that produced them. Decide per case and document it. Default: existing data stays readable, new writes and exports are gated.
6. **Jobs and API.** Recurring booking creation, monthly invoicing, credit cycles, notifications and the 5 `/api/v1` booking endpoints have no commercial check. Add explicit checks per tenant, with failure isolation per tenant.
7. **Foreign-ID risk.** Guest, visitor, printing and locker writers accept referenced user/location IDs without confirming same-operator ownership. Close this before adding new meters.
8. **Downgrade timing.** Scheduled downgrades currently tighten limits before the old paid term ends. Apply new limits only at the effective date.

---

## 7. Not built: do not sell, advertise, or list as included

Accounting sync, API keys and webhooks, GST e-invoicing, multi-GSTIN billing, Featured listing, Online payments (Razorpay), WhatsApp message packs, PAN verification, GSTIN verification, e-sign provider signatures, native iOS/Android app, premium Branded Web Portal, franchise/sub-tenant management, SSO, customer sandbox, SLA, automatic waitlist notifications, referral reward automation.

Rules for the pricing page: render only built capabilities. A "Coming soon" block is allowed only if the existing hidden-pricing setting permits it. Never put an unbuilt item in a tier's included list.

Roadmap pricing notes (do not publish, do not configure):
- E-invoicing needs a multi-GSTIN model first. Price the registration license separately from per-IRN provider events.
- Meta WhatsApp rates in India (reference, excluding 18% GST): about 0.115 per utility or authentication message and about 0.8631 per marketing message. Add provider fees before pricing.
- PAN/GSTIN verification supplier costs are unknown.
- Razorpay: earn from the partner commission instead of charging a platform fee.

---

## 8. Decisions

| # | Decision | Recommendation | Status |
|---|---|---|---|
| 1 | Tier and action manifest | Section 4 | **[CONFIRM]** |
| 2 | Add-ons on trial | Paid tiers only. New trials: 14 days, full Growth features, no cost-bearing add-ons | **[CONFIRM]** |
| 3 | Grace and quota rules | 7 days, floor(1.10 x allowance), no percentage grace on locations, never stop a live centre | **[CONFIRM]** |
| 4 | Staff counting | Active plus pending invitations, exclude deactivated | **[CONFIRM]** |
| 5 | VO billing scope | Distinct active legal party per operator, never also counted as a seat | **[CONFIRM]** |
| 6 | White-label scope | Web/PWA/custom domain only. Call it exactly that | **[CONFIRM]** |
| 7 | Gateway/provider fees and retries | No tariffs set until contracts. Retries share one idempotency key and never bill twice | Deferred until providers exist |
| 8 | "Network reporting" meaning | Same operator's own locations only | **[CONFIRM]** |
| 9 | Enterprise SSO/sandbox/SLA | Out of scope. Scope per customer | Deferred |
| 10 | Grandfathering | Existing customers keep current price and features 12 months after new prices go live. Old 200-seat Growth keeps 200. Legacy expired trials: 30 days' notice, then Starter limits with data intact | **[CONFIRM]** |

---

## 9. What to report back

1. Draft offer versions created (names and ids) and proof that nothing is published and no tenant bindings exist.
2. A table of every capability code used in section 4, flagged where the code did not exist (with your proposed name).
3. Code changes needed for each item in section 6, with size S/M/L and the files involved.
4. Any capability in sections 4a to 4d that is not actually built, as a gap list.
5. Anything in this document that conflicts with what the code does.
6. Confirmation that shadow and enforcement flags remain off in production.
