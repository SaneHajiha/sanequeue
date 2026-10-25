<p align="center"><img src="docs/images/banner.jpg" alt="SaneHajiha — Open-source VoIP & Contact Center Tools" /></p>

# SaneQueue

Persian and English live queue monitoring for Asterisk-based contact centers. MIT licensed.

**2.1.0-beta.24 · Redis and WebSocket monitoring beta · [راهنمای فارسی](README.fa.md)**

![English operations dashboard with synthetic demonstration data](docs/images/dashboard-en.png)

## Automatic installation, scoped controls and contextual help

The standard installer now connects the existing dashboard to Redis and an authenticated ASGI WebSocket gateway. A separate read-only AMI collector handles queue events independently of browser count. See [deployment](docs/REALTIME_DEPLOYMENT.md), [architecture](docs/REALTIME_ARCHITECTURE.md), [beta.24 audit and scores](docs/AUDIT_BETA24.md) and [admin password recovery](docs/ADMIN_ACCESS.md). Reporting remains the next phase.

## What you can use

- Live queues, waiting callers, agent availability, queue counters and service level.
- Persian RTL / English LTR, local fonts, dark/light appearance, search, queue filters, wallboard and browser-observed live charts.
- Scoped accounts, supervisor phones, per-queue permissions, pause reasons and minimum staffing rules.
- Role-authorized pause/resume, penalty, dynamic membership, caller priority and hangup controls with CSRF checks and audit records.
- SIP/PJSIP internal-phone and trunk inventory, observed RTCP metrics, active channel and parking inventory, capability detection.
- Live call journey events, threshold alerts, Telegram and Bale notifications, queue directory and shift planning with overlap validation.
- Persistent collector mode: Redis-only normal reads, WebSocket push, scoped exact call targets, durable command/capacity state and optional alert outbox. Legacy five-second snapshots remain an explicit rollback mode.

Listen/whisper/barge requests use ChanSpy and a configured supervisor extension. AMI acceptance is **not audio confirmation**. These controls remain beta and require a manual audio acceptance test on each installation. Transfer, park/retrieve and pickup have now passed test-PBX telephone acceptance; they remain installation-specific beta controls. CRM, WebRTC, AI and historical reports remain deferred. See the [feature matrix](docs/FEATURES.md).

## Install and operate

[Persistent mode setup](docs/REALTIME_DEPLOYMENT.md) · [Base installation](docs/INSTALL.md) · [Compatibility and performance](docs/COMPATIBILITY.md) · [User guide](docs/USER_GUIDE.md) · [Validation evidence](docs/VALIDATION.md) · [Changelog](CHANGELOG.md) · [Security](SECURITY.md) · [Contributing](CONTRIBUTING.md)

```bash
git clone https://github.com/SaneHajiha/sanequeue.git
cd sanequeue
sudo bash scripts/install.sh
```

The installer reuses or downloads isolated Python 3.10–3.12, provisions a private Redis instance and two restricted local AMI identities, and installs the collector, gateway and inventory timer. It asks you to choose the initial administrator password and panel origin; there is no shared default password. Queues and internal phones are discovered automatically. Existing accounts are preserved on upgrade. It reloads AMI configuration without restarting Asterisk. See [installation and rollback](docs/INSTALL.md).

Each of the 17 menu sections includes collapsible Persian/English help. [فارسی](docs/USER_GUIDE.fa.md) · [English manual](docs/USER_GUIDE.en.md). Roles, allowed menus and per-queue operations are checked independently by the server. Users can update their own name, phone, picture and password from the avatar button.

## Verified scope

See [beta.24 validation](docs/AUDIT_BETA24.md) for automated tests, actual Telegram/Bale delivery, real RTCP observations and a bounded 100-concurrent-Local-call test. That load test does **not** certify 100 SIP/RTP audio calls. Actual installation was exercised on Rocky Linux 8.10 / Asterisk 20.12.0; Asterisk 16/18 event fixtures do not establish complete Issabel 4/5 installation compatibility. This remains a beta release.

Current help screenshots use the laboratory PBX; older demonstration screenshots use synthetic data. Historical notes are retained for provenance and do not override the current installation guide.

## Attribution

Third-party copyright and license notices are preserved in [LICENSE](LICENSE) and [NOTICE](NOTICE).
