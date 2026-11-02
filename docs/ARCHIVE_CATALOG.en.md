# Operator archive snapshot catalog

The catalog organizes **complete reporting archive snapshots with a monthly
label**. A label such as `2026-10` does not filter October events: all archived
events, source checkpoints and available projections in that SQLite snapshot
remain together. This is **not event sharding, database partitioning, transparent
cross-month query routing, storage compaction or full installation disaster
recovery**. It does not archive telephony audio, accounts, configuration or other
module databases. Those need their own backup plan.

No source data is deleted, moved, checkpointed or replaced. No automatic live
cutover, PBX access, scheduler, server deployment or web file-path endpoint is
installed. The operator deliberately runs this CLI against local trusted paths.
It reuses the validated online backup/verify/restore implementation in
`sanequeue.reporting.backup` and its committed-WAL preservation.

## Commands

The parent directory of the catalog must exist. Keep its root outside public
web/static directories on trusted private local storage. Run all commands as
the same authorized operating-system user. On Unix the catalog and bundle root
must be owned by that user with mode 0700; its database is 0600. Existing public
permissions or symlinks are refused, not silently repaired.

```sh
python -m sanequeue.reporting.archive_catalog --root /private/sanequeue-catalog create /var/lib/sanequeue/reporting.sqlite3 --month 2026-10 --key monthly-2026-10-01
python -m sanequeue.reporting.archive_catalog --root /private/sanequeue-catalog list --limit 50
python -m sanequeue.reporting.archive_catalog --root /private/sanequeue-catalog status
python -m sanequeue.reporting.archive_catalog --root /private/sanequeue-catalog verify ENTRY_UUID
python -m sanequeue.reporting.archive_catalog --root /private/sanequeue-catalog restore ENTRY_UUID /private/restore-new-directory
```

`list` returns immutable metadata and a `next` sequence cursor (`--before`).
`status` reports completed counts and at most 100 unpublished intents. Neither
command rehashes bundles; `verified_now=false` is explicit. Run `verify` for
current checksum/schema/checkpoint verification. Output omits source paths and
request keys. SHA-256 detects corruption relative to the catalog; it is not
authentication against a malicious owner able to rewrite the storage.

Restore only creates a **new** directory. Existing destinations are refused.
It never replaces or selects the running database. Keep restored data separate
for verification and a separately reviewed migration decision.

For an existing completed bundle already copied by a trusted operator into
`ROOT/bundles/UUID`, register it using:

```sh
python -m sanequeue.reporting.archive_catalog --root /private/sanequeue-catalog register ENTRY_UUID --month 2026-09 --key imported-2026-09
```

UUID means exactly 32 lowercase hexadecimal characters; arbitrary relative or
absolute bundle paths are not accepted by `register`, `verify` or `restore`.
Do not write into registered bundles. A changed database/manifest fails verify
against the immutable entry.

## Crash recovery and retention

A durable request intent reserves a UUID before backup starts. A catalog entry
is committed only after the bundle's final completion manifest and successful
integrity verification. If the process dies after completion but before catalog
publication, rerun the identical `create` request (same source path, month and
key). The completed bundle is verified and registered with the same UUID.
Reusing a key for another month/source is rejected. Retrying after the source
grows returns the original snapshot; use a new key for a new snapshot.

An interrupted bundle without its valid completion marker stays `incomplete`.
It is never accepted or overwritten. Preserve it for investigation, then use a
new request key for another attempt. Missing or changed registered bundles are
never silently regenerated. Catalog entries and intents have immutable SQL
triggers. There is no automatic deletion of snapshots, intents or incomplete
evidence, and no retention purge command.

Caps: 1000 intents total (including interrupted attempts), at most 100 entries
per list page, 100 unpublished intents in status, 60 seconds per create/verify/
restore by default (maximum 300), and 1 GiB per snapshot by default (maximum
8 GiB). `--seconds`, `--max-mib` and `--reserve-mib` are global options before
the command. The default free-disk reserve is 64 MiB in addition to backup work.
SQL uses short bounded connections; backup/hashing cooperatively check a shared
deadline. Filesystem calls are not hard real-time guarantees. Hitting caps
rejects new work without deleting retained information.

Back up the catalog database **and all bundles** consistently; neither catalog
metadata alone nor a partial directory copy is a complete archive backup.
Automated tests cover real process death before catalog publication, replay,
incomplete bundles, integrity, new-directory restore and preservation of source
events across different months. These are local synthetic tests, not a live
cross-server recovery certification.
