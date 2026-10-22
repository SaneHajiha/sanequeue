<p align="center"><img src="./assets/sanequeue-header.svg" alt="SaneQueue — Asterisk and Issabel live call center operations" width="100%" /></p>

# SaneQueue · Live Call Center Operations

**فارسی:** [راهنمای فارسی](README.fa.md) · [Live monitoring matrix](docs/LIVE_MONITORING_MATRIX.fa.md) · [Asterisk access (FA)](docs/ASTERISK_ACCESS_GUIDE.fa.md) · [AI roadmap (FA)](docs/AI_LIVE_COPILOT.fa.md)

SaneQueue is an independent, open-source Persian/English **Asterisk / Issabel real-time queue monitoring and supervisor console** built on the MIT-licensed [QPanel](https://github.com/roramirez/qpanel).

> **Development status: 2.0.0-beta.3 local preview.** The recovered beta source is currently distributed as a local ZIP, **not yet synced to this GitHub branch**. The GitHub default branch remains an older QPanel-based codebase. No production deployment or Asterisk live control has been validated.

## Goals

- Queue health, waiting callers, agent availability, current calls, short-lived alerts and wallboard views.
- Supervisor actions: pause/resume, queue membership, caller priority and monitored intervention with role-based permissions.
- Accessible responsive UI, genuine Persian RTL and English, dark theme, audit events, queue scopes.
- Future: extension/trunk state, transfers, parking, browser notifications and optional AI live insights.
- **Deferred:** historical reporting, periodic reports and Excel export.

## See it locally

Download the current Windows beta archive from the release handoff, extract to a **fresh** folder, then launch `RUN_DEMO_WINDOWS.bat`.

Open **http://127.0.0.1:8766/operations**; the older preview may still be on 8765.

Verify **http://127.0.0.1:8766/__sanequeue__/build** reports `2.0.0-beta.3`. The demo uses *fake calls* and blocks all PBX-changing actions.

[Windows troubleshooting (FA)](docs/WINDOWS_BETA3_GUIDE.fa.md)

## Security and release process

Do **not** connect an operational PBX or enable AMI writes during preview. Use a temporary read-only AMI account restricted to a dedicated tester host in a private network or SSH tunnel. See [safe test guidance (FA)](docs/ASTERISK_ACCESS_GUIDE.fa.md).

New work is reviewed in [PR #1](https://github.com/SaneHajiha/sanequeue/pull/1) and development branch `work-recovery-2026-10-22`; `master` stays untouched until complete sanitized source, CI, and PBX test-call validation are reviewed.

## Project status

| Track | State |
|---|---|
| Local beta UI and fake-data preview | Built; needs testing on user's Windows host |
| Three static beta.3 checks | Passed |
| Nineteen earlier mocked tests | Previously passed; **not rerun in current environment** |
| Live Asterisk/AMI tests | Not performed |
| Complete beta.3 code pushed to GitHub | **Not yet** |
| GitHub review documentation | Published to development branch |

## License and credits

Copyright and license notices of upstream [QPanel](https://github.com/roramirez/qpanel) are retained. Released under the repository's MIT license. No proprietary vendor source code or visual assets from FOP2 or VoiPing are used.

Maintainer: **Sane Hajiha** — IT & Network Infrastructure Manager / Consultant · [Website](https://sanehajiha.ir) · [LinkedIn](https://www.linkedin.com/in/sane-hajiha-544948199).
