# beta.23 acceptance and remaining scope · 2026-10-25

این نسخه برای پایلوت کنترل‌شده آماده‌سازی شده است؛ «۱۰ از ۱۰ در همه محیط‌ها» یا «صفر باگ ممکن» ادعا نمی‌شود. نتیجهٔ فنی زیر از آزمایش واقعی و آزمون خودکار است. تأیید نهایی تصویری نسخهٔ جدید هنوز به‌دلیل پاسخ‌ندادن ابزار مرورگر ثبت نشده است.

## Regression and live acceptance

- Windows Python 3.11: **326 passed, 4 skipped, 79 subtests passed**, 153.63 seconds. Redis-dependent tests skipped locally are enabled in GitHub CI. Historical tests are excluded deliberately.
- Actual JavaScript executed against an authenticated SSR fixture: six metrics, queue cards, capacity comparison, eight wallboard totals, independent rule switches, profile entry and wildcard RBAC action dialog passed; no POST requests occurred. This DOM test does not verify CSS rendering or accessibility.
- Laboratory Rocky Linux 8.10 / Asterisk 20.12.0: pause/resume on both queues, discovered internal dynamic add/remove, trunk rejection, durable pause-reason activity and profile fields passed. Asterisk's process did not restart.
- Unit coverage includes Tehran day boundaries, disconnected observation gaps, bounded disk-failure retry, late writer rejection, current phone-assignment clipping, exact directory scope, external dial allowlists and IVR/hangup evidence.
- Earlier transfer, parking, pickup and partial supervision-audio acceptance are retained as historical evidence in [beta.22](AUDIT_BETA22.md); they are not newly repeated microphone-isolation tests.

## Bounded Local queue load

Six virtual CPUs, 8 GB memory; 20 concurrent HTTP readers, 100 requests at each stage. Queue agents were temporarily paused for this test and restored afterwards. The generator created Local queue callers and no external telephone destinations.

| Waiting calls | System CPU | HTTP p95 | HTTP errors | Extra HTTP-triggered AMI collections |
|---:|---:|---:|---:|---:|
| 10 | 9.18% | 0.6176 s | 0 | 0 |
| 25 | 12.29% | 0.8202 s | 0 | 0 |
| 50 | 15.54% | 1.0716 s | 0 | 0 |
| 100 | 22.09% | 1.5660 s | 0 | 0 |

At 100 waiting callers: collector 0.46% of one CPU core / 40.60 MB RSS; web 52.00% of one core / 81.58 MB RSS; Asterisk 49.96% of one core / 146.91 MB RSS. Available memory 6551.8 MB. All generated channel legs were removed; the collector stayed connected. Test elapsed 72.38 seconds. [Machine-readable measurements](evidence/beta23-local-load.json).

This measures monitoring and synthetic waiting-call handling, **not 100 simultaneous RTP conversations**, codec/transcoding load or long-duration production soak. The final small privacy/writer-ordering and UI race fixes were regression-tested after this load run; the full load was not repeated for each edit.

## Findings corrected

1. Wildcard role-based controls incorrectly blocked browser actions despite valid backend permissions; corrected and live-tested.
2. Saving queue alerts could imply mandatory staffing with an empty roster; staffing is now explicit and independent.
3. Wallboard totals lived outside the fullscreen boundary, and light-theme text overrides reduced dark-card readability; summary and theme rules corrected in source.
4. Empty dashboard comparison area, scattered action controls and inconsistent queue identities; compact labelled comparison bars, reason cards and stable identity colors added.
5. Stale queue-option responses could replace the selected queue's targets; requests are sequenced and submission stays disabled until the current queue is loaded.
6. Personal activity could expose a prior owner of an extension; new assignments have a timestamp and self-service history is clipped to it.
7. Local channel hangup order could be mistaken for call initiator evidence; unknown stays unknown, with explicit queue-completion reason shown separately.
8. Activity writes needed off-loop batching, storage bounds, reconnect boundaries and rejection of late older generations; these paths now have regression coverage.

## Coverage gaps and strict assessment

| Area | Current assessment | Outstanding evidence |
|---|---|---|
| Monitoring and scoped controls | 8/10 for a controlled pilot | Real RTP concurrency, long soak, installation matrix |
| Daily activity correctness | 8/10 | Site timezone/process restart acceptance; not payroll or complete historical reporting |
| UI and accessibility | Provisional 7/10 | Fresh screenshots, light/dark/fullscreen/mobile review and assistive technology |
| Universal production readiness | Not certified | Actual Issabel 4/5, Asterisk 16/18/20 and SIP/PJSIP host matrix |

The Product Design workflow used user-supplied reference images and pre-change browser screenshots. New screenshot capture then repeatedly timed out despite the browser being visible. Existing manual illustrations are labelled examples from earlier builds; they are not beta.23 after-images. No final visual approval is claimed.

The optional Codex Security diff scan did not start: its native helper rejected a valid worktree, while a separate diagnostic lacked owning-thread context. There is no scan ID or formal scanner report. Ordinary code/regression review above is not represented as that scan. The requested new Gemini cross-check was also not completed while Chrome control was unavailable; no independent approval is claimed.

## Operational boundaries

Daily activity is observation-based, bounded to 90 days and roughly 500,000 intervals; gaps are excluded, simultaneous queue memberships are not summed into work hours. It does not reconstruct prior CDR/queue_log history. IVR requires standard `ivr-*` contexts and collector dialplan-read permission; arbitrary in-call DTMF/AppData is excluded. Directory matching is exact after phone normalization, within the authorized queue. External saved-contact dialing is disabled by default and requires explicit per-queue authorization and a working outbound dialplan.

Emergency stop: `sudo sanequeuectl disable`; restore: `sudo sanequeuectl enable`. These affect the module services, not Asterisk. First install prompts for an admin password; upgrades keep existing credentials. [English installation](INSTALL.md) · [نصب فارسی](INSTALL.fa.md).
