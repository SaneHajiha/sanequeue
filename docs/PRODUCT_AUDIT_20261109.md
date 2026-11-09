# SaneQueue product audit and execution tracker

Baseline: GitHub `master` at `e977516398db5b04309ddae11dffb3dbec4f09d9`, runtime version `2.1.0-beta.26`. The Phase 1 archive commit follows the published beta.26 installer evidence in [AUDIT_BETA26.md](AUDIT_BETA26.md). That evidence applies to its own tagged source. Independent clones preserve the existing development checkouts, including their dirty working trees.

## System map

| Boundary | Implementation and evidence |
| --- | --- |
| HTTP, presentation and legacy compatibility | `sanequeue/asgi.py` wraps Flask with Starlette. `demo_monitor.py` wires the runtime, accounts, state and modules. `qpanel/operations.py` serves the primary Jinja/vanilla JS app. `qpanel/app.py` retains legacy queue/statistics routes. |
| Monitoring | `sanequeue/realtime/collector.py` owns persistent AMI, initial synchronization, event ordering, reconciliation, and Redis publishing. `sanequeue/api/state.py` reads Redis with generation checks. `sanequeue/gateway/app.py` applies the allowed Origin and reuses Flask authorization on each WebSocket snapshot. |
| Authority and mutations | `sanequeue/security/`, `qpanel/queue_policies.py` and `qpanel/operations.py` provide account, menu and per-queue authorization. `sanequeue/actions/` implements action plans, delivery and outcome tracking. The root PBX adapter and FastAGI have separate authority from the HTTP layer. |
| Storage | Managed Redis is ephemeral. Runtime SQLite activity and calls have bounded retention. `sanequeue/reporting/` adds a separate CLI-operated, private SQLite WAL archive for immutable queue_log/CDR/CEL source versions with bounded readers and replay checkpoints. See [Phase 1](REPORTING_PHASE1.md). |
| Installation and release | `scripts/install.sh`, `scripts/provision.py` and `deploy/` manage versioned releases, separate AMI identities, isolated Redis and the inventory/adapter services. `.github/workflows/` runs the Linux matrix and packages tagged prereleases. |

## Baseline inventory

Verification here means the indicated local test or screen was exercised. Real-call coverage from older revisions is linked separately.

| Capability | Status on baseline | Source or evidence |
| --- | --- | --- |
| Dashboard, queues, waiting and active calls, agents, extension presence | Implemented; synthetic login and dashboard verified. Daily counters are defective without observation coverage. Active memberships and channel legs are distinct from unique calls. | `qpanel/operations.py`, `operations.js`, `test_realtime_engine.py`, `test_observed_calls.py` |
| PBX health, inventory, capabilities | Implemented with incomplete deployment evidence; endpoint classification requires site-specific contexts. | `sanequeue/realtime/local_inventory.py`, `test_local_inventory.py`, `docs/INSTALL.md` |
| Pause/resume, membership, listen, whisper, barge, transfer, parking and pickup | Implemented; action plans and authorization exercised by fixtures. Requires site-specific isolated call and audio acceptance. | `qpanel/operations.py`, `test_advanced_actions.py`, `test_action_ledger.py`, [prior pilot](AUDIT_BETA25.md) |
| Wallboard, alerts, queue policies, audit | Implemented with fixtures. Wallboard period label disagrees with its current default data period. | `operations.html`, `operations.js`, `test_alert_outbox.py`, `test_system_alerts.py` |
| Users/access, organization/service, profile, shift planning, directory | Implemented with account, session and permission coverage. Role-specific end-to-end navigation remains pending. | `demo_monitor.py`, `sanequeue/security/`, `qpanel/planning.py` |
| Telephone modules | Implemented for configured extension waiting, callback, prompts and number formatting. Acceptance depends on the installed dialplan and devices. | `sanequeue/pbx/`, `test_pbx_features.py`, [module guide](TELEPHONY_MODULES.en.md) |
| Observed agent activity, personal activity, call history | Implemented for the observed window. Recorder gaps and expired retention limit retrospective counts. | `sanequeue/api/activity.py`, `sanequeue/realtime/calls.py`, `test_beta23_activity.py` |
| Independent queue and PBX reporting areas, richer exports and recording access | Missing as a complete product on master. Archive CLI and legacy reports exist. Evaluate existing reporting and PBX unit branches for reuse before adding parallel implementations. | `sanequeue/reporting/__main__.py`, `qpanel/app.py`, `test_reporting_archive.py` |
| Call journey and transfer/hangup diagnostics | Implemented for observed event stages, incomplete for SIP/RTP causality. | `sanequeue/realtime/journeys.py`, `sanequeue/reporting/correlate.py`, `test_beta23_journey_directory.py` |
| One-way audio direction, missing trunk/IVR stages, complete occupancy and AHT | Unsupported when directional media, dialplan, duty, hold or wrap-up evidence is absent. | `sanequeue/realtime/calls.py`, [reporting research](REPORTING_RESEARCH.en.md) |

## Prioritized work

| Priority | Reproduction and impact | Cause and implementation gate |
| --- | --- | --- |
| P1 | Demo dashboard displays zero abandoned calls while “recording since” shows unknown. Wallboard shows totals under a mismatched period label. A supervisor may miss a recording outage. | Daily projection replaces absent observations with zero. Update daily coverage bounds and propagate unknown values to all period views. Check an abandon-only SLA and a mix with missing SLA thresholds. |
| P1 | Audit the browser-to-PBX, privileged adapter, credentials, file and reporting boundaries before expanding permissions or deploying. | Codex Security scan tracks source coverage independently. Resolve supported findings with bounded fixture reproductions. |
| P1 | Two reporting domains are incomplete in master. | Compare the published reporting line and `feature/pbx-reports-units` work before integrating. Preserve bounded ingestion, source coverage, scoping and export checks. |
| P2 | `VERSION`, Python and the release manifest say beta.26. Node metadata says beta.12. Both installers guides title beta.23 and download beta.24. | Align package metadata and current published install links. Gate future release packages against version drift. |
| P2 | Default narrow dashboard puts nav, header, help and filters ahead of the first KPI. The Persian view includes untranslated visual status text. | Compare with the existing visual foundation work before a broad redesign. Keep the 18 existing sections and their grants. Test all five role workflows, keyboard, filters, mobile/wallboard and both locales/themes. |
| P2 | Browser-session trend mixes samples from different filters if changed mid-session. | Partition the trend by selected queue scope, or reset it explicitly and label the source/window. Future historical trends should come from persisted observations. |
| Release gate | No new release candidate has passed Rocky 8 upgrade/rollback, mixed-role load or site telephone acceptance. | Use a disposable Issabel 5 / Rocky 8 / Asterisk 20 environment with state restoration and isolated SIP calls. Record actual evidence and package the exact verified commit. |

## Research and verification trail

- Existing vendor comparison and proposed historical boundaries are in [Reporting research](REPORTING_RESEARCH.en.md). The exact revisions and scope of existing branch work must be checked before implementation proceeds beyond master fixes.
- Fresh baseline command: `python -m pytest tests --ignore=tests/historical -p no:cacheprovider -q`. Result: 355 passed, 5 skipped, 104 subtests passed on Windows with Python 3.11.4. Historical test files are intentionally archived. Linux Redis jobs and real PBX acceptance require separate evidence.
- Fresh in-app browser observations: offline synthetic admin dashboard in Persian dark and English light, at narrow panel and English desktop widths. One desktop capture rendered partially blank through the native panel API, so it was replaced with the browser tab screenshot. The English interface still showed Persian synthetic labels in queue and agent names, which represent source values. The false zero is independently visible alongside the absent coverage timestamp.
- Release references: [published beta.26](https://github.com/SaneHajiha/sanequeue/releases/tag/v2.1.0-beta.26), [master source baseline](https://github.com/SaneHajiha/sanequeue/commit/e977516398db5b04309ddae11dffb3dbec4f09d9).
