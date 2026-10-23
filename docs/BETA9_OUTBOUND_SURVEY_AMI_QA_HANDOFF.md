# SaneQueue 2.1.0-beta.9 — outbound survey agent status and AMI connection QA

**Development handoff (2026-10-23).** Full beta.9 source and Windows launcher are in the conversation ZIP, **not yet pushed to GitHub**. Existing development PR #1 remains documentation-only. This is **not a production release**.

## Correct survey workflow

Survey is a **manual outbound task carried out by the agent**, not a survey IVR and not routing the caller to a survey. Agent presses QueuePause with reason `survey` (displayed: «نظرسنجی تلفنی خروجی (طبق فهرست مشتریان)»), calls customers on the organization's own list manually, then QueueUnpause/Resume to return to receiving inbound queue calls. Support per-queue editable pause reason options; display active survey-paused memberships.

## Fixes in the local ZIP

- Implemented previously missing JavaScript policy state and handlers for queue summary, rules save, supervisor grants, queue selector and queue policy editor.
- Working 10-metric queue summary dialog sourced from QueueStatus, not fabricated history.
- Actual API save/refresh for queue-specific staff percentages, counts, wait and backlog alerts and tagged Pause reasons, plus scoped supervisor grant policy editing.
- Six-stage read-only AMI diagnostic: validated private target, TCP reachability, AMI login, QueueStatus, live-parser, Issabel-visible queue filter; safe/structured errors distinguishing failure stages.
- Independent no-Flask CLI `RUN_AMI_STAGES_18887.cmd`, which uses Login, QueueStatus and Logoff only, without exporting passwords or caller data.
- New isolated localhost port 18887; Unicode-safe Windows debug launcher and build version check.
- Existing QueueStatus monitoring and safe test-call supervisor gates inherited, not globally unrestricted.

## Validated locally

- 78 selected Python unit/regression tests passed; Python compile and JS syntax passed.
- Offline Chromium using Jinja-rendered template and mocked APIs: six KPI cards, working queue summary with 10 metrics, policy/grant forms, 6 AMI stages, outbound-survey Pause reason, no JS exceptions or desktop/mobile horizontal overflow.
- Complete archive 718 sanitized files, ZIP CRC check passed.
- **Real user's PBX login and call-changing AMI actions were NOT tested in this beta.9, nor was Windows Flask startup.**

## Remaining work, NOT falsely presented as complete

Blind/attended transfer, Park/Pickup, conferencing, full extension/trunk and RTP diagnostics, WebRTC audio/video, CRM/contacts and task list workflow, actual multi-user authentication and queue isolation, AI copilot. Historical reporting remains deferred.

Before production, build and verify these subsystems with PBX-specific test traffic, TLS/WSS and compliant call surveillance policies; only merge code after review and CI.
