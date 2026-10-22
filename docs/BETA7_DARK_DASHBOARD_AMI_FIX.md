# SaneQueue 2.1.0-beta.1 — dark dashboard & Asterisk 20 AMI fix

**Status:** Local Windows ZIP completed, not yet synchronized as source to GitHub. `master` and test PBX are unchanged.

## Changes in local ZIP
- Midnight-blue RTL/English UI, six KPI cards, three-panel overview, queue status, waiting and current calls, queue-member presence, supervisor control hub, alerts and wallboard; quick actions navigate to real controls, not fake operations.
- AMI diagnostics from web UI retain entered field values on failures and do not deactivate a previously active connection when testing credentials.
- Direct standard-library read-only Asterisk 20 `QueueStatus` adapter parses `QueueParams`, `QueueMember`, `QueueEntry` over local SSH tunnel. The prototype restricts reads to queue `8001`.
- Server still binds only `127.0.0.1` on **18879**, separate from earlier local ports.
- In-memory AMI credential handling, no password in local preferences file, loopback-only host restriction, CSRF on configuration/actions, 30-minute scoped test-action arming, server-side agent/queue restrictions.

## Verified
- 18 offline Python tests passed, including mock AMI protocol and test-action gate.
- Flask integration via mock AMI passed: UI HTTP 200, login/QueueStatus probe, native live parsing, 8001 isolation, redacted settings, fallback to sample data.
- Chromium offline preview: 6 KPI cards, queue tiles, AMI error message visible without losing typed password, waiting view, wallboard, no JavaScript exceptions or horizontal mobile overflow.
- **NOT tested with the user's live credentials or real supervisor write actions.**

## Out of scope / pending
- Actual test PBX connectivity: requires user's local SSH tunnel and newly rotated AMI credentials. Never put secrets in chat/GitHub.
- Listen/Whisper/Barge, Pause/Resume, Priority and Hangup remain **unverified on Asterisk 20.12.0**, despite guarded code paths.
- Transfer/Park/Pickup/conferences, trunk monitoring, all-extension presence, historical reports and AI assistant are **not implemented**.
- The local Windows application is an isolated test prototype, not a production-hardened service.

## Next
After local test and sanitized source review, upload complete sources to the development branch, run CI/security review, perform staged live call testing, then prepare a prerelease tag; do not merge this documentation-only PR as production.
