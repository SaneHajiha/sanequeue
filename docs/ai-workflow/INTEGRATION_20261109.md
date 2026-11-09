# Reporting, operations and accessible UX integration

This tracker continues the first audit. Its starting comparison is limited to changes since the audited master and to the code that will enter the integration branch.

## Source inventory

| Source | Verified head | Relationship and disposition |
| --- | --- | --- |
| GitHub master | `e977516398db5b04309ddae11dffb3dbec4f09d9` | Common ancestor, beta.26 with Phase 1 archive. |
| Local audit | `169541bea7b77c1567d644ddaa2682aa98ba48e1` | Eight master-based commits. Reconcile behavioral fixes with beta.27 services, reports and UI. |
| PR #14 and local `feature/reporting-phase2` | `20a0e846ac621f87892cf55005699e28132d1836` | Same commit. 117 master-descendant commits already included in the PBX reporting base. |
| PR #15 | `3946fb8a32a929260f2cc1d1ad1eeec0f694eeb9` | Eight master-based commits. Overlay stylesheet, permissioned navigation and SVG icons, test contracts and design research. |
| Local `feature/pbx-reports-units` | `c7bbc5bb0040df1e4e7541b679c4550a057e3822` | 44 additional commits after PR #14, with two unstaged workflow documents retained in original checkout. |
| GitHub `feature/pbx-reports-units` | `f1fec145f614fa779068a887e56610933459850f` | Published equivalent of the committed local reporting work. Both tree IDs are `9d2bca44a62be5c6536e9288f9ba72226df9ee37`. This is the integration base and avoids duplicating equivalent history. |
| GitHub `feature/pbx-call-report-redesign` | `ba92e9bb9bf2508c9ba08373ac5c9cdbee43dc6f` | Parallel November 3 pilot branch. Compare its presentation and export changes with the newer PBX reporting base before taking any delta. |

Original checkouts remain available at `C:/Users/SaNe/Documents/Codex/2026-11-09/x20/work/sanequeue-remediation` and `C:/Users/SaNe/Documents/Codex/2026-10-22/new-chat-3/work/{review-20261024,sanequeue-pbx-reporting}`. The latter two have user-owned work. The PBX checkout has changes in `docs/ai-workflow/DECISIONS.md` and `TEST_RESULTS.md` recording an earlier preview. The older review checkout has 37 staged paths, 54 unstaged paths and 275 untracked paths from a different base. Do not bulk-import its working tree, including any test data, state and credentials.

## Feature and conflict matrix

| Surface | Master and local audit | PR #14 and PBX reporting base | PR #15 | Integration decision and remaining verification |
| --- | --- | --- | --- | --- |
| HTTP, Redis and WS | Persistent AMI collector and scoped live projection. Audit fixes unavailable KPIs and search/filter scope. | Retains collector and gateway, adds independently managed reporting worker and diagnostics. | Existing runtime contracts retained. | Preserve beta.27 lifecycle; port observed metric and trend behavior. Verify stale, reconnect, scope and overload. |
| Navigation, views, localization | 18 operational entries; audit compacts mobile header and search. | Additional reporting links, conditional admin routes and separate report navigation. | Accessible CSS, grouped permissioned menus, SVG icons. | Conflict in `operations.html` and menu tests. Apply groups and assets to the beta.27 menu while retaining report links, role guards and data-view contracts. |
| Queue and agent analytics | Observed activity and optional legacy queue report. | Durable visit/agent analytics, waiting distribution, SLA/ASA, shifts, ring attempts, outcomes, saved reports and exports. Unit queue drill-down extends the base. | UX and information architecture specification. | Keep archive/API/worker as primary implementation, retain legacy contracts. Verify queue and unit scope, calendar, pagination and historical assignment. |
| PBX call reporting | Phase 1 raw CDR/CEL import only; audit sets Tehran dates on legacy route. | Inbound/outbound/internal CDR, filters and time buckets, extension/trunk evidence, classifications, recordings, CDR exports and unit scopes. | Reporting roadmap and competitor comparison. | Verify CDR grouping and CEL evidence, filter/share state, role-safe exports and both halves of internal calls. Full path and media causality depend on available evidence. |
| Report access | Account/menu/queue grants; audit fixes directory dial, canonical queue and profile extension assignment. | Report/export/recording rights, historical unit assignments, bearer scopes, logged access and optional AI. | Preserves 18 beta.26 menu permission wrappers. | Recheck independent ACLs at HTTP, jobs, downloads, audio and token routes. Preserve draft/feature flags. |
| Security and failure recovery | Session-CSRF, bounded control audit and installer backup preconditions added in audit branch. | Installer/runtime/state paths and rollback behavior expanded for reporting. | Design contracts only. | Reconcile installer, tests and docs rather than replacing them. Complete active transport and session risks before release. |
| Release and QA | Audited beta.26, Windows/synthetic Chromium evidence. | Beta.27 workflow, tests and service validation material. | Static accessible-navigation contract tests. | Retain and run both suites. Stage release only after Linux, installation and live-call gates. |

## Acceptance tracker

- Complete — fetch exact master and PR refs, confirm the committed PBX tree match, and preserve the original working trees.
- Complete — SSH read-only environment check on `192.168.2.2` using the existing trusted host-key record. Issabel system package 5.0.0-5, Rocky 8.10, Asterisk 20.12.0. Asterisk, SaneQueue, collector, Redis and reporting service active. Both HTTP login URLs returned 200. Main source path identified as beta.27 `e096928b4ba7`; this is deployed baseline evidence.
- In progress — merge design and audit changes into the published PBX reporting base. Record conflict resolutions and tests here.
- Pending — compare the remaining parallel report design deltas, audit changes in older dirty source, verify both domains and monitor roles, and run browser visual/accessibility matrices.
- Pending — verify release artifacts, dependencies, Debian-independent Rocky installation assumptions, safe upgrade and restore on an isolated lab installation. Active production calls and dialplans are outside these tests.
