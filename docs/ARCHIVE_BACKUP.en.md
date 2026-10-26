# Reporting archive backup and recovery drill

This operator CLI snapshots **only the reporting archive SQLite database**. It
includes its committed WAL transactions, events, projections and checkpoints.
It does not back up accounts, queue policies, audit/AI/export/survey stores,
PBX configuration, recordings, prompts, credentials or encryption keys. It is
not a complete installation disaster-recovery solution or archive partitioner.
No web action, automatic schedule or PBX operation is added.

## Create a private snapshot

Use an existing trusted local backup parent owned by the service/operator,
outside the web root. The destination subdirectory must **not exist**. Use the
actual archive path configured in the reporting service, not a guessed filename.

```sh
umask 077
nice -n 15 ionice -c 3 /opt/sanequeue/.venv/bin/python \
  -m sanequeue.reporting.backup backup \
  /var/lib/sanequeue/reports.sqlite3 \
  /var/backups/sanequeue/reports-20261026 \
  --seconds 30 --max-mib 1024 --reserve-mib 64
```

The parent `/var/backups/sanequeue` must already exist with private access; the
example date is a label, not an automatic retention period. The database example
must be replaced if the installed service uses a different path. Never execute
blindly as root against arbitrary paths. Prefer a quiet period and the existing
service user. `nice`/`ionice` lower scheduling priority, not guarantee call quality.
Use an administrator-reviewed systemd resource ceiling for large archives.

SQLite's online backup API copies 64 pages per step and yields briefly between
steps. There is no source checkpoint, VACUUM, DELETE or long explicit read
transaction. Writers can continue; the resulting archive is one internally
consistent SQLite snapshot, which can include commits arriving during backup.
The copied event high-watermark describes that snapshot, not a wall-clock cutoff.
It does not prove the upstream importer was complete.

The default total deadline is 30 seconds (maximum 300); default database ceiling
is 1 GiB. Space checks reserve 64 MiB plus estimated remaining pages. Size and
deadline failure require a new destination after operator investigation, not an
unbounded retry. Filesystem calls and SQLite steps have cooperative boundaries:
these ceilings are not a hard I/O latency guarantee or reserved resources.

## Verify and drill restore

```sh
/opt/sanequeue/.venv/bin/python -m sanequeue.reporting.backup verify \
  /var/backups/sanequeue/reports-20261026

nice -n 15 ionice -c 3 /opt/sanequeue/.venv/bin/python \
  -m sanequeue.reporting.backup restore \
  /var/backups/sanequeue/reports-20261026 \
  /var/backups/sanequeue/drill-20261026 --reserve-mib 64
```

Verification checks bounded manifest size/version, SHA-256/byte size, SQLite
`quick_check`, archive core schema and event high-watermark. Backup bundles with
WAL/SHM/journal sidecars, symlinked files or directories are refused. SHA-256
detects accidental corruption; it is not a digital signature or protection from
an attacker who can modify both files. Only use trusted local operator bundles.

A completed bundle contains `archive.sqlite3` and the final `manifest.json`.
A successful new restore directory contains `archive.sqlite3` and a final
`restore.json`. Existing directories/files are never overwritten, switched into
the application or removed. Inspect a restored archive with read-only reporting
tools; compare known reports/checkpoints before considering a maintenance-window
switch. This command performs **no live service cutover or rollback**.

Interrupted/failed directories are retained privately, without a successful final
marker. Never use those databases as accepted restores; never reuse the directory.
There is no automatic cleanup or retention deletion. A power-loss/storage-failure
guarantee is not established by process-death tests. Monitor disk/inodes/WAL and
keep independently tested encrypted off-host backups under your organisation's
policy. Do not put bundles in GitHub, messaging services or a public web directory.

## Acceptance boundary

Repository tests cover real committed WAL recovery, a later source commit not
changing the saved snapshot, checkpoint preservation, corrupt/unsealed/incomplete
bundle rejection, wrong schema, limits, I/O failure, existing destination refusal,
CLI behaviour and process death before completion. Linux CI covers symlinks.
They do not prove multi-gigabyte production performance, PBX load safety,
cross-version application schema migration or a full installation restore.
