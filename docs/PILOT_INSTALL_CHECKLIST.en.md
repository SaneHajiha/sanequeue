# Pilot installation and acceptance checklist

Code reviewed: 2026-10-28. This is not installation authorization or certification of every PBX version. This audit was read-only: no installation, restore or PBX change was executed. [فارسی](PILOT_INSTALL_CHECKLIST.fa.md).

## Before publication and installation

- [ ] Record the exact source SHA, branch, version, tag and checks for that SHA. Align bootstrap defaults and both installation guides. Installing an old tag does not install development-branch changes.
- [ ] Build public artifacts from tracked public files; inspect ZIP/tar and SHA256SUMS. Exclude credentials, databases, customer audio, local configuration and private screenshots. A checksum is not an independent publisher signature.
- [ ] Inventory OS, Asterisk version, SIP drivers, systemd, Python, functioning package repositories, local AMI and free space for release, virtual environment and a complete backup. Confirm site origin, TLS/proxy and firewall.
- [ ] Make a private recoverable backup of services, accounts/grants, application configuration, historical/media data and managed PBX files. Test restore on an isolated copy. Restoring an old database can discard newer facts.
- [ ] Apply/restore telephone files only in the site's approved window after checking active calls. Stopping this module's FastAGI is not proof of zero impact on a call currently using that menu.

## Concrete installer gates

| Gate | Code evidence | Closure requirement |
|---|---|---|
| Release identity | `install.sh` defaults to beta.26; current INSTALL.md title says beta.23 and its bootstrap URL uses beta.24 | One exact release/SHA across script, manifest and guides |
| Reporting acceptance | Provisioner checks collector health and `/login` | Verify importer, source coverage, projection/watermark and an authorized export; login HTTP 200 does not validate reports |
| CDR/CEL sources | SQL arguments are enabled only when an existing `reporting-sql.ini` is present | Validate a read-only account and actual tables/columns/coverage; missing evidence remains unavailable |
| Telephone rollback | Provisioner starts PBX apply; its error path restores manager files, units, application etc/state and source | Inject failure after PBX apply on a test copy and prove rollback of those exact telephone changes |
| AMI marker ambiguity | `manager_block` replaces marked blocks by regex | Reject malformed/duplicate/ambiguous markers before writing; preserve unrelated accounts |
| Large archive upgrade | `Archive.initialize` may build a new index under installer initialization timeout | Measure elapsed time, IO and disk on realistic history; define maintenance window and safe failure |
| Fresh callback integration | Unknown macro signatures fail with `unsupported_dial_one_adapter` | Inspect the target's exact dialplan signature and test phones; do not claim generic macro support |

Gates remain open until fixed or explicitly managed with evidence. These are rollout/recovery requirements, not claims of a proven critical exploit.

## After installation

1. Record the running release path/version and services. Log in with the password chosen during installation; there is no default administrator password. Separately test Viewer, Agent, Supervisor and denied accounts.
2. Reconcile queues/endpoints, answered and abandoned calls, multi-queue agents, transfers and hangup evidence against actual sources. Unknown durations/counts must not become zero. Reconcile exports with identical filters, grants and snapshots.
3. Verify KPI source/period, SLA denominator, unanswered offers, audio play/download and Persian/Gregorian dates in the integrated panel. Keep synthetic validation data outside real history.
4. Inspect `sudo sanequeuectl status`. Exercise disable/enable and data-retaining uninstall according to verified guidance, first on a disposable copy. Service removal is not a data purge. Configuration-file presence alone does not establish safe AI reactivation policy.
5. Measure CPU/RSS/IO, WAL, disk, importer lag, AMI connections and call quality before/during/after. AI remains off by default; model load and Persian accuracy require separate acceptance.

## Development not replaced by acceptance tests

Reconcile the current [completion checklist](REPORTING_COMPLETION_CHECKLIST.en.md): monthly agent-duty/rank aggregation above interactive caps; separate CDR builder dataset and custom PDF; pre-queue Ring Group/Follow-Me intervals; abandoned follow-up with proven action/outcome; consent-based automatic survey/voice intake; automatic historical block/status sources; periodic archive routing and complete installation/media/account recovery. These are development gaps, not merely remaining tests.
