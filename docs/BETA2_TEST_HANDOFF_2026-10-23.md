# SaneQueue v2.1.0-beta.2 — test handoff (2026-10-23)

This is a **local Windows test ZIP**. Complete beta.2 source code remains in the ZIP and **has not yet been pushed to GitHub**. Do not merge this documentation-only branch as a production release.

## Local test build

- Local bind only: `127.0.0.1:18880`.
- Installer: `START_SANEQUEUE_18880.bat`.
- SSH tunnel to Asterisk 20.12.0: `127.0.0.1:15038` -> PBX local AMI 5038.
- AMI queue read is restricted to test queue `8001`; written commands require a separate 30-minute test gate and are not production validated.
- Offline tests: **20 passed**; Python compile and JavaScript syntax passed. Flask live integration and Asterisk action tests **not run in this environment**.
- Fixes: failed reconnect preserves verified session; test queue hint for extension 100 maps to `PJSIP/100` for ChanSpy only; QueueMember `Membership` retained and static removal blocked; AMI request timeout raised to 30s while dashboard polling remains 15s.
- User must rotate previously shared AMI secret before further access. Never commit it.

## Feature maturity

Prototypes: queue and waiting-caller monitoring, agent state, service level counters, responsive FA RTL/EN UI, wallboard, alert thresholds, role and audit foundations.

Staged but unverified Asterisk writes: Pause/Resume, dynamic QueueAdd/QueueRemove, QueuePenalty, QueueChangePriorityCaller, Hangup, Listen/Whisper/Barge on consenting test calls.

Not implemented: Blind/attended transfer, Park/Pickup/conferences, all-extension Presence, trunk health, WebRTC, phonebook/CRM, AI assistant, multi-tenant RBAC and production hardening. Historical reporting/Excel intentionally deferred.

Benchmarks: [FOP2](https://www.fop2.com/), [VoiPing](https://voiping.ir/product/ماژول-گزارشات-و-مانیتورینگ-آنلاین-صف/), [QueueMetrics](https://www.queuemetrics.com/), [OpDesk](https://github.com/Ibrahimgamal99/OpDesk), [VICIdial](https://www.vicidial.com/features/).

Real PBX confirmation is still needed before any capability can be labelled production-ready.