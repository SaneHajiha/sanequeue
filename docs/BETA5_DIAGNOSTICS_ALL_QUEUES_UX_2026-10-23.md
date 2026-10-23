# SaneQueue 2.1.0-beta.5 — local test handoff, 2026-10-23

**Status:** complete source in local Windows ZIP only; NOT pushed to GitHub. Development PR #1 remains documentation-only. This is not a production-ready release.

## Resolved in local ZIP
- AMI `ListCommands` matrix identifies Actions authorized for the current AMI user, instead of collapsing permission/module/timeout issues into one message.
- Health inventory now distinguishes `action_permission_denied`, `action_or_module_unavailable`, `event_list_incomplete`, `timeout`, and `connection_lost`, with caller IDs and SIP URIs redacted.
- Read-only probes: CoreShowChannels, PJSIPShowEndpoints, PJSIPShowContacts, PJSIPShowRegistrationsOutbound, ParkedCalls.
- Queue `*` can be selected to read ALL queues through QueueStatus; UI supports any current read queue.
- Mutating actions are **not** globally unrestricted. A manager must explicitly select a currently verified queue, type `ENABLE <queue>`, and arm a 30-minute scope restricted to existing queue member interfaces. This is for a test PBX only.
- Consistent light/dark theme refinement, six colored KPIs, queues/agents/waiting panels moved above live trend charts, stronger contrast and mobile layouts.
- Port **18883**, isolated from earlier versions. Local read-only audit runner writes redacted `safe_live_capabilities.json`.

## Tests
- 25 selected offline unit/regression tests passed.
- Python compilation, JavaScript syntax validation and ZIP integrity passed.
- Chromium mock preview: 12 subpages, 6 KPI cards and 390/768/1300px layouts with no horizontal overflow or page errors.
- **No live test PBX command was sent**; login, privileges and write actions must be confirmed in the owner's local environment.
- Entire legacy suite and production security/load tests have not passed; no production deployment.

## Recommended test account
Rotate previously disclosed secret. For a temporary lab-only account on Asterisk 20:

```ini
[sq_supervisor_test]
secret = STRONG_NEW_ASCII_PASSWORD
deny = 0.0.0.0/0.0.0.0
permit = 127.0.0.1/255.255.255.255
read = agent,call,system,reporting,command
write = agent,call,originate,reporting
```

If direct LAN access is necessary, add only the user's workstation IP/32. The distinction between `read=command` (receiving COMMAND-class events) and `write=command` (able to execute powerful CLI actions) matters. Avoid `write=command`, `write=all`, `permit=0.0.0.0/0`, and public AMI exposure.

For exact granted Actions use Asterisk 20 `manager show command ACTION` and AMI `ListCommands`; don't guess capability from the class alone.

Pending: real PBX tests, full production role enforcement, SIP trunk/bridge correlation, transfer/Park/Pickup implementations, WebRTC, CRM and AI. Historical reports deferred.
