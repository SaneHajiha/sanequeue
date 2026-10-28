# VIP and blocked-call observation reports

Open **Reports → VIP & blocked observations**, select a period of at most 31
days and authorised queues in the main report filter, then **Load report**.
Supervisors/admins with Reports and current queue-view grants can read. Agents
cannot use this report. Caller numbers are masked unless the current queue grants
allow caller details. Changing a filter/view discards earlier private results.

## VIP is an annotation, not phone policy

Administrators with caller-details access on a queue can record a new immutable
VIP or explicitly-not-VIP annotation for a number. By default it starts now;
**Effective from selected period start** intentionally backdates the annotation
to the report's Tehran start time. This is an administrator classification, not
proof of the historic PBX or the caller's identity. It never changes routing,
priorities, a blacklist, dial permissions or authentication.

The newest annotation effective at each queue-entry time classifies that visit.
Future annotations do not rewrite earlier classifications. No matching annotation
means **unclassified**, not ordinary/not VIP. Number matching only normalises
decimal digits and formatting; `0912...` and `+98912...` are not guessed equal.
Labels apply independently per PBX/queue. A call visiting two queues remains two
visits; membership in multiple queues does not create extra people.

SLA numerator is answered visits within the selected wait threshold. Denominator
is answered visits with known waiting time; unknown waiting is excluded, and no
denominator yields a dash, never 0%. Counts are visits, not unique customers or
conversations. Annotation history shows the latest 100 permitted annotations,
not just those created inside the selected report dates. All history is retained.

## Imported block observations

No live blacklist adapter is silently installed. A technical operator exports
actual, reviewed source events to UTF-8 JSONL, with a stable source ID, queue,
number, epoch timestamp and one reason (`blacklist`, `policy`, `security`, `other`):

```json
{"id":"source-event-123","queue":"8001","number":"09120000000","at":1793000000,"reason":"blacklist"}
```

```sh
umask 077
/opt/sanequeue/.venv/bin/python -m sanequeue.reporting.customer_segments \
  --database /var/lib/sanequeue/customer-segments.sqlite3 \
  --pbx primary --source reviewed_pbx_export /private/operator/blocks.jsonl
```

Use the database parent configured for the actual reporting archive; the command
path is an example. Keep source exports and database private. Never upload them
to GitHub. There is no web file-path/URL import. Do not infer a queue for a
pre-queue blocked call: a source must explicitly establish that attribution.
Unattributed/global blocked-call routing needs an actual server adapter.

Stable `(PBX, source, event ID)` deduplicates retries. Changed contents under an
existing ID are rejected, not overwritten. Each batch of up to 500 is atomic;
earlier committed batches survive a later malformed line. CLI failure reports
the committed count without echoing numbers; retry the reviewed source using the
same IDs. Input is bounded to 4 KiB per line and 8 MiB per file.

Counts describe **imported observations**, not an independent verification that
the PBX blocked each call. Missing rows do not prove no blocked calls. Different
sources may describe the same call twice; there is no guessed deduplication by
CallerID/time. The table shows the latest 100 observations in the authorised
period and reason aggregates. No audio is implied or granted.

## Operations and verification

The private local metadata store is separate from the reporting archive. Reports
use a read-only attachment, current scope, indexed temporal lookups and the shared
archive deadline; writes do not contact AMI/PBX SQL. The current ceilings are
50,000 annotation versions and 100,000 observations per PBX, with no automatic
deletion. At a ceiling ingestion is refused; plan storage/backups before growth.
Include this metadata database separately in recovery plans; archive-only backup
does not include it. Rendering uses text nodes; stale requests are invalidated.

Tests cover temporal classification/queue scope, explicit SLA denominators,
unknown values, normalisation without country guessing, idempotency/conflicts,
atomic import, CLI, CSRF/menu/queue/role checks, masking and actual frontend
request races/text escaping. Live source integration, historical completeness,
visual acceptance and loaded-server performance remain separate acceptance.
