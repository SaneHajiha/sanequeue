Current source-of-truth (2026-10-28): [Module catalog](MODULE_CATALOG.fa.md), [reference sources](MODULE_REFERENCE_SOURCES.md), [reporting completion](REPORTING_COMPLETION_CHECKLIST.fa.md). Older roadmap notes below are historical.

# Roadmap

## Phase 1 — Monitoring and supervisor operations (2.0 beta)

Persian/English operations dashboard; queue/member scope; viewer/agent/supervisor/admin roles; guarded pause/resume; staffing thresholds; caller priority; listen/whisper/barge; dynamic membership and penalties; waiting-call hangup; live alerts; wallboard; local fonts; audit trail; installation documentation.

Release acceptance: unit tests, real-server read-only smoke checks, desktop/mobile rendering, then a controlled pilot with test calls for AMI mutations. No production calls are terminated or monitored merely to prove the implementation works.

## Phase 2 — Historical analytics

The experimental incremental queue_log reader is behind `reports_enabled=false`. Before enabling generally: validate event correlation across dates/transfers/requeues; ingest rotated files and backfill; retention; DST/timezone semantics; per-agent talk/wait/occupancy; SLA policy; abandoned-call follow-up; CSV/XLSX/PDF exports; scheduled reports; report permissions.

## Further monitoring improvements

- Push/event-driven updates with reconnection and bounded event buffers.
- Per-queue staffing policies and schedules; alerts outside an open browser.
- Optional desktop notifications and webhook destinations explicitly configured by administrators.
- Multi-PBX tenancy with separate credentials, roles and audit boundaries.
- Agent self-service screen and richer pause reasons/work states.
- Call-control integration tests using a disposable Asterisk test environment.
- CRM caller enrichment, recording playback and WebRTC only as separate opt-in integrations.

This roadmap is a plan, not a list of shipped features.
