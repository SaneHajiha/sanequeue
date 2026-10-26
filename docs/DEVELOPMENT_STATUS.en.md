# SaneQueue development handoff

Updated 2026-10-26. Continue from **feature/reporting-phase2**, draft PR **#14**.
This is a development branch, not a production certification; master does not yet contain the entire reporting change.

## Implemented code

Persistent bounded local queue/CDR/CEL/activity ingestion; scoped queue visits, agent and duty reports; protected original recordings; bilingual help and module navigation; queue trends, previous-period comparisons, Tehran heatmaps, ASA and nearest-rank waiting percentiles; explicit configurable SL denominators; full-range pause-call aggregates; separate durable private CSV jobs; request-level recording access audit; explicit happy-call/survey work sessions independent of queue presence; browser-local SVG/PNG chart export.

Unique duty uses interval unions. Queue visits, CDR segments, memberships and unique conversations are distinct units. Session time is declared work, not observed presence. Leaving queues does not end a session. Sessions require access to every stored queue. Admins with user-management access can select known extensions, supervisors use scoped membership evidence, and agents use their assigned endpoint.

The optional CPU ASR adapter is experimental code, not a completed AI processing pipeline.

## Continue locally

```sh
git clone --branch feature/reporting-phase2 https://github.com/SaneHajiha/sanequeue.git
cd sanequeue
python -m venv .venv
. .venv/bin/activate
pip install -r requirements/modern.txt -r requirements/reporting.txt pytest
python -m pytest tests --ignore=tests/historical
```

Deployment units in `deploy/` require matching paths and private state permissions. The separate export worker has a 10% CPU and 128 MB memory ceiling. Jobs and private CSV files live beside the reporting archive; they must never be exposed as static files. The web process does not start the worker. Public installer provisioning and rollback acceptance remain incomplete.

## Evidence and limits

On the laboratory archive, 490 visits matched across overview, trends and heatmap; pause-call aggregates matched paginated details. A private 490-row CSV was generated/downloaded and cancellation was exercised. These small-archive results do not certify large-history or concurrent RTP capacity. Automated tests live in `tests/test_reporting_*`; CI checks JavaScript syntax.

Large CSV jobs currently fail if the global projection watermark changes during processing, rather than publishing inconsistent pages. Unrelated live changes can therefore interrupt an old-period export. Scoped revisions or a measured bounded snapshot remain necessary. Large XLSX/PDF are not implemented. Permissions are rechecked on download, including revocation of full-number access.

Recording audit records requests, not proof of human listening; duplicate requests are grouped into fixed 30-second buckets. Audio remains closed if audit persistence fails. Visual testing of the newly added interface encountered browser input/rendering failures; API acceptance is not visual acceptance.

## Remaining development

- Complete conversation correlation, IVR choices, ring groups/follow-me, consultation/conference timing, final hangup and transferred-recording ownership.
- Shift adherence/tardiness, evidence-backed ACW/AHT/occupancy and missed-call follow-up.
- Real originating extension versus outbound CID, permission-safe party/length filters, trunk/DID reporting and daily-hour filters.
- Live-ingestion-tolerant large exports, XLSX/PDF, saved report templates and scheduled delivery.
- Versioned QA reviews, timed notes, multi-file audio and customer survey responses.
- Durable AI jobs, preprocessing/VAD, Persian ITN, transcripts/search/analysis, accuracy and actual server CPU measurements.
- Historical backfill, non-deleting archive partitions, backup restore and least-privilege automated installation.
- Multi-version PBX/SIP/PJSIP acceptance, large datasets and actual concurrent call/RTP tests. No callable external trunk is available in the laboratory.

No credentials, SSH keys, private connection configuration, messaging tokens, customer audio or live databases belong in the repository. See the Persian handoff and reporting phase documents for detail.
