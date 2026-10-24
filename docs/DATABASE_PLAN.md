# Reporting database and indexing plan

Reporting remains a later phase. No SQL in this document has been executed against the PBX. Do not apply generic indexes to Issabel tables without inspecting the actual schema, engine, existing indexes, write rate and a maintenance plan. Issabel queue_log storage varies; some installations have only a file, others a realtime table with different columns.

## Application-owned event ledger

Use a separate database and read-only source credentials. Preserve raw event semantics: source PBX, source file identity/rotation epoch, byte offset, event timestamp, call Uniqueid, queue, member, event name and all data fields. Commit each import batch and its cursor in the same transaction. Never treat timestamp alone as an import cursor or hash the line alone as a unique event: identical lines can legitimately occur at distinct source positions.

Proposed PostgreSQL schema (design for the later importer; not a claim that the importer exists):

```sql
CREATE TABLE queue_events (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  pbx_id varchar(48) NOT NULL,
  source_epoch uuid NOT NULL,
  source_offset bigint NOT NULL CHECK (source_offset >= 0),
  occurred_at timestamptz NOT NULL,
  call_uniqueid text,
  queue_id text NOT NULL,
  member_id text,
  event_type text NOT NULL,
  event_data jsonb NOT NULL,
  UNIQUE (pbx_id, source_epoch, source_offset)
);
CREATE INDEX queue_events_queue_time
  ON queue_events (pbx_id, queue_id, occurred_at, id);
CREATE INDEX queue_events_member_time
  ON queue_events (pbx_id, member_id, occurred_at, id);
CREATE INDEX queue_events_call
  ON queue_events (pbx_id, call_uniqueid, occurred_at, id);
```

Rotation handling must distinguish rename, copytruncate, inode reuse and replacement. Retain the old descriptor until drained; verify file fingerprints around committed offsets. Reimporting another copy requires explicit provenance/reconciliation; the source-position unique key alone does not deduplicate separate copies. The current legacy importer lacks this complete contract and drops call identity from its report model.

Roll up into time buckets with an idempotent watermark. Keep source events so changed SLA/short-abandon policy can be recalculated. Define answered, abandoned, transfer, timeout, exit-with-key, ring-no-answer and queue re-entry separately. Store UTC and render in configured IANA timezone. Use keyset pagination on `(occurred_at,id)`, bounded time ranges and query timeouts; never fetch millions of rows into a web request.

## Existing MariaDB CDR

First inspect `SHOW CREATE TABLE asteriskcdrdb.cdr`, `SHOW INDEX FROM asteriskcdrdb.cdr` and representative `EXPLAIN` plans using read-only access. If the schema contains these columns and equivalent indexes are absent, candidates are:

```sql
-- Examples for DBA review only. DDL may scan/lock a large table.
CREATE INDEX sq_cdr_time_uniqueid ON asteriskcdrdb.cdr (calldate, uniqueid);
CREATE INDEX sq_cdr_linkedid_time ON asteriskcdrdb.cdr (linkedid, calldate);
```

Do not add linkedid indexing if the column is absent. Avoid automatically adding both call-direction indexes or indexing every field; measure the actual predicates and PBX write overhead first. Prefer incremental replication/import into the application database for dashboards. A read replica or explicit resource-limited reporting account avoids long scans competing with call-related writes.

For a realtime queue_log table, inspect its actual time/callid/queuename/agent/event layout. Time-range queries commonly benefit from `(queuename,time)` and agent-time queries from `(agent,time)`; ordering and types must match the local schema. These are query-driven candidates, not an installation script.

## Retention and operations

Partition large application-owned ledgers by time only after query/load evidence justifies it. Back up with restore tests, constrain retention and personal-data access, and expose import lag/cursor errors. Never write to Asterisk `asterisk`, `asteriskcdrdb` or `call_center` tables as part of monitoring installation. No reporting query belongs on the collector event loop.
