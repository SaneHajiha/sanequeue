# Collector pilot validation — beta.20

Date: 2026-10-24. Baseline: beta.19, master `2df2dc4e04648abed878425a10ea15ca84c87316`.

Final local run: Python 3.11 / Windows, 247 passed, 2 integration tests skipped because a dedicated local Redis was not configured, 66 subtests passed, no failures or warnings (15.11 seconds). Final server run: Python 3.11 / Rocky Linux, 249 passed, 66 subtests passed, no failures or skips (9.77 seconds), with an isolated real Redis 5.0.3 instance. Both JavaScript syntax checks passed.

During the critique loop, repeated full runs exposed a shutdown race: cancellation during a completed Ping could be swallowed by `asyncio.wait_for`. This was fixed using a cancellation-preserving deadline helper. Regression tests include 100 cancellation/completion races, 30 collector shutdowns near initial Ping, pending-request timeout/disconnect cleanup and cancellation at socket-open completion. Five complete Windows runs passed consecutively after the race fix; one final full run passed after adding socket cleanup coverage.

Live shadow test, Asterisk 20.12.0:

| Check | Observed result |
|---|---|
| Two collectors, same PBX namespace | One initial AMI connection; standby did not connect |
| 100 concurrent private Redis reads | 0.106 s; zero extra AMI snapshots |
| Expired Redis owner | Cannot publish, renew or remove a replacement owner's lease |
| Interrupt only the collector socket | Reconnect, resync and new generation confirmed |
| Stop active collector | Standby took over |
| Stop both collectors | State read as stale; zero collector sockets remaining |
| Final cleanup | Temporary Redis and shadow collectors stopped; distro Redis not enabled |

The shadow test did not change PBX configuration, reload/restart Asterisk or issue call-control actions. The existing dashboard remained on its legacy adapter. Three raw queues include two operational queues and the PBX default queue; display filtering is separate.

This is a short, idle-server integration test, not a large-scale capacity benchmark. Redis 7 CI exercises the same Lua integration tests in the Python 3.10/3.11/3.12 matrix. No real Asterisk 16/18 or Issabel 4/5 environment was provisioned. Audio isolation, WebSocket, complete historical reconstruction, native Issabel SSO and multi-process command reservations remain open gates. See the [scored audit](AUDIT_20261024.fa.md) and [architecture](REALTIME_ARCHITECTURE.md).
