# SaneQueue live monitoring — beta.2 scope

Monitoring only. Historical reports and CSV/Excel exports are explicitly deferred.

## Implemented in the recovered local beta.2 source (pending GitHub source sync)

- Live operations dashboard: queue KPIs, waiting calls, staffing, alerts, RTL Persian and English.
- Queue health view: zero-ready critical state, backlog threshold, longest wait, capacity status.
- Live calls view: active members and waiting room with limited AMI channel metadata when permitted.
- Staff view: queue members and agent status, pause/resume with reason.
- Supervisor controls: queue priority, hangup, spy, whisper, barge, dynamic membership and penalty — permission-scoped.
- Browser wallboard, dark theme, accessible status labels and search/filter shortcuts.
- Sample-data local Windows preview with server-side AMI control lock-out.
- Roles, CSRF, queue scoping, audit events and redacted caller numbers.

## Still unverified / intentionally not promised

- Full SIP/AMI validation on each Asterisk and Issabel version, load tests and multi-site isolation.
- Trunk monitoring, parking lot, attended transfer, pickup, presence, conference rooms and advanced supervision require dedicated read-only adapters or safe command integrations.
- No historical call-center reporting in this development phase.
- Production compatibility, security and real-call behavior require dedicated staging.

## Review and rollout

1. Keep `master` unchanged; development branch `work-recovery-2026-10-22`.
2. Transfer complete sanitized local source via `SYNC_GITHUB_WINDOWS.ps1` included in ZIP after reviewing diff.
3. Run unit tests, static checks, desktop/mobile browser checks in CI.
4. Test read-only against a nonproduction Issabel before any writable AMI action.
5. Pilot each call-changing control with test queues and calls only.
6. Obtain explicit acceptance before stable release.

Inspired by FOP2 and commercial Asterisk dashboards, without copying their proprietary code or assets.
