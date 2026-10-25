# SaneQueue 2.1.0-beta.22

نسخهٔ پایلوت مانیتورینگ برای نصب کنترل‌شده و آزمون روی سرورهای هدف. مستندات فارسی و انگلیسی همراه با تصویر داخل مخزن هستند.

Monitoring installation pilot for controlled target-server acceptance.

- Automatic isolated installation, restricted collector/control AMI identities, private Redis and sanitized endpoint discovery.
- Enforced roles, selected menus and queue/action permissions; personal password/phone/avatar and organization name/logo.
- Queue-specific count/time alerts, Telegram/Bale delivery, supervisor fullscreen wallboard and improved light/dark charts.
- Emergency disable/enable/uninstall with private backup and AMI configuration restoration on removal failure; no Asterisk restart.
- Independent module review and regression fixes for expired AMI replies, session growth, branding validation and identity lifecycle.
- Configurable root-owned exact internal-context allowlist for customized dialplans.

Validation: 317 tests passed on Python 3.10, 3.11 and 3.12; release publication repeats the Python 3.11 suite with Redis. Live laboratory acceptance covered scoped queue controls, transfers, park/retrieve, pickup, RTCP reception and install/remove/reinstall with unchanged Asterisk process. The bounded 100 Local-call test had no HTTP errors, 19.19% total CPU and 1.4563-second HTTP p95; it is not a 100-stream RTP benchmark.

This prerelease does not certify all Issabel/Asterisk versions or guarantee absence of every defect. Target acceptance includes real media/recording/supervision and viewer load, microphone-equipped directional audio tests, HTTPS/site dialplans and assistive technology. Historical reporting, browser softphone and AI remain separate work.

Installation: [English](https://github.com/SaneHajiha/sanequeue/blob/v2.1.0-beta.22/docs/INSTALL.md) · [فارسی](https://github.com/SaneHajiha/sanequeue/blob/v2.1.0-beta.22/docs/INSTALL.fa.md). Evidence: [audit](https://github.com/SaneHajiha/sanequeue/blob/v2.1.0-beta.22/docs/AUDIT_BETA22.md) · [independent review](https://github.com/SaneHajiha/sanequeue/blob/v2.1.0-beta.22/docs/INDEPENDENT_REVIEW_BETA22.md).

Emergency stop on the PBX: `sudo sanequeuectl disable`; restore with `sudo sanequeuectl enable`. First installation asks for the administrator password; there is no shared default password.

Published ZIP/tar.gz artifacts contain tracked public source only. `SHA256SUMS` verifies downloaded artifact bytes; it is not an independent signature or complete supply-chain guarantee.
