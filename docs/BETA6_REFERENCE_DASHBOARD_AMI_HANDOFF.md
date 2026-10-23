# SaneQueue v2.1.0-beta.6 — UX & AMI QA handoff

This document records a local Windows test ZIP. **Full v2.1 beta.6 source is packaged locally and is NOT pushed to GitHub.** PR #1 remains documentation-only; do not merge as a functional release.

## Observed from the connected browser (2026-10-23)
- v2.1.0-beta.5 displays live AMI data for queues `8001` and `default`.
- One `test` member was ready in `8001`; zero waiting calls in the latest observation.
- `QueueStatus` and `CoreShowChannels` appear in permitted ListCommands; `PJSIPShowEndpoints` and `PJSIPShowContacts` do not.
- Audit HTTP 200 responses for Pause/Whisper/Barge are not evidence of successful Asterisk side effects.
- An empty `default` queue falsely generated a no-ready-staff alert.

## Changes in local beta.6 ZIP
- Dashboard order matches reference: six colored KPIs, three equal-height operational columns (queue readiness / waiting room / agent roster), active-call overview and quick operations, alerts and live charts further below.
- Real queue readiness circles and member-status mini bars use only current QueueStatus data; no fabricated trends.
- Agent control actions displayed consistently: full-width Pause/Resume, followed by a three-column action grid for Listen, Whisper, Barge, Penalty and Remove.
- No staffing alert for empty/no-member/no-caller queues.
- Audit label distinguishes HTTP accepted from confirmed PBX outcome.
- PJSIP permission failure now suggests inspecting exact server-side AMI Actions and `res_pjsip_manager` module, not blanket privileges.
- Local-only port `18884`, kept-open diagnostic launcher, browser-observed samples.
- Source ZIP includes Persian/English docs and safe read-only AMI diagnosis script.

## Validation
- 64 selected local unit and regression tests passed, Python compilation and JS syntax passed.
- Chromium mock-API preview checked 1650, 1300, 768 and 390px: six KPI cards, four sample queue rows, rendered agent action grid, no horizontal page overflow or uncaught JS exception. Both light and dark were captured.
- ZIP integrity and a scan for the previously disclosed AMI credential passed.
- **No real PBX supervisor command was sent from this environment; full Flask integration and production deployment remain unverified.**

## Remaining items
1. On test PBX inspect `manager show command PJSIPShowEndpoints`, `manager show command PJSIPShowContacts`, `module show like res_pjsip_manager`.
2. Do not add `write=system` without recognizing it authorizes other dangerous system-management Actions; test-only separate account and private ACL if essential.
3. Confirm real QueuePause changes queue member state, then supervise test-only Priority/Hangup and consenting Listen/Whisper/Barge.
4. Implement future Transfers, Park/Pickup, WebRTC, CRM, AI and production authentication. Historical reporting deferred by product scope.
