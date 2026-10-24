
# SaneQueue beta.6 — Controlled Asterisk 20 trial

This build is an **offline-test staging release**, not production-ready. It preserves the existing operations dashboard but adds a manually armed, 30-minute test-control guard scoped to queue `8001`, agent interfaces `Local/100@from-queue/n` and `PJSIP/100`, and monitoring destination `PJSIP/101`. Windows demo binds only to loopback port `18878`; AMI is accessed through an SSH tunnel to `127.0.0.1:15038`.

| Operation | AMI action | Required AMI privilege class (verify locally) | Additional application restriction |
|---|---|---|---|
| Pause/Resume | QueuePause | agent | member in queue 8001, exact allowlist |
| Add/remove dynamic member | QueueAdd/QueueRemove | agent | allowlisted test agent; QueueRemove may reject static |
| Penalty | QueuePenalty | agent | allowlisted test member |
| Change priority / move front | QueueChangePriorityCaller | none (inspect with manager show command) | caller currently present in queue 8001 |
| Hangup waiting call | Hangup | call | caller currently waiting in queue 8001 |
| Listen/Whisper/Barge | Originate + ChanSpy | originate | exact test member and supervisor PJSIP/101 |

The AMI permission model is class-wide; **a separate test account and private loopback-only access are necessary**. Do not grant `command`, `config` or `all` for this staging account. This build does not automatically enable writes. The user must test login, live QueueStatus, and then type `ENABLE 8001`.

Local settings persist only host/port/username/queue; the AMI password is memory-only. Legacy beta.5 plaintext settings are scrubbed on beta.6 startup if present in the **same** folder. Delete old beta.5 `local_ami_settings.json` manually if previously saved.

## Validation status

Pure-Python guard unit tests and static checks can run offline. Real Flask lifecycle, Windows startup, py-Asterisk connection, and live AMI state-changing commands require user-side testing; never claim they have passed without observed evidence.
