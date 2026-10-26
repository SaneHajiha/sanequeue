# Reporting development: snapshots, schedules, quality and local speech

This development branch extends the historical reporting module. It is not a certification of every PBX version or of concurrent RTP capacity.

## Implemented modules

| Module | Behaviour | Evidence boundary |
| --- | --- | --- |
| Large exports | Private CSV/XLSX jobs, immutable visit-version snapshot, keyset pages of at most 200, cancellation and crash recovery | 100,000 rows, 32 MiB compressed and 64 MiB sheet XML limits; no partial download |
| Saved reports | Owner-private versioned plans; manual or selected weekdays at a Tehran time; previous day, seven complete days, previous Gregorian or Persian month | Delivery is inside the authenticated export centre; no automatic messenger/audio transmission or missed-day backfill |
| Shift adherence | Scheduled intervals compared with observed queue presence; union of overlapping memberships | Unknown observation periods are not absence; no inferred lateness without a covered shift prefix |
| Traffic | Global CDR segment report, real originating extension, outbound CID, party search, digit length, DID/trunk and hour/weekday filters | Global administrator scope required; segments are not unique conversations; current inventory is not historical proof |
| Journey | Explicit CONNECT peers, Local optimisation, bridges, transfer and instrumented IVR/ring-group/follow-me events | Linked IDs alone never merge calls or grant audio; unknown routes and final hangups remain unknown |
| Human quality | Immutable form versions, weighted scores, idempotent reviews, protected comments and timestamped audio notes | Scores are human assessments; audio notes require proven recording ownership and duration |
| Local speech | Durable owner-private jobs, one CPU thread, Silero VAD before Persian NeMo CTC, conservative text/number normalisation and keyword extracts | Experimental Persian-only engine; not generative summaries, sentiment, automatic decisions or guaranteed transcription accuracy |

## Additional agent and repeat-contact reports

Handling/occupancy uses explicit frozen endpoint identity and interval unions across authorised memberships. ACW comes only from explicit wrap-up states with verified queue-segment end boundaries. Missing evidence returns NULL with reason codes. AHT is specifically queue-segment talk plus proven ACW per completed queue segment, not a transferred conversation metric.

Later-contact rows compare the same recorded caller after a proven abandonment within authorised queues and a chosen window of 1–30 days. Several abandonments can point to one later answered visit. This neither proves a unique customer nor an outbound callback. Missing/unfinished observation is not proof of no follow-up.

## Installation and stopping

The installer includes reporting dependencies and creates private databases as the service user. It installs separate import, export and schedule units. The web server never launches ingestion or model work. Existing historical data is retained. The optional AI worker starts only when `/etc/sanequeue/reporting-ai.enabled` and its configuration already exist. Models and isolated ASR dependencies are not silently downloaded by the public installer.

`sanequeuectl disable` stops the module's reporting, export, schedule and optional AI services as well as its normal services. It does not stop Asterisk or MariaDB. Old installations without the optional units remain supported. Restore/upgrade/emergency acceptance on additional PBX versions is still required.

Historical SQL imports require a separately provisioned **read-only** `/etc/sanequeue/reporting-sql.ini`. The installer reuses this configuration through `reporting.env`; it does not copy privileged PBX database credentials into the web process. If absent, queue-log/activity data can import but full CDR/CEL history is unavailable. Index prerequisites must be checked before enabling SQL import; never add a large production-table index during busy hours without a reviewed maintenance plan.

Default worker ceilings: import 15% CPU/128 MiB, exports 10%/128 MiB, schedules 5%/128 MiB, optional AI 20%/768 MiB. These are systemd ceilings relative to one CPU, not reserved capacity or proof of harmlessness to live calls. AI defers on low memory, disk pressure or load and runs serially. Do not remove those limits on a live PBX to speed up a backlog.

## Operator guide

1. Select dates and authorised queues in Reports. Metric help explains whether a figure counts queue visits, CDR segments or observed time.
2. In **Saved plans & scheduled exports**, create a named plan, choose queues, file format/language, complete relative period and optional schedule. Manual plans do not run automatically. Export files appear only in the owner's export centre. A dispatched occurrence means a job was registered, not that its file succeeded; check the export status.
3. Open a visit's **Path & audio**. Journey links show recorded evidence only. Playback/download and access history use separate permissions. The access log records requests, not proof that a human listened to the whole file.
4. An administrator creates a quality form. A permitted supervisor selects a version and scores every criterion. Attach a timestamped note only to an authorised recording; changing the form later does not rewrite old reviews.
5. If the local speech worker is configured, explicitly request transcription for an authorised recording and refresh its status. Review the original transcript alongside the normalised text. Silence or rejected audio must not become invented conversation text. No customer audio is sent to a cloud provider by this implementation.

## Privacy and correctness

Owner identity, role, report menu and every frozen queue are checked on reads and downloads. Revoking full-number or audio access prevents historical content disclosure. A schedule also rechecks current account and queue grants at dispatch. Edits do not rewrite prior occurrence scopes. Cross-database occurrence keys reuse the original export after a crash instead of producing a second snapshot.

Snapshot history and source events are not automatically deleted. This increases storage needs: monitor the database, WAL and private output sizes. Read deadlines and short pages limit pinned readers, but monthly archive partitions and a verified backup/restore workflow remain separate development items.

## Still outside the completed scope

Direct Persian PDF generation; unrestricted report builders; verified multi-hop/transferred audio ownership; complete IVR digits without PBX instrumentation; ACW instrumentation when the source lacks explicit states; outbound callback proof; customer survey response ingestion; VIP-specific SLA/blacklist sources; archive partition routing and restore drills; corpus-wide transcript search; generative AI analysis; production SQL auto-provisioning; multi-version installation/load/RTP certification. Do not label these as tested or implemented merely because the architecture describes them.

Laboratory acceptance and current handoff documents record the actual passing checks and unresolved items. No private audio, transcript, database, messaging token or SSH key belongs in this repository.

## Source semantics

Transfer and Local-channel labels follow the [official Asterisk CEL specification](https://docs.asterisk.org/Configuration/Reporting/Channel-Event-Logging-CEL/CEL-Specification/). The second transferer channel is distinct from the explicit transfer target. Application-bound transfers can lack a proven target channel; they must not acquire one from a fallback name.
