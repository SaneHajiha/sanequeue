# Reporting completion criteria

Updated 2026-10-28. This current checklist supersedes historical phase notes. Source lives on feature/reporting-phase2; master does not contain all development. Implemented code, exact-commit CI and accepted live behavior are distinct.

| Area | Implemented scope | Open acceptance/development |
|---|---|---|
| Queue analytics | Visits, answers, abandonment, explicit SLA denominator, ASA/percentiles, trends/heatmap | New phone scenarios and multiple PBX versions |
| Multi-queue agents | Unioned duty, pauses, queue segments, evidence-gated ACW/AHT/occupancy | Instrumentation where explicit ACW is absent |
| Unanswered offers | RINGNOANSWER detail/groups/chart and bounded whole-range CSV | New deployment/phone acceptance; dedicated projection for large busy ranges |
| Call/audio | Evidence-based journey, independent play/download and request audit | Complex multi-hop ownership and source gaps |
| CDR/trunks | Actual origin/CID/DID/trunk, party/length/hour/weekday filters | Real external trunk and historical inventory evidence |
| Happy calls | Explicit work sessions, pause-call details/summary/audio | External trunk; declared sessions are not observed presence |
| Human quality | Versioned forms, weighted human scores and timed notes | Complete live UI/permission acceptance |
| Customer surveys | Forms/answers/CSAT and conservative optional adapter | Live hook, automatic consent-based voice capture |
| VIP/blocks | Temporal labels/SLA and operator source imports | Automatic historical source ingestion |
| Charts | Queue, agent, trunk, shifts, pauses, VIP; local SVG/PNG | Full light/dark/mobile and real-browser PNG acceptance |
| Standard exports | Private pinned CSV/XLSX/PDF, current grants, schedules | Additional installation/recovery/resource acceptance |
| Builder | Selected columns/filters/groups, private versioned queue-visit definitions | Matching custom-layout exports/schedules; separate CDR dataset |
| Text/AI | Private ASR/search, opt-in loopback generative assistance | Persian accuracy and independently limited model service |
| Storage | No automatic deletion; archive-only backup/catalog/no-overwrite restore | Physical partitions, full installation/media/account recovery |

## Five concrete remaining development gaps

1. Export/schedule the exact builder definition using immutable versions, current grants and consistent aggregates.
2. Proven pre-queue Ring Group/Follow-Me intervals, separately from queue wait and without summing parallel legs.
3. Explicit abandoned-call follow-up action IDs with proven outbound outcomes; equal phone numbers alone are candidates, not proof.
4. Accepted automatic customer survey/voice capture with consent and a proven session; manual upload/optional hooks are not full intake.
5. Automatic historical status/block sources plus partition routing/full recovery. Missing historic facts cannot be reconstructed by guessing.

Every completed capability needs a panel path, permission, source, unit/denominator, unknown-data behavior, export contract and acceptance evidence. Universal competitor superiority is not a testable completion claim. The PR records exact-commit CI; no private credentials, audio or live databases belong in source control.
