# SaneQueue verification and release gates

Development branch `feature/product-audit-20261109`, based on master `e977516398db5b04309ddae11dffb3dbec4f09d9`. This development snapshot carries the baseline runtime version `2.1.0-beta.26` and is identified by its Git SHA. A new release identifier requires the acceptance gates below.

## Evidence

| Check | Result |
| --- | --- |
| Windows / Python 3.11.4 baseline | 355 passed, 5 skipped, 104 subtests passed. |
| Windows / Python 3.11.4 with changes | 367 passed, 6 skipped, 108 subtests passed. One intermediate run exposed a missing import in the new audit test. After correction the full run passed. |
| Skips | Four Linux-only installer tests, including the new directory-descriptor fixture, and two dedicated Redis integration tests. |
| Chromium E2E | Real demo login/logout, unavailable versus observed zero, abandon-only and mixed SLA, unknown SLA threshold, queue dialog Escape, search-filtered trend, wallboard, 18 admin menu entries, 1440×900 English light and 390×844 Persian dark, and mobile no horizontal page overflow. Test response fixtures simulate reporting observations. |
| Static checks | Python provisioning/launcher source parsed, five JS entry points passed `node --check`, installer passed Bash syntax check, `pip check` found no broken installed dependencies. This does not establish dependency CVE coverage or a reproducible package lock. |
| Local performance | 25,000 synthetic queue-log records across 10 queues, querying one authorized queue. Ingest 379.1 ms. Seven reads, median 75.6 ms, maximum 97.6 ms. Single-process Windows test; no live throughput, memory, telephony or multi-user SLA conclusion. |
| Real PBX | No session-specific call, media, installation, upgrade or rollback acceptance. See [historical beta.26 evidence](AUDIT_BETA26.md) for the published release only. |

### Reproduce on an isolated development host

```bash
python -m pip install -r requirements/modern.txt pytest httpx2
python -m babel.messages.frontend compile -d qpanel/translations
python -m pytest tests --ignore=tests/historical -p no:cacheprovider -q -rs
node --check qpanel/themes/qpanel/static/js/operations.js
bash -n scripts/install.sh
```

For browser checks, start the loopback synthetic demo from the source root using a new state directory:

```bash
SANEQUEUE_STATE_DIR="$(mktemp -d)" SANEQUEUE_DEMO_PORT=18895 python demo_monitor.py
```

Use its generated admin password only in the isolated demo. From another terminal with Playwright and Chromium available, set `SANEQUEUE_BROWSER_URL=http://127.0.0.1:18895`, `SANEQUEUE_DEMO_PASSWORD`, and optionally `SANEQUEUE_CHROMIUM` and `SANEQUEUE_SCREENSHOTS`. Run `node tests/browser/operations-metrics.cjs`. Keep any credentials out of Git and screenshots. A dedicated Redis test instance can be supplied with `SANEQUEUE_TEST_REDIS_URL`; use an isolated instance because integration fixtures may mutate its state.

## Security and reliability disposition

The workbench audit covers the original revision and remains partial. Evidence below refers to the stated baseline unless a fix is listed.

| Issue and impact | Evidence | Status |
| --- | --- | --- |
| Forged local sign-in and sign-out can replace or clear operator sessions. | `qpanel/app.py:180-211,440-446` | Fixed for local forms. Optional upstream external-login integration requires its own protocol review. |
| Self-service can adopt an unassigned extension, changing the authority used for own status and personal call history. | `sanequeue/security/profile.py:36-41,66-107`, `qpanel/local_accounts.py:68-79` | Admin-only reassignment. Existing assignments and self-service name, avatar, password and authorized controls remain available. |
| Legacy display aliases can change the queue ID after managed authorization. Contact ID dialing can bypass a directory menu denial. | `qpanel/operations.py:109-123,344,389-429,655-669` | Fixed and exercised with fixtures. |
| Anonymous rejected calls can drive operational audit rotation through long form values. | `qpanel/operations.py:147-162` | Anonymous requests stay outside the operator audit file; authenticated fields are bounded. Separate security telemetry and authenticated rate limiting remain open. |
| Backup errors can enter restore without complete copies. Permission traversal can use mutable intermediate paths. | `scripts/provision.py:100-119,157-162,212-232` | Code changes use a backup-complete gate and directory-relative descriptors. Verify both branches on Linux and reproduce upgrade/rollback on Rocky 8. |
| A predictable temporary script path can be modified before root execution. Bootstrap downloads are not bound to published checksums. | `docs/INSTALL.md:7-14`, `scripts/install.sh:7-20,27-36` | Bilingual guides stage verified release archives in a private directory. Standalone bootstrap and Python runtime supply-chain verification remain open. |
| Managed installation suggests private IPv4 HTTP, leaving credential and control traffic exposed to a network observer. | `scripts/provision.py:45-59,89-95,155-176` | Open. Use TLS on the lab deployment and enforce secure remote defaults before a production gate. |
| A shared WebSocket connection ceiling can be occupied by one account; fallback WSGI omits the revocation registry. | `sanequeue/gateway/app.py:19-69`, `demo_monitor.py:129-190`, `compose.yaml:7-13` | Open. Test per-principal admission and server-side logout in all deployment modes. |
| A failed or uncertain resume releases a prior pending staffing reservation. | `qpanel/operations.py:320-347`, `sanequeue/actions/ledger.py:54-81` | Open. Keep reservations until newer observed state or definitive non-departure. Test ordered replay and concurrent commands. |
| Legacy opt-in report does synchronous queue-log ingestion; date fixes do not migrate it to the persistent archive. | `qpanel/operations.py:633-679`, `qpanel/reporting.py:15-69` | Open. Reuse the reporting worker branch after review. Keep separate PBX/queue scopes, export permissions and coverage. |

The focused security worker stopped after an automated security check flagged its turn. Its early source leads remain in the partial workbench record. No conclusion about unreviewed files follows from this interruption.

## Release checklist

1. Reconcile the reporting and visual branch heads, inventory data migrations, and verify role/queue/export/audio permissions. Run the dependency advisory scan against the actual locked release environment.
2. Complete Redis outage and restart tests, WebSocket churn and fair admission, and measured concurrent reporting and operator actions.
3. Rehearse clean install, upgrade with existing accounts and private databases, failed backup, interrupted upgrade and rollback on a disposable Issabel 5 / Rocky Linux 8 / Asterisk 20 host.
4. Snapshot application state and deployment configuration. Record installed source target, service state, PBX version/PID, and backup path. Use isolated endpoints and no production customers for call-control and audio acceptance.
5. Verify `systemctl is-active sanequeue sanequeue-collector sanequeue-redis`, `sudo sanequeuectl status`, and the displayed build revision. Check queue membership, PBX status, session revocation, and one controlled call per enabled action. AMI acceptance and observed phone/audio outcomes require separate evidence.
6. To roll back, use the matching verified installer backup and prior source pointer. Stop only relevant SaneQueue services, preserve the failed-run state before restoring private application data, restore managed units and AMI config with original permissions, run `systemctl daemon-reload` and an AMI manager reload when needed, and start only the previously active services. The telephone module has a separate managed dialplan restore. Validate healthy services, preserved accounts and unchanged Asterisk PID.
7. Set the next version only after the gates pass. Build release archives and SHA256SUMS from that exact commit. Validate the downloaded artifact and rehearse the installation instructions before deployment authorization.
