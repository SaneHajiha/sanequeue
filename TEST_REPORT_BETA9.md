# SaneQueue 2.1.0-beta.9 validation

Test date: 2026-10-23.

- 78 existing and new selected Python unit tests passed (QueueStatus, AMI parsing, scoped controls, queue policies, outbound survey reasons, step diagnostics).
- Node JavaScript syntax and Python compilation passed.
- Chromium offline with explicitly mocked APIs: six live KPI cards, queue summary with 10 metrics, per-queue policy save, supervisor grant UI, six-step diagnostic, outbound-survey Pause reason modal, desktop/mobile with zero page JS errors and zero horizontal overflow.
- The browser test used a locally rendered Jinja template via `page.set_content` because direct localhost navigation was blocked by environment administrator settings. Browser preview **does not prove Windows+Flask startup**.
- Real Asterisk connection for *this beta.9*, SIP/PJSIP write actions and WebRTC/audio remain **not tested**. An earlier independent QueueStatus login on user's lab system was successful.
- README includes precise QA steps and the independent safe CLI.
- Historical reporting deferred. No secrets, customer lists or credential material intentionally included.
