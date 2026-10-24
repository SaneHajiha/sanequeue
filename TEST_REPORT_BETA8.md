# Test Report — SaneQueue 2.1.0-beta.9

- Selected offline Python unit/regression tests: **84 passed** (network mocked; no real PBX effects).
- Python bytecode compilation of app, scripts, tests: **passed**.
- Node.js JavaScript syntax: **passed**.
- Jinja2 template mock HTTP response: **HTTP 200**, new policy section and queue summary dialog present, no duplicate DOM IDs in rendered HTML.
- Browser visual E2E test: **blocked by runtime administrator at 127.0.0.1**, therefore **NOT PASSED / not claimed**.
- Flask runtime on Windows: **not available in this model container** (Flask dependencies could not be installed due DNS). Must be tested on user's Windows environment.
- Bale Bot API integration: **request encoding tested with a mocked network response, no real message sent**.
- Asterisk AMI QueuePause/QueueRemove/Originate etc.: **not executed against live PBX in this turn**.

Critical limitation: local preview auto-logs into `demo` as administrator; full user authentication, secure policy management, distributed/concurrent operation controls, durable notification delivery, and production monitoring are still separate work items.
