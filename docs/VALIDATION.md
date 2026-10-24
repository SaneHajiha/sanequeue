# Validation record · 2026-10-24

## Automated

221 pytest tests and 52 subtests passed on Python 3.11 (10.92 seconds). The unittest runner passed 219 tests (14.511 seconds); pytest additionally executes two parametrized backend tests. Coverage includes queue event variants for Asterisk 16/18/20, concurrent snapshot collection, failure backoff, scope/CSRF rules, driver resolution, last-administrator protection, duplicate phones, scoped planning, overlapping shifts and successful/rejected AMI responses.

The supplied archive's baseline had 33 failures and 10 errors among 230 tests. Tests with obsolete fixed beta versions/preview ports or assumptions that removed survey UI and unowned gates existed were migrated. Original copies are retained in `tests/historical/`; 31 obsolete assertions were retired. These counts do not mean the original 230 unchanged tests passed.

## Actual PBX

Rocky Linux 8.10, Asterisk 20.12.0, Python 3.11, two queues and three test endpoints. Live QueueStatus and optional health inventories succeeded. Pause/resume, penalty change/restore, dynamic add/remove, caller priority and specific synthetic caller hangup were checked against actual PBX state. Existing queue member state was restored. No external telephone number was called and no dialplan was modified.

An actual pause command exposed a response-type bug: the PBX changed state but HTTP returned 500. The handler now returns a Flask response and has a regression test. A browser sweep found missing headings for the new shift/directory views; fixed.

100 HTTP requests / 20 concurrent clients: 8.078 seconds total, p95 2.797 seconds, two AMI snapshot collections. This is not a production stress test.

Supervision: a listen Originate request received HTTP 202 / AMI acceptance. That does not prove audio. Manual listen/whisper/barge audio acceptance remains pending until explicitly confirmed.

## Browser

Persian RTL and English LTR pages, all 17 navigation views, synthetic demo screenshots and initial layout inspection were exercised in the in-app browser. Desktop content width did not overflow horizontally. Mobile-device and cross-browser certification remain pending. Screenshots contain synthetic data.

## Remaining gates

Real Asterisk 16/18 and Issabel 4/5 acceptance, SIP-agent control calls, supervision audio, notification delivery, Docker build, mobile layouts and production-volume testing. Planned transfer/parking/CRM/WebRTC/AI and historical reporting are not claimed complete.

فارسی: نتایج بالا فقط موارد آزموده‌شده را تأیید می‌کنند. تست صوت، نسخه‌های نصب‌نشده و بار عملیاتی هنوز نیازمند پذیرش مستقل‌اند.
