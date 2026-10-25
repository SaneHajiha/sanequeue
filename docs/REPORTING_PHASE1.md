# Historical reporting foundation · phase 1

Status: implemented archive/source infrastructure, **not the completed reporting UI or AI system**. Research: [فارسی](REPORTING_RESEARCH.fa.md) · [English](REPORTING_RESEARCH.en.md).

## Implemented

- Separate SQLite WAL archive with no automatic history deletion, private file permissions, short query-only readers, a maximum five-second VM query deadline, bounded pages/batches and a disk-pressure guard.
- Immutable source versions, PBX-scoped source keys, last-observed source-item pointers and checkpoints committed in the same transaction as ingestion/projection.
- Incremental queue_log ingestion with partial-line continuation, inode/generation tracking, copy-truncate/regrow anchoring and bounded rejection records for malformed/oversized lines. Rotation is reported; archives not yet discovered/imported are not declared covered.
- Bounded, resumable immutable JSONL adapters for CDR and CEL exports. CDR normalization does not assume an integer primary key. Changed JSON snapshots require a new path; source identities deduplicate repeated exports.
- CEL evidence graph for linked IDs, explicit Local optimization, bridge and transfer relationships. This stores evidence; it deliberately does not blindly merge all bridged/linked calls or infer a hangup from Local-channel disappearance.
- Blind/attended transfer evidence retains nullable consultation timing. Missing consultation start/end is not invented.
- Full, masked, hidden and tenant/PBX-scoped HMAC pseudonymous number policies. A full digest is kept rather than silently accepting collisions from four-character aliases.
- CLI entry points and focused automated tests for replay, atomic rollback, timeout, source rotation, malformed input, privacy and transfer evidence.

## Run on a private reporting host/directory

```bash
python -m sanequeue.reporting --database /var/lib/sanequeue-reporting/archive.sqlite3 initialize
python -m sanequeue.reporting --database /var/lib/sanequeue-reporting/archive.sqlite3 import-queue /var/log/asterisk/queue_log
python -m sanequeue.reporting --database /var/lib/sanequeue-reporting/archive.sqlite3 import-json cel /private/cel-snapshot.jsonl
python -m sanequeue.reporting --database /var/lib/sanequeue-reporting/archive.sqlite3 import-json cdr /private/cdr-snapshot.jsonl
python -m sanequeue.reporting --database /var/lib/sanequeue-reporting/archive.sqlite3 status
```

Each import invocation is bounded and returns `caught_up`. Repeat until caught up, then stop. Queue-log snapshots can contain a partial last line; wait for its completion on a live source rather than inventing it. Export JSONL files are immutable, UTF-8, one database row per complete line. CEL rows require `id`, `eventtime` and `eventtype`; CDR rows require `calldate` and retain source identity fields. Naive dates use the configured source timezone, not the browser clock.

The CLI does not read root credentials, create source database users, alter PBX schemas, issue AMI requests or modify dialplan. Automated production SQL ingestion, read-only credential provisioning and service installation are a separate integration step; JSONL import is not misrepresented as a deployed persistent SQL daemon.

Use this CLI with explicitly authorized source access. The archive contains private call metadata; do not place it or source snapshots in the Git repository or a public web directory.

## Laboratory acceptance

On the existing authorized laboratory PBX, a bounded private export/import of 1169 CDR rows, 6084 CEL rows and a queue_log snapshot archived **8908 source versions**. A replay inserted **zero** additional CDR/CEL/queue-log records. The initial run took 3.197 seconds and Python peak RSS was 27296 KiB; these are measurements for this small snapshot, not a capacity guarantee for millions of records. Asterisk PID was unchanged.

The real CEL data exposed an important source gap: `eventextra` was empty for all sampled bridge/transfer/Local-optimization/hangup event types. Transfer events were present (one attended, two blind), but this does not establish their missing peer/consultation metadata. The source archive retains that fact. Synthetic fixtures verify parsing of populated extra data; they do not repair missing historical production fields.

No audio was sent externally; no AI model, GPU library or additional database server was installed. The archive experiment lived in a private temporary laboratory directory and did not replace the running monitoring release.

## Still to implement

- Direct production SQL readers with bounded source-specific pagination, durable scheduling and read-only source credentials.
- Historical observed-activity migration with an archive watermark before live-cache retention can discard unarchived data.
- Conversation/visit/ringing-attempt metrics, source coverage gaps, late-data reconciliation and conservative correlation across transfers/conferences/ring groups.
- Monthly/quarterly immutable archive manifests and crash recovery; the current foundation uses one database file and does not claim sharding is complete.
- Reporting navigation/API, filters, scope-safe exports, secure recording playback/offsets and QA/survey workflows.
- Schedule adherence, historical VIP/blacklist sources and billing/QoS adapters.
- Optional VAD/ASR/ITN/AI workers with original-timeline mapping, actual configured providers, costs/quotas and measured Persian telephone-audio quality.

These boundaries keep implemented behavior distinguishable from planned capability. No TODO button or inactive menu is presented as a working feature.
