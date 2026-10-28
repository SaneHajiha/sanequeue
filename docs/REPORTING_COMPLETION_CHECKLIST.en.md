# Reporting completion criteria

Updated 2026-10-28. This current checklist supersedes historical phase notes. Source lives on feature/reporting-phase2; master does not contain all development. Implemented code, exact-commit CI and accepted live behavior are distinct.

| Area | Implemented scope | Open acceptance/development |
|---|---|---|
| Queue analytics | Visits, answers, abandonment, explicit SLA denominator, ASA/percentiles, trends/heatmap | New phone scenarios and multiple PBX versions |
| Multi-queue agents | Unioned duty, pauses, queue segments, evidence-gated ACW/AHT/occupancy | Instrumentation where explicit ACW is absent; interactive large-month limits remain |
| Unanswered offers | RINGNOANSWER detail/groups/chart and bounded whole-range CSV | New deployment/phone acceptance; dedicated projection for large busy ranges |
| Call/audio | Evidence-based journey, independent play/download and request audit | Complex multi-hop ownership and source gaps |
| CDR/trunks | Actual origin/CID/DID/trunk, party/length/hour/weekday filters | Real external trunk and historical inventory evidence |
| Happy calls | Explicit work sessions, pause-call details/summary/audio | External trunk; declared sessions are not observed presence |
| Human quality | Versioned forms, weighted human scores and timed notes | Complete live UI/permission acceptance |
| Customer surveys | Forms/answers/CSAT and conservative optional adapter | Live hook, automatic consent-based voice capture |
| VIP/blocks | Temporal labels/SLA and operator source imports | Automatic historical source ingestion |
| Charts | Queue, agent, trunk, shifts, pauses, VIP; local SVG/PNG | Shared chart/calendar Chromium matrix passed; installed full-page acceptance and other browsers remain |
| Standard exports | Private pinned CSV/XLSX/PDF, current grants, schedules | Additional installation/recovery/resource acceptance |
| Builder | Selected columns/filters/groups, private definitions; exact pinned background CSV/XLSX and schedules | Installed acceptance; separate CDR builder dataset/custom PDF |
| Text/AI | Private ASR/search, opt-in loopback generative assistance | Persian accuracy and independently limited model service |
| Storage | No automatic deletion; archive-only backup/catalog/no-overwrite restore | Physical partitions, full installation/media/account recovery |

## Concrete remaining development and acceptance gaps

1. Exact builder background CSV/XLSX and schedules are implemented locally and tested. Install/recovery acceptance remains; independent CDR builder/custom PDF is still development.
2. Proven pre-queue Ring Group/Follow-Me intervals, separately from queue wait and without summing parallel legs.
3. Explicit abandoned-call follow-up action IDs with proven outbound outcomes; equal phone numbers alone are candidates, not proof.
4. Accepted automatic customer survey/voice capture with consent and a proven session; manual upload/optional hooks are not full intake.
5. Automatic historical status/block sources plus partition routing/full recovery. Missing historic facts cannot be reconstructed by guessing.

Every completed capability needs a panel path, permission, source, unit/denominator, unknown-data behavior, export contract and acceptance evidence. Universal competitor superiority is not a testable completion claim. The PR records exact-commit CI; no private credentials, audio or live databases belong in source control.

## 2026-10-28 bounded custom CSV update

Exact custom queue CSV now preserves column order/filters/grouping and a single archive snapshot, with current all-queue export/number permissions rechecked. Hard limits: 500 rows/groups, 4 MiB, 2-second reader, one slot per web process. Over-cap requests fail without partial exports. This paragraph describes the earlier immediate-CSV checkpoint. The later background export/schedule implementation is documented in REPORTING_CUSTOM_EXPORTS_AND_RANKINGS.en.md; the CDR builder dataset remains separate development. Callback history no longer auto-deletes after 30 days; pending expiry still prevents dialing.


2026-10-28 beta.27: installed pilot/API/calendar/charts and real CSV/XLSX/PDF downloads passed; see PILOT_BETA27.en.md. Private sealed-backup monthly agent aggregation now passed the full synthetic month (53.4s wall,13.3sCPU,~32MiB RSS at25%onecore). Current-permission background job/API integration remains development; interactive limits were not raised.
