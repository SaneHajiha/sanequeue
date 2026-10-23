# SaneQueue 2.1.0-beta.4 — All subpages UX & test handoff

**Status: local test ZIP only.** The GitHub development PR remains documentation-only; full beta.4 source has **not** been pushed to this branch. Do not merge as a working release.

## Implemented locally

- Dedicated dark RTL/EN operational hero and four real-snapshot-derived metrics for all 12 subpages: queues, active calls, waiting room, agents, queue presence, PBX, supervisor actions, wallboard, alerts, audit, AMI settings and capability catalog.
- Visual improvements: queue comparison bars, longest-current-wait spotlight, responsive agent roster tiles, readiness/presence legend, explicit locked/armed controls, wallboard statistics, alert severity segmentation and device-responsive layouts.
- No fake historical charts. Existing Asterisk 20 read-only QueueStatus adapter and AMI options preserved from beta.3.
- A control UI action can proceed only when data source is validated live AMI AND the 30-minute test gate is armed; independent backend test queue/agent restrictions remain intact.
- Windows launcher on loopback port 18882 with persistent startup diagnostics.
- Persian setup / AMI ACL guide, feature-status matrix, explicit test report and a read-only comparative QA tool.

## Validation

- 39 selected Python unit/security regressions passed.
- Python compileall / Node JS syntax passed.
- Chromium mocked API: all twelve views, queue lanes, agent tiles, waiting spotlight; 390, 768 and 1300 px widths with no horizontal overflow and zero browser JS errors.
- The full legacy test suite was NOT green here because Flask/Asterisk dependencies were missing and old version assertions were stale. This is **not** production validation.
- **No live Asterisk write command was sent by the assistant.** Actual QueuePause/QueuePenalty/Hangup/Originate tests require a supervised consenting test call.

## Recommended test AMI identities

Read-only test account: `read = agent,call,system,reporting`, `write =`.
Temporary supervisor test identity: `read = agent,call,system,reporting`, `write = agent,call,originate`.
ACL only allows PBX loopback via SSH tunnel or an explicit host /32 workstation IP on an isolated test LAN; never blanket `permit 0.0.0.0/0`, `write = all`, `command` or `config`. Asterisk AMI permissions are class-wide, not scoped to Queue 8001. Rotate all credentials previously shared in chat.

## Unimplemented / deferred

Blind/attended transfers, park/pickup, conference, full PBX extension presence and trunk/RTP quality monitoring, WebRTC, CRM/contacts, production multiuser RBAC, optional AI copilot. Historical reports are deferred by product scope.

See the local ZIP's `START_HERE_18882_FA.md`, `docs/AMI_PRIVILEGE_TEST_FA.md`, `docs/FEATURE_STATUS_FA.md`, and `TEST_REPORT_2026-10-23.md`.
