# SaneQueue 2.1.0-beta.23

اصلاح کنترل صف‌ها، نمای سرپرست، پروفایل و وضعیت شخصی، کارکرد روزانه، قوانین مستقل هر صف و دفترچهٔ قابل استفاده. این انتشار بتا برای پایلوت کنترل‌شده است؛ تأیید تصویری نهایی و آزمون روی نسخه‌های مختلف سرور هنوز باقی است.

- Fixed wildcard RBAC queue controls and optional staffing enforcement.
- Supervisor fullscreen summary, stable queue colors, small waiting-history charts and a labelled capacity comparison.
- Custom pause-reason cards, independent per-queue count/time thresholds and dynamic internal membership management.
- First/last name, assigned phone, picture/password, personal queue status, click-to-call and daily observed activity with phone-assignment privacy.
- Queue-scoped directory caller names and explicitly enabled saved-contact outbound dialing.
- Bounded IVR selections and evidence-based queue-leg hangup party; uncertain outcomes stay unknown.
- Off-loop bounded activity recording, reconnect-gap handling and stale-response/writer protection.

Local regression: **326 passed, 4 skipped, 79 subtests**. Actual PBX controls passed without restarting Asterisk. A bounded 100-Local-caller test produced zero HTTP errors and zero additional browser-triggered AMI collections, with 22.09% total CPU and 1.566-second HTTP p95. This is not a 100-RTP-stream benchmark.

Fresh visual sign-off, formal scanner output and a new Gemini review are **not** claimed: browser capture/control and the optional security scan helper were unavailable. Historical screenshots remain illustrative. See the [audit, scores and limits](AUDIT_BETA23.md), [English guide](USER_GUIDE.en.md), [راهنمای فارسی](USER_GUIDE.fa.md), [installation](INSTALL.md) and [نصب فارسی](INSTALL.fa.md).

There is no shared default admin password. Emergency module stop: `sudo sanequeuectl disable`; restore: `sudo sanequeuectl enable`. Real media acceptance, site dialplans, long soak and the Issabel/Asterisk deployment matrix remain necessary before production rollout. Reporting, WebRTC and AI remain separate work.
