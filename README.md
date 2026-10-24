<p align="center"><img src="docs/images/banner.jpg" alt="SaneHajiha — Open-source VoIP & Contact Center Tools" /></p>

# SaneQueue

Persian and English live queue monitoring for Asterisk-based contact centers. MIT licensed.

**2.1.0-beta.21 · Redis and WebSocket monitoring beta · [راهنمای فارسی](README.fa.md)**

![English operations dashboard with synthetic demonstration data](docs/images/dashboard-en.png)

## Redis-backed monitoring and strict audit

The opt-in persistent mode now connects the existing dashboard to Redis and an authenticated ASGI WebSocket gateway. A separate read-only AMI collector handles queue events independently of browser count. See [deployment](docs/REALTIME_DEPLOYMENT.md), [architecture](docs/REALTIME_ARCHITECTURE.md), [beta.21 audit and scores](docs/AUDIT_BETA21.md) and [admin password recovery](docs/ADMIN_ACCESS.md). Reporting remains the next phase.

## What you can use

- Live queues, waiting callers, agent availability, queue counters and service level.
- Persian RTL / English LTR, local fonts, dark/light appearance, search, queue filters, wallboard and browser-observed live charts.
- Scoped accounts, supervisor phones, per-queue permissions, pause reasons and minimum staffing rules.
- Staged pause/resume, penalty, dynamic membership, caller priority and hangup controls with CSRF checks and audit records.
- SIP/PJSIP endpoint and registration inventory, active channel and parking inventory, capability detection.
- Live call journey events, threshold alerts, optional Bale notifications, queue directory and shift planning with overlap validation.
- Persistent collector mode: Redis-only normal reads, WebSocket push, scoped exact call targets, durable command/capacity state and optional alert outbox. Legacy five-second snapshots remain an explicit rollback mode.

Listen/whisper/barge requests use ChanSpy and a configured supervisor extension. AMI acceptance is **not audio confirmation**. These controls remain beta and require a manual audio acceptance test on each installation. Transfer, park/retrieve and pickup have now passed test-PBX telephone acceptance; they remain installation-specific beta controls. CRM, WebRTC, AI and historical reports remain deferred. See the [feature matrix](docs/FEATURES.md).

## Install and operate

[Persistent mode setup](docs/REALTIME_DEPLOYMENT.md) · [Base installation](docs/INSTALL.md) · [Compatibility and performance](docs/COMPATIBILITY.md) · [User guide](docs/USER_GUIDE.md) · [Validation evidence](docs/VALIDATION.md) · [Changelog](CHANGELOG.md) · [Security](SECURITY.md) · [Contributing](CONTRIBUTING.md)

```bash
git clone https://github.com/SaneHajiha/sanequeue.git
cd sanequeue
sudo env PYTHON=python3.11 bash scripts/install.sh
```

The installer requires an isolated Python 3.10–3.12 runtime. Never replace Issabel's system Python. It creates a dedicated OS user, asks for AMI credentials and a dashboard password, stores only the password hash, and binds the service to localhost. Review the install guide before starting it. No dialplan or SIP endpoint configuration is changed.

## Verified scope

The beta.19 baseline passed 224 tests. Collector pilot validation is recorded in [the current audit](docs/AUDIT_20261024.fa.md). Live monitoring and queue controls were exercised on a test PBX running Rocky Linux 8.10 and Asterisk 20.12.0. Asterisk 16/18 event variants are fixture-tested; Issabel 4/5 and all customer installations are not universally certified. Docker configuration is supplied but has not been built in this validation environment. This release is beta, with explicit remaining acceptance work.

Screenshots use synthetic data. Historical notes from earlier previews remain under `docs/` and root release notes for provenance; this README and the beta.18 validation guide describe the current release.

## Attribution

Third-party copyright and license notices are preserved in [LICENSE](LICENSE) and [NOTICE](NOTICE). SaneQueue is independent of Issabel, Asterisk, FOP2 and VoiPing. No proprietary assets or source code from those products are included.
