# Installation and operations · beta.18

## Requirements

Use a parallel Python 3.10–3.12 environment, Git, pip/venv and systemd on Linux. On Rocky 8 use `python3.11`; do not change Issabel's system Python or PBX packages. On legacy Issabel 4 hosts that cannot safely supply this runtime, run SaneQueue on a separate supported Linux host with restricted AMI access. Only the dashboard needs the modern runtime.

```bash
git clone https://github.com/SaneHajiha/sanequeue.git
cd sanequeue
sudo env PYTHON=python3.11 bash scripts/install.sh
sudo systemctl enable --now sanequeue
sudo journalctl -u sanequeue -n 30 --no-pager
```

The installer refuses to overwrite an installation/configuration. It creates `/opt/sanequeue`, `/etc/sanequeue/config.ini`, `/var/lib/sanequeue` and the `sanequeue` service user. Enter existing AMI credentials and a new dashboard password interactively. Account hashes and session state live outside the source tree. Server startup refuses an empty account registry. Use `scripts/init_accounts.py --state /var/lib/sanequeue` only when initializing an empty registry manually, as the service user.

One gunicorn worker with four HTTP threads is required: the cache, listener and control gate are process-local. Do not increase workers or run competing instances against one state directory. Default binding is `127.0.0.1:5000`.

## AMI and drivers

Create a dedicated AMI account through your PBX's supported custom configuration. Restrict it to the dashboard IP; never publish port 5038. Monitoring uses QueueStatus; call journeys use one event subscription with `read=call,agent`. Optional health actions and controls need their own privileges. Inspect `manager show command <Action>` for your installed Asterisk version. Do not grant `command` or `system` wholesale to solve an unexplained failure.

SIP and PJSIP are detected independently. Local members with `hint:100@ext-local` are resolved against actual active channels. Ambiguous or absent channels cause a refusal, not a guessed driver. An explicit `[device_channels]` mapping, such as `100 = SIP/100`, is available for unusual deployments. Supervisor phones are assigned in Users & access; each account gets a distinct phone. Test ChanSpy audio before enabling supervision for users.

## TLS proxy

Use `deploy/nginx.conf.example` as a starting point and configure your own certificate. The dashboard must remain bound to loopback when trusting forwarded headers. Add these systemd environment values **only behind your trusted proxy**:

```ini
Environment=SANEQUEUE_TRUST_PROXY=1
Environment=SANEQUEUE_HTTPS=1
```

The first trusts one proxy's protocol/host headers; the second makes session cookies HTTPS-only. Forward `Host` (including any nonstandard port) and `X-Forwarded-Proto`. Apply `systemctl daemon-reload` and restart the dashboard. Do not turn proxy trust on for a directly exposed service.

## Accounts, policies and controls

Manage accounts, phones and queue permissions in Users & access. Minimum staffing is configured per queue. A session-bound control gate must be enabled for the selected test queue before write operations. Controls remain beta. AMI response 202 means accepted but not independently verified; check the PBX result. Out-of-band changes from phones/other dashboards are outside SaneQueue's staffing safeguard.

Shift planning stores schedules and rejects overlapping periods for one agent; it does not automatically pause or log agents into the PBX. Directory records are queue-scoped contacts, without automatic dialing or CRM synchronization.

## Docker (configuration supplied; build not validated here)

```bash
docker compose build
docker compose run --rm --user root --entrypoint sh sanequeue -c 'mkdir -p /var/lib/sanequeue && chown 10001 /var/lib/sanequeue'
docker compose run --rm --entrypoint python sanequeue scripts/init_accounts.py --state /var/lib/sanequeue
docker compose up -d
```

Create a local `config.ini` with `[manager]` host/port/user/password and `[general]` language/interval/theme first, readable by UID 10001. Use a PBX address reachable from the container; container localhost is not the PBX host. State is a persistent volume. Do not include credentials in image layers. Host port exposure defaults to loopback.

## Upgrade, backup and rollback

Back up the config and complete state directory with restricted permissions. Stop only the dashboard service, deploy into a new source directory/venv, preserve state, install dependencies and run tests. Update the service path, then start and verify login, queue counts and AMI errors. Roll back by stopping the new dashboard and restoring the previous service path/config/state backup. Never restart Asterisk merely to update this dashboard. SQLite backups should be taken while the dashboard is stopped.

Back up account hashes, session key, AMI settings, policies, SQLite planning database and audit logs. These are private and must not enter GitHub or release ZIPs. Apply log rotation and an organizational retention policy. Multiple tenants and high availability are not provided.
