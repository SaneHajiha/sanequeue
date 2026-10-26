# SaneQueue development handoff

Updated 2026-10-26. Continue from **feature/reporting-phase2**, draft PR **#14**. This is a development branch, not a production certification. Master does not contain the entire reporting change.

## Implemented

Bounded independent queue/CDR/CEL/activity ingestion; scoped queue visits and agent/duty reports; protected recordings and access-request audit; bilingual help and module navigation; trends, previous-period comparison, Tehran heatmaps, ASA, waiting percentiles and explicit SLA denominators; pause-call aggregates and explicit happy-call/survey periods independent of queue membership.

New code adds immutable visit-version export snapshots, streaming private CSV/XLSX jobs, private versioned scheduled plans, evidence-limited shift adherence and conditional ACW/AHT/occupancy, later queue contact after abandonment, global administrator CDR/trunk/DID traffic, real-origin/CID/party/length/hour filters, explicit CONNECT and Local-optimisation journey evidence, versioned human QA with protected timed notes, durable CPU-only Persian speech jobs with VAD and conservative number normalisation. Keyword extracts are not generative analysis or sentiment decisions.

Unique duty uses interval unions. Queue visits, CDR segments, memberships and unique conversations are different units. Declared survey time is not observed presence. Leaving a queue does not end a session. Every stored queue remains part of the access scope.

## Continue locally

```sh
git clone --branch feature/reporting-phase2 https://github.com/SaneHajiha/sanequeue.git
cd sanequeue
python -m venv .venv
. .venv/bin/activate
pip install -r requirements/modern.txt -r requirements/reporting.txt pytest
python -m pytest tests --ignore=tests/historical
```

The installer creates private reporting stores and separate import/export/schedule units. Historical SQL needs an explicitly provisioned read-only configuration and verified indexes. AI models/runtime are optional operator configuration, not silent downloads. Emergency control includes installed reporting workers and never stops Asterisk/MariaDB. Multi-version upgrade/rollback acceptance remains open.

## Actual evidence

On the small laboratory archive, 490 visits matched across overview/trends/heatmap, and 1,199 CDR segments matched paginated details and grouped totals. A private 490-row XLSX passed ZIP/XML checks. Audio and internal survey calls were exercised in earlier panel/phone acceptance. There is no callable external trunk.

An actual local speech request from the panel completed for an approximately 19-second recording: 4.38 seconds engine CPU, 215.8 MiB peak RSS and 22.1 seconds wall time under the service limit. No recognisable speech was detected in that sample; this does not establish Persian accuracy or concurrent call/RTP capacity.

Tests live in tests/test_reporting_*; CI checks JS syntax. Consult Actions for the exact commit. Browser capture/input failures leave final visual light/dark/mobile acceptance open; API success is not visual acceptance.

## Remaining development

See [phase five](REPORTING_PHASE5.md) for exact behaviour, ceilings, operator steps, privacy and remaining items. Unrestricted report builders, fully proven multi-hop recording ownership, complete IVR without instrumentation, PBX instrumentation for currently unobserved ACW, outbound callback proof, live survey routing and free-form voice feedback, VIP/blacklist sources, archive partitions/restore, cross-account transcript discovery, generative AI and production SQL auto-provisioning are not completed merely because the architecture describes them.

Source/snapshot history is retained indefinitely. Monitor disk/WAL/private output growth. Never commit credentials, SSH keys, connection secrets, tokens, customer audio/transcripts or live databases.

## Independent review and expanded module scope

The reporting worker reauthorization, midnight plan retries, historical AI job lookup, stale-result clearing, automatic plan loading and bounded MP3/Ogg timed-note metadata fixes are implemented. Reporting now shows one selected authorized section. Exact-head CI passed on Python 3.10/3.11/3.12 (640 tests); 274 bounded lab reporting tests passed. See [review evidence](REVIEW_20261026.md).

The initial [inbound status notice](INBOUND_NOTICES.en.md) includes API/UI, revision/expiry and an optional explicit hook. No live hook has been installed or accepted and playback events are not yet projected into reports. The additional survey/routing/fax/paging/campaign/reservation and related modules are tracked in the [module program](MODULE_PROGRAM.fa.md), not presented as completed.

Latest source e12effec passed 665 CI tests across three Python versions; 40 incident/media tests passed on the bounded Linux lab runner. Real conversion of the public 14.84-second prompt completed in about 3.03 seconds, consuming 0.323 cgroup CPU seconds with about 29 MiB observed peak memory. This does not establish concurrent-call/RTP capacity or ASR accuracy; see the review evidence.

## Current development checkpoint

[Owner-scoped transcript search](TRANSCRIPT_SEARCH.en.md) is implemented with atomic FTS indexing, bounded legacy migration, fresh multi-queue recording authorization, safe excerpts and request-race protection. Seven new store/API tests and actual-script frontend security checks pass locally; the related AI/API set passed 26 tests (one optional local decoder test skipped). This does not validate ASR accuracy or live PBX load. Current SSH deployment is blocked by the Windows ACL of the previously created key, and Chrome review hit CDP focus timeouts; these attempts are not live acceptance or a new independent AI review.

The new [customer survey slice](CUSTOMER_SURVEYS.en.md) has versioned bounded branching forms, idempotent answers, explicit CSAT denominators and independently scoped panel access. Nineteen module tests, two service-control tests and the actual JavaScript harness pass. The opt-in PBX adapter accepts only exactly proven Queue COMPLETEAGENT endings; transfer/caller-hangup/missing evidence are not guessed. Its service/hook is not automatically provisioned or live-phone accepted.

[Direct bilingual PDFs](PDF_EXPORTS.md) now use the private export worker, immutable snapshots and current authorization, with explicit 1,000-row/100-page/8 MiB limits. Synthetic three-page FA/EN samples were rendered and inspected; live installation acceptance and unrestricted report construction remain separate.

Checkpoint source commit `1a6a7cec72a5d166ced6b6623e969a3538df7c86` passed [exact-source CI](https://github.com/SaneHajiha/sanequeue/actions/runs/40325215028) on Python 3.10/3.11/3.12. Python 3.11 logs show 703 passed and all three actual-script JS harnesses passed. PDF API/MIME/revocation is covered. Server installation, PDF memory acceptance under 128 MiB, real survey phone acceptance and renewed external three-service review remain open; CI does not replace them.

## Next development: report builder and export lifecycle

The [queue-visit builder](REPORT_BUILDER.en.md) adds whitelisted columns, wait/talk filters, bounded grouping, private immutable definitions and agent scope. Preview reads live archive facts; arbitrary SQL, all-CDR construction and custom file export are not claimed.

[Private export artifact reconciliation](EXPORT_RECOVERY.en.md) handles process death followed by cancellation/retry exhaustion. Durable intents, shared database budgets, persistent directory scanning and private quarantine preserve abandoned content. Completed outputs, archives and recordings remain untouched. There is no disk reclamation or quarantine download/automatic restore. Cache headers and view disposal were checked for the builder/export centre.


Published-source verification: commit `1c5ad85b2b3072be1dfb3479e1e94668227bae24` passed [CI run 98](https://github.com/SaneHajiha/sanequeue/actions/runs/40340342178) on Python 3.10/3.11/3.12; the 3.11 job recorded 736 passing tests, and all four real-script frontend harnesses passed. This does not replace live server/call/load acceptance. Preview deployment is blocked by Windows access to the existing SSH key.


## Archive-only backup and restore development

[Operator archive backup](ARCHIVE_BACKUP.en.md) now uses the SQLite online backup API with committed WAL preservation, bounded time/size/space, SHA-256 and core-schema checks, a final private completion marker, and restore into a new directory only. Thirteen local tests pass (one Linux symlink test skipped on Windows); full exact-commit CI is checked at publication. An independent review found and fixed premature completion-marker publication after fsync failure. This backs up only the reporting archive: other module databases, media and PBX configuration need a separate full-installation recovery plan. No live database switch, automatic retention or archive partitioning was added.


## Indexed journey and termination correctness

[Call journey guide](CALL_JOURNEY.en.md): root-only pre-queue IVR inside report/assignment cutoffs is implemented without widening CDR, relation or downstream windows. A version-9 current-source CEL identity projection is indexed by UID/time and rebuilt only in the existing bounded worker; HTTP waits for catch-up and performs no DDL. Final causality requires agreeing current causes from two proven peers, after their connection; conflicting/missing/complex evidence stays unknown. Queue-segment termination remains separate. Browser stale success/failure and private-data disposal are covered. Thirty-seven targeted backend tests and the real-script frontend harness passed locally. Exact-source CI is checked at publication; real PBX/phone, load and visual acceptance remain open.
