# Pricing and Entitlement Manifest v1 Review

## 1. Draft Offers

Created on production by `flask --app wsgi.py seed-entitlement-drafts`. A second invocation returned the same IDs and verified the saved terms/grants.

| Offer key | Version | ID | State | Public |
|---|---:|---:|---|---|
| `starter_v2` | 1 | 1 | draft | no |
| `growth_v2` | 1 | 2 | draft | no |
| `scale_v1` | 1 | 3 | draft | no |
| `enterprise_v1` | 1 | 4 | draft | no |
| `extra_storage_v1` | 1 | 5 | draft | no |
| `white_label_v1` | 1 | 6 | draft | no |
| `virtual_office_v1` | 1 | 7 | draft, held | no |
| `assisted_onboarding_v1` | 1 | 8 | draft, service workflow absent | no |

Production verification: 8 entitlement offer versions; 0 tenant plan bindings; all versions are `draft` and `publicly_listed=false`. No public `PricingTier` records were created or changed by this command. Two legacy rows are marked public, but `PlatformProfile.pricing_page_public=false` keeps the live pricing page hidden. No prices were published.

A fresh database backup was taken before deployment at `~/hub1z-pre-manifest-drafts-20261006-061702.sql.gz`.

## 2. Capability Codes

“Existing” means the key was already in the application catalog/registry before this manifest. “Added” means the key was registered by this implementation; it does not imply a new route gate or customer access change.

| Manifest capability | Entitlement key | Status / notes |
|---|---|---|
| Bookings | `bookings` | Existing, built |
| Calendar | `calendar` | Existing, built |
| Meeting-room credits | `meeting_credits` | Existing, built |
| GST invoices | `gst_invoices` | Existing, built; not IRN e-invoicing |
| PDF documents | `pdf_documents` | Existing, built |
| Manual UPI payments | `upi_payments` | Existing, built |
| Static location QR | `location_qr_checkin` | Existing, built |
| Manual attendance | `manual_attendance` | Added, mapped to shipped manual attendance route |
| Member PWA | `member_app` | Existing, built; not native apps |
| Parcels | `parcels` | Existing, built |
| In-app alerts | `inapp_alerts` | Existing, built |
| Leads | `leads` | Existing, built |
| Lead email notifications | `lead_email_alerts` | Existing, built |
| Basic reports | `basic_reports` | Existing, built |
| People/company/member administration | `people_admin` | Added, registry key only; no new route gate |
| Announcements | `announcements` | Added, registry key only |
| Community directory | `community_directory` | Added, registry key only |
| Support tickets | `support_tickets` | Added, registry key only |
| Payment reminders | `payment_reminders` | Existing, built; included in drafts, still marked PO-confirmation required |
| Audit capture | `audit_capture` | Added to catalog; capture is already implemented as core behavior |
| Audit viewer | `audit_viewer` | Added, maps to shipped viewer; no commercial gate added |
| Payroll | `payroll` | Existing, built |
| Expenses | `expenses` | Existing, built |
| Attendance history | `attendance_reports` | Existing, built; report clamps history to seven days when absent |
| Attendance CSV | `attendance_export` | Existing, built; current export does not apply the report history clamp |
| Rotating reception QR | `rotating_qr_screen` | Existing, built |
| Advanced people analytics | `people_analytics` | Added, shipped report surface; draft key is not yet wired to a distinct route gate |
| Booking heatmap | `booking_heatmap` | Added, shipped report surface; draft key is not yet wired to a distinct route gate |
| Alert digests | `alert_digests` | Existing, built |
| Lead export | `lead_export` | Existing, built; included in drafts, still marked PO-confirmation required |
| Audit export | `audit_export` | Existing, built |
| White-label web/PWA | `white_label` | Existing, partially built; same key is used for Scale and add-on drafts |
| Same-operator multi-location reports | `network_reports` | Added, based on existing operator-scoped reports; not independently gated today |
| E-invoicing future inclusion | `gst_einvoicing` | Existing, unbuilt; referenced only in Scale metadata, never granted |
| API/webhooks future inclusion | `api_webhooks` | Existing, unbuilt product; referenced only in Scale metadata, never granted |
| Authentication core (`auth`) | `authentication` | Existing registry key; `auth` is the manifest alias |
| Tenant isolation | `tenant_isolation` | Existing protected registry key |
| Two-factor authentication | `two_factor` | Added protected registry key; metadata only |
| Password reset | `password_reset` | Added protected registry key; metadata only |
| Financial settlement/history | `financial_settlement_and_history` | Added protected registry key |
| Billing recovery | `billing_recovery` | Added protected registry key |

`advanced_reports` remains as the legacy combined catalog code; new drafts use `people_analytics` and `booking_heatmap`. The new report keys are configuration only until service/route enforcement is migrated and shadow parity is reviewed.

## 3. Section 6 Prerequisites

| Item | Size | Files / work |
|---|---|---|
| Exclude VO subscriptions from prospective seat gauge without rewriting old snapshots/invoices | M | `app/services/platform_pricing.py`, `app/services/operator_billing.py`; add meter revision and regression tests |
| Active distinct VO-party gauge and gate subscriptions to existing VO plans | L | `app/services/platform_pricing.py`, `app/blueprints/admin/subscription_routes.py`, `app/services/operator_billing.py`, entitlement definitions, lifecycle tests; requires approved legal-party semantics |
| Remove `all_features` from new quota resolution paths | M/L | `app/services/entitlements.py`, `app/services/operator_quotas.py`, `app/services/operator_billing.py`, `app/services/storage.py`; new offers already use explicit finite/unlimited meter grants |
| Apply identical attendance history window to CSV | S | `app/blueprints/admin/attendance_routes.py`, `tests/test_attendance.py` |
| Decide retained-data reads for expenses, salary, and generic document downloads | M | `app/blueprints/admin/report_routes.py`, `app/blueprints/admin/staff_routes.py`, document download routes; preserve existing reads by default, gate new writes/exports after approval |
| Add tenant-scoped checks to jobs and five session API endpoints | L | `app/services/booking_service.py`, `app/services/billing_service.py`, `app/services/credit_service.py`, `app/services/notifications.py`, `app/blueprints/api/routes.py`; tenant-by-tenant failure isolation and owner tests required |
| Validate referenced user/location ownership in guest, visitor, printing, and locker writers | M | `app/blueprints/community/routes.py`, related models/services and isolation tests |
| Apply scheduled downgrades only at their effective date | M | `app/services/entitlements.py`, `app/services/operator_quotas.py`, `app/services/operator_billing.py` and period-boundary tests |

None of these prerequisites were implemented as part of draft creation, so current customer behavior is unchanged.

## 4. Built-Capability Gaps

- White Label is partial: custom-domain DNS/certificate automation is incomplete, the domain continues resolving after expiry, and email branding is not fully removed. The draft records these caveats and the proposed notified transition policy.
- Network reporting exists only through current operator-scoped reports; it is not a separately enforced product capability yet.
- People analytics and booking heatmap are shipped surfaces but still share the legacy `advanced_reports` entitlement in route middleware.
- Assisted onboarding has no standalone order/fulfillment workflow. Its offer is a draft service record only.
- VO client billing is deliberately held; no active-client gauge exists and current seat metering includes VO contract quantities.
- E-invoicing, external API/webhooks, multi-GSTIN, WhatsApp transport, native apps, SSO, sandbox, franchise tenancy, SLA fulfillment, and other section 7 products remain unbuilt and receive no offer grants.

## 5. Conflicts and Decisions

- The current seat counter includes active Virtual Office subscription quantities, contrary to the proposed no-double-count rule.
- The attendance CSV query does not share the seven-day history clamp.
- Current staff quotas count stored staff-role user rows, including deactivated/pending rows; the proposed active-plus-pending/exclude-deactivated rule is not implemented and remains **[CONFIRM]**.
- Existing scheduled downgrade terms can tighten quotas before renewal; the proposed effective-date behavior remains unimplemented.
- The old `all_features` flag still bypasses some legacy quota paths. New draft offers do not use it.
- The legacy public tier path is separate from entitlement offer versions and still hard-excludes the `scale` key. Draft offer versions are not consumed by public pricing.
- Current `payment_reminders` is already a feature code; moving it to the base tier is represented in drafts only and remains **[CONFIRM]**.
- Current `advanced_reports` is combined; new split keys are not wired to route gates pending incremental migration.
- Current `public_catalog` previously included unbuilt add-ons in sellable lists when pricing was public. It now omits unbuilt items from add-on/usage groups and displays only names in a single Coming Soon block when `pricing_page_public` is enabled. Production pricing remains disabled.
- White Label price/scope, trial eligibility, seven-day grace, staff counting, VO scope, same-operator report semantics, and 12-month grandfathering/legacy-trial transitions remain **[CONFIRM]**. Draft snapshots store these as pending decisions; no customers are affected.

## 6. Deployment and Verification

- Commit: `01dce6d` (`feat: seed pricing manifest as drafts`), pushed to `main` and deployed to the VM.
- Production database migration remains `fc72b8d19a04`; no schema migration was needed for these offer rows.
- `ENTITLEMENTS_SHADOW_ENABLED=false` and `ENTITLEMENTS_ENFORCEMENT_ENABLED=false` in production.
- `PlatformProfile.pricing_page_public=false`; `https://hub1z.com/pricing` displays the hidden-pricing state; `/healthz` returns 200.
- No tenant plan bindings were created; no draft is published or publicly listed.
- Focused tests: `tests/test_entitlement_manifest.py` 4 passed; `tests/test_entitlement_foundation.py` 7 passed; `tests/test_pricing_catalog.py` 12 passed.
