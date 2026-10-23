# SaneQueue v2.1.0-beta.7 — Issabel-managed queue visibility and PJSIP AMI diagnosis

**Handoff date:** 2026-10-23. The complete application source for beta.7 is currently in a local Windows ZIP, **not pushed to GitHub**. The existing development PR remains documentation-only.

## Findings from test Asterisk 20.12.0

- `PJSIPShowEndpoints` and `PJSIPShowContacts` are registered and return `[Privilege] system,all` from `manager show command`.
- `module show like res_pjsip_manager` returns no matching module, but it does **not** prove the AMI Actions are absent; the above command proves the Actions are present.
- Temporarily adding `system` to `write` on a **separate, IP-restricted lab-only AMI account** can make the PJSIP Actions available; `write=system` also grants unrelated system-class Actions and is not appropriate as the default production monitoring permission. Avoid `write=all` or `write=command`.
- `asterisk -rx 'queue show'` previously listed both `8001` and `default`. The `default` queue is a real Asterisk queue, not merely a SaneQueue mock. Whether it originates from a sample `queues.conf`, a custom include or GUI-generated Issabel config must be checked read-only before any PBX deletion.

## Local beta.7 changes

- Read `QueueStatus` normally, then **filter only the app data** with explicit Issabel GUI queue IDs. Initial allowlist: `8001`. `default` is hidden from live panels, KPIs, alarm calculations and supervisor queue options.
- New setting: **Issabel queue IDs** (comma-separated list such as `8001,8002`); `*` here explicitly re-enables raw Asterisk-all mode for diagnostics.
- Changing queue allowlist immediately disarms any previously armed supervisor test-control scope. A queue outside the allowlist cannot be newly armed for calls.
- Queue `*` in the AMI read scope still requests all from Asterisk. The separate Issabel queue ID setting controls what appears to the operator; filtering cannot infer GUI provenance from AMI events alone.
- Updated 2.1.0-beta.7 version/UTF-8 Windows launcher on local port **18885**.
- Includes a read-only Asterisk queue-origin inspection script and Persian setup guide.

## Validation

- 55 selected Python unit/regression tests passed: queue filtering, AMI read parsing, health response redaction, scoped write guard, reference UI/launcher checks.
- Python compilation, JavaScript syntax and ZIP integrity passed.
- Flask browser startup **not** executed in this environment (Flask dependencies absent); live PBX testing still must be performed on the user's Windows test host.
- Production deployment, all call controls, and complete contact center feature set remain unverified or under development.
