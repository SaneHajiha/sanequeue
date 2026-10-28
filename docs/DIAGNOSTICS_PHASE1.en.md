# Diagnostics foundation v1

Approved scope: archive source health, conservative incident storage/API and opt-in historical candidate processing. This is not a completed media-diagnostics product. No new PBX debug, capture, call action or automatic service activation is included.

Source health reads existing bounded importer checkpoints. It distinguishes missing, unknown, stale, failed, catching-up, current polling and immutable snapshots. Old last-call timestamps do not establish an outage. A later read-only lab check found current CEL/queue-log heartbeats and unknown CDR overlap coverage; an inactive named service alone did not prove ingestion had stopped.

Startup schema work has a separate five-second deadline; ordinary writes stay at one second and reads default to 0.5 seconds. The independent private SQLite/WAL store retains history without automatic deletion. Scope requires all incident queues, with reporter-own visibility for agents. Evidence/actions and rule parameters are immutable. Source generation, file identity, anchor and projection version bind an atomic checkpoint. Private notes may contain personal data; logs do not include their content.

Routes registered with reporting:

- `GET /api/diagnostics/source-health`: admin with reporting menu and full known-queue scope.
- `GET/POST /api/diagnostics/incidents`: private listing or a manual report tied to an authorized queue visit.
- `GET/POST /api/diagnostics/incidents/<id>`: private detail and acknowledge/resolve/reopen/comment workflow.

POST requires the current login and `X-CSRF-Token`; request size is 8KiB, description 1,000 and note 2,000 characters. Clients cannot choose queue scope, reporter or role. Fresh queue/agent/assignment checks apply, including foreign queue reuse of the same identity. Third-party free text is withheld without number visibility. Status changes require a positive expected_version; comments may omit it. Nested malformed JSON is rejected as 400. Pagination is bounded at 100 and never publishes filtered incident IDs as cursors. Changed-ownership rows are skipped with at most 200 internal rows/four reads; scan_limited=true is explicitly partial, not end-of-data. Date filtering uses report-creation time in the existing Tehran report calendar; it is not the queue-entry date.

The worker reads only local archive facts/evidence. It requires an explicit `--once`, independent database, stable `archive_<32 lowercase hex>` generation and a caught-up projection. Batches cap at 1,000 input events and 100 observations. No AMI/PBX SQL or commands are used. Short answered queue segments become historical `suspected` / `needs_review` candidates, never fault or intent verdicts. Custom thresholds are stored immutably. API rechecks use those parameters; `current_state_verified` remains false. Unknown historical policies are not silently interpreted as the default.

See the Persian companion for the full CLI example. A disabled marker is checked before initialization and commit. Source replacement or projection changes fail closed; controlled binding migration is a separate operational step, not deletion of old history.

Related reporting corrections preserve optional CEL `userdeftype` with versioned anchor migration and explicit Local optimization-end edges. Pre-cursor field/edge backfill is not automatic. A separately tested queue-source revision fix upgrades projection to 10 using bounded replay and as-of batch watermarks. Raw history and old pinned export snapshots stay intact. Derived facts may be partial during replay; diagnostics defers until caught up. Do not deploy this upgrade without backup/replay planning.

Not included: full UI, independent capture/confirmation grants, standalone internal-call ownership, SIP Call-ID/dialog capture, BYE/CANCEL/SDP, historical directional RTP, one-way audio root cause, automatic source activation or load/cross-PBX certification. Resolving a case is workflow closure, not confirmed technical causality. The next UI phase uses the established Product Design/Figma/Storybook workflow with synthetic fixtures and separate visual approval.
