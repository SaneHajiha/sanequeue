# SaneQueue beta.16 — test and feature preservation report

Read-only event listener; no AMI call-changing commands introduced.

36 selected Python regression tests and offline Chromium page checks at 390, 768, 1280, 1650px passed (no browser JS errors or full-page horizontal overflow).

See `tests/test_beta16_call_journey.py` for tested blind-transfer lifecycle, attended-transfer no false success, refused transfer, end-of-call only after all observed channel legs end, data redaction and queue authorization.

Old Dashboard, Queue Monitoring, Active Calls, Waiting Calls, Agents, Wallboard, Settings, Alerts, Users and permission UI are retained. The 8 main menu entries are not increased: call journey is embedded in existing monitoring views.

Still pending: actual PBX AMI event stream validation, blind/attended and PBX native transfer interoperability, verified trunk detection, reconnect gaps, all dependency integration tests, long-term storage and multi-worker state.
