# Compatibility and resource use / سازگاری و بار سرور

| Platform | Evidence | Acceptance still required |
|---|---|---|
| Asterisk 20.12.0 / Rocky 8.10 | Actual PBX integration, queue control and browser tests | Supervision audio and production-size traffic |
| Asterisk 18 | SIP/PJSIP/Local event parser fixtures | Actual installation, privileges, modules and audio |
| Asterisk 16 | SIP/PJSIP/Local event parser fixtures | Actual installation, privileges, modules and audio |
| Issabel 5 | Asterisk-compatible AMI adapter | OS/package-specific installation and end-to-end acceptance |
| Issabel 4 | Separate dashboard runtime supported architecturally | Actual host; use a sidecar host if modern Python is unsafe |
| SIP | Parser, hint resolution and real health inventory | Real SIP agent call/control scenarios |
| PJSIP / Local | Actual test PBX queues and endpoints | Each site's contexts and unusual endpoint naming |
| Python 3.11 | Local 224-test pytest suite + Linux deployment | Python 3.10/3.12 CI passed; installation acceptance still required |
| Docker | Configuration only | Image build, network and volume ownership validation |

No OS distribution or all-version compatibility guarantee is implied. Capability checks return unsupported/permission errors instead of inventing values. No SIP/PJSIP migration or dialplan change is performed.

## Resource design

A shared snapshot cache collects QueueStatus at most once per five seconds for ordinary viewing, regardless of browser count in one worker. Mutating controls request a fresh authorization snapshot. Concurrent cache misses coalesce; failures back off between 2 and 30 seconds. Snapshot AMI sessions disable unsolicited events. One bounded call/agent event listener tracks journeys. Health checks cache results for 30 seconds. Timeouts cap socket/action work; no shell command or CLI polling is used for normal monitoring.

A measured run of 100 HTTP operations requests with 20 concurrent clients completed in 8.078 seconds, p95 2.797 seconds, and caused two snapshot collections. This is a small test on an idle PBX, not a capacity guarantee. Slow AMI responses can still delay HTTP threads. Large queues, many controls, media supervision and alerts require site-specific load tests.

Use one worker/four threads, restrict optional probes, retain default polling and monitor CPU/RAM, AMI failures and HTTP latency. Runtime collection counters are available to administrators at `/api/runtime/metrics`. SaneQueue does not process the audio media path for ordinary monitoring. ChanSpy runs on Asterisk and has its own resource cost.

فارسی: کش مشترک، اتصال رویداد محدود، مهلت پاسخ و فاصله‌گذاری خطا برای کاهش بار اضافه شده‌اند. عددهای بالا نتیجهٔ محیط آزمایشی‌اند و تضمین عدم اختلال در همه سرورها نیستند. پیش از نصب عملیاتی، آزمون همان نسخه و بار واقعی لازم است.
