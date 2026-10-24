# Redis and WebSocket deployment · beta.21

[فارسی](REALTIME_DEPLOYMENT.fa.md)

The persistent mode is an explicit upgrade from the legacy five-second snapshot adapter. Run one gateway worker and one elected collector per PBX. The gateway never falls back to AMI when Redis is unavailable. Existing installs remain in legacy mode until configured; `scripts/install.sh` alone does not activate this migration.

## Prerequisites and secrets

Use the isolated Python 3.10–3.12 runtime installed by the base installer. Install `requirements/modern.txt` in that venv. Provide authenticated Redis bound to loopback or a private socket, with at least 128 MB available and an explicit memory limit. Use a separate Redis database/instance from other PBX applications. Do not expose Redis or unencrypted AMI publicly.

Copy `samples/collector.ini.example` to `/etc/sanequeue/collector.ini` and fill the actual private AMI read identity and Redis URL. The collector currently uses QueueStatus, CoreShowChannels, Ping, ListCommands and optional inventory actions. Start with `read=system,call,agent,reporting` and `write=reporting` on a loopback-only AMI account. The test installation verified that this identity cannot issue Hangup, Originate, QueuePause, Command, BlindTransfer or Park. This privilege set deliberately cannot enumerate every PJSIP/parking resource: AMI action privileges differ from read event classes. Do not add `system` or `call` write privileges merely to make an optional inventory tile green. Review privileges for the installed Asterisk version.

Create `/etc/sanequeue/control.ini` with an `[ami]` section containing `host`, `port`, `user`, `password` for the separately authorized supervisor identity. Only actions and fields explicitly allowed by `sanequeue/actions/transport.py` can use it. Control transport currently requires local AMI or a private tunnel; unlike the collector transport, it does not configure TLS itself. Never use an Internet AMI endpoint here.

All three private INI files, including the original `config.ini`, must be owned by `root:sanequeue` with mode `0640`. Keep passwords out of the repository, command-line arguments and browser screenshots. No universal initial administrator password exists: the installer asks for one, or use the documented [reset command](ADMIN_ACCESS.md).

## Services

1. Back up the current service file, `/etc/sanequeue`, and `/var/lib/sanequeue` while application writes are stopped. Preserve ownership and permissions. Keep the previous source release and its venv for rollback.
2. Install `deploy/sanequeue-collector.service` as `sanequeue-collector.service`.
3. Copy `deploy/gateway.env.example` to `/etc/sanequeue/gateway.env`. Set the exact HTTPS browser origin, the real internal extension allowlist, transfer context and parking lot. Advanced actions remain disabled unless explicitly listed. Asterisk contexts and parking lots are installation-specific; the example numbers are not discovery results.
4. Replace the dashboard service with `deploy/sanequeue-asgi.service`, installed as `sanequeue.service`. Keep its loopback binding behind the reverse proxy. The supplied nginx example includes WebSocket upgrade headers. Use the site's actual TLS certificate and `SANEQUEUE_HTTPS=1` for remote HTTPS deployment.
5. Run `systemctl daemon-reload`, then `systemctl enable --now sanequeue-collector` and `systemctl restart sanequeue`. This does not restart Asterisk or rewrite its dialplan.
6. Inspect collector health with `/opt/sanequeue/.venv/bin/python -m sanequeue.realtime --config /etc/sanequeue/collector.ini --status`. This reads Redis only. An administrator can inspect `/api/runtime/metrics`. The UI should show WebSocket after login.

The test PBX used a private Redis instance on port 16379 and an isolated gateway on 18896 before migration. Those are test choices, not required customer ports.

## Operating boundaries

WebSocket Origin and the actual Flask session are validated. Role, queue scope and session revocation are checked on every pushed update. Each socket receives a coalesced full snapshot every two seconds; maximum 100 sockets, 512 KiB per snapshot, ten concurrent projection threads and a three-second send deadline. A client cannot send commands over the socket. HTTP controls require CSRF, grants, a fresh collector, an observed exact channel and the temporary queue control gate. Slow or oversized clients disconnect instead of accumulating a send queue.

SQLite WAL stores session revocation, command outcomes, capacity reservations and an alert outbox on the single node. This is not a multi-node HA release. Keep one gateway process: its notification/reconciliation workers and control gate are process-local, although SQLite capacity reservations are serialized across processes. Multiple dashboard hosts require a separately designed shared auth/policy/command layer.

Normal dashboard, channel, journey and health inventory reads use Redis only. Explicit administrator AMI diagnostics can still open a short diagnostic connection; they are not automatic refresh work. Periodic inventory uses the collector connection every 120 seconds and reports unavailable/partial drivers honestly. Optional Bale delivery requires explicit environment opt-in plus token/chat settings and the per-queue policy. It uses a leased, retrying outbox with at-least-once delivery; it does not promise exactly-once messages.

## Acceptance and rollback

Before production use, repeat queue scope/revocation, stale-state, pause/resume, transfer, parking and audio acceptance on that PBX. `202` means accepted, not proven audio. Commands expose `pending`, `confirmed`, `rejected` or `unknown`; some transfer/origination outcomes still require call-event/manual acceptance and can remain unknown. Never automatically retry a command with an unknown outcome.

Stop the gateway and collector, restore the backed-up legacy service, source symlink and original environment, then daemon-reload and restart the dashboard to roll back. Leave the current state backups intact. Stopping Redis alone is not rollback: persistent mode intentionally fails closed. Do not restart Asterisk for this application rollback.

Compatibility evidence and remaining limits are listed in [the beta.21 audit](AUDIT_BETA21.md). A two-queue browser load test does not establish capacity for thousands of live calls.
