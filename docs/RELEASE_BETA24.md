# SaneQueue 2.1.0-beta.24

اصلاح نهایی چیدمان پس از بررسی تصویری: سه ستون دسکتاپ، کارت صف بدون بیرون‌زدگی، نوار پروفایل قابل استفاده در موبایل و خروج درست از تمام‌صفحهٔ مرورگر داخلی. این نسخه شامل همهٔ امکانات مانیتورینگ beta.23 است.

- Keeps all three desktop monitoring panels aligned and removes unused legacy queue-card columns.
- Wraps mobile header controls without clipping the profile button at 320/390 px.
- Corrects fullscreen toggle labels and fallback exit, including Escape; supervisor totals stay within the stage.
- Includes stable queue identity colors, mini charts, scoped controls, per-queue rules, personal status/profile/dialing, directory integration and daily observed activity from beta.23.
- Bilingual guides, current visual evidence and explicit pilot limitations are published with the source.

Validation inherited from beta.23: 326 local tests and 79 subtests, successful Python 3.10–3.12 Redis CI, actual scoped queue controls without an Asterisk restart, and 100 Local waiting callers with zero HTTP errors. The release workflow repeats tests for beta.24. A Local load generator does not certify 100 RTP calls.

[Visual audit and screenshots](AUDIT_BETA24.md) · [Monitoring/load evidence](AUDIT_BETA23.md) · [Install](INSTALL.md) · [نصب](INSTALL.fa.md).

This remains a controlled-pilot prerelease. Final dark-layout/accessibility sign-off and the new Gemini/formal scanner reviews remain unverified after recurring tool failures. Actual Issabel/Asterisk target versions, media directionality and long-duration production-like load still require site acceptance.

Choose the first admin password during installation; upgrades preserve it. Emergency module stop: `sudo sanequeuectl disable`; resume: `sudo sanequeuectl enable`. Asterisk is not restarted by this module operation.
