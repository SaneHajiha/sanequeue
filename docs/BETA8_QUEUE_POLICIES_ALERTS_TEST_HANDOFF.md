# SaneQueue 2.1.0-beta.8 — queue summary, per-queue alerts and staffing policies

**Status:** Local Windows ZIP only. The full beta.8 source is **not** pushed to this GitHub branch, and the existing PR should remain a documentation-only draft. The previous master is untouched.

## What changed in the beta.8 source

- Per-queue summary dialog from live QueueStatus: calls completed/abandoned, waiting, longest wait, average hold/talk, service level, ready/busy/paused/offline memberships. No fabricated historical statistics.
- Editable policies per queue: waiting > threshold, longest wait > N seconds, minimum ready, cooldown, fixed staffed roster, departure ceiling by percent and absolute count, minimum on-duty members.
- Configurable safe QueuePause reasons, including break, lunch, meeting, training, after-call, technical and survey. `survey` is a pause reason, **not** call routing to an IVR or a survey result.
- Supervisor grant policy (queue IDs + view/pause/membership/monitor/hangup/priority), integrated into API data/action checks. **Local demo auto-login still uses demo/admin**, therefore production real multi-user authentication remains unimplemented.
- Per-process action reservation that prevents two near-simultaneous departure actions from breaching the same quota based on stale AMI snapshots. Not distributed/authoritative against external PBX changes.
- Optional Bale Bot `sendMessage` adapter, disabled by default; token/chat ID read only from runtime environment. Alerts have transition dedup and cooldown. Optional 30-second in-process polling; no durable retry guarantees.
- Windows launcher on loopback **18886**. Previous queues and AMI configuration remain unchanged. An explicit Issabel queue visibility allowlist inherited from beta.7 hides unwanted `default`.

## Example: ten people and 50% limit

Set `roster_size=10`, `max_absent_percent=50`, `max_absent_count=5`, `min_on_duty=5`. Five pauses/removals are permitted from a fully present ten-person queue; the sixth is rejected by the local controller.

## Validation (2026-10-23)

- **84 selected offline Python unit/regression tests passed**, including simulated concurrent departure attempts.
- Python compile and JavaScript syntax passed.
- Jinja2 static template successfully rendered on mocked HTTP 200 with no duplicate IDs.
- **Browser visual integration could not run** because a local browser request was blocked by environment administrator restrictions.
- **Flask startup and real Asterisk write controls have not been verified** in this environment; missing Flask dependencies could not be fetched due DNS restrictions.
- Bale API request formation was tested with mock response only; no real message delivered.
- ZIP integrity passed; sensitive AMI password patterns not found.

The local ZIP includes `START_HERE_18886_FA.md`, `docs/QUEUE_ALERTS_STAFFING_BALE_FA.md`, `TEST_REPORT_BETA8.md` and source/tests.

**Do not deploy to a customer/production PBX.** Required before stable release: real user authentication, role-based sessions, distributed quota arbitration, robust notification outbox, real PBX integration tests and security review. Historical reporting remains deferred by user request.
