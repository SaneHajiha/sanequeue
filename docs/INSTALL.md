# Automatic installation · published beta.26

[فارسی](INSTALL.fa.md) · [User guide](USER_GUIDE.en.md) · [Validation](AUDIT_BETA26.md)

## Install on the PBX

Use a systemd Linux PBX with Asterisk available locally, AMI listening on 127.0.0.1:5038, outbound HTTPS and a working distribution package repository. Review the script before running it as root:

```bash
(
set -e
sq_stage=$(mktemp -d)
sq_release=https://github.com/SaneHajiha/sanequeue/releases/download/v2.1.0-beta.26
curl -fL "$sq_release/SaneQueue-2.1.0-beta.26.tar.gz" -o "$sq_stage/SaneQueue-2.1.0-beta.26.tar.gz"
curl -fL "$sq_release/SHA256SUMS" -o "$sq_stage/SHA256SUMS"
(cd "$sq_stage" && sha256sum --check --ignore-missing SHA256SUMS)
tar -xzf "$sq_stage/SaneQueue-2.1.0-beta.26.tar.gz" -C "$sq_stage"
sudo bash "$sq_stage/SaneQueue-2.1.0-beta.26/scripts/install.sh"
)
```

Continue only when the checksum command reports `SaneQueue-2.1.0-beta.26.tar.gz: OK`. The installer reuses Python 3.10–3.12 or downloads isolated Python 3.11 using official Astral uv. Redis is installed through the distribution package manager if missing. Internet access and supported OS repositories are required.

On first install, choose an administrator username, a 12–200 character password (entered twice without echo), an optional detected supervisor phone, and the exact panel origin. There is no default password. Upgrades retain existing accounts and passwords. Do not put passwords in shell arguments or public issue reports.

## What is provisioned

- Immutable source release under `/opt/sanequeue-releases/`; `/opt/sanequeue` points to it.
- Restricted `sanequeue` OS identity and private state in `/var/lib/sanequeue`.
- Two loopback-only AMI identities: read/reporting collector and separate agent/call/originate control account. The installer adds a delimited block to `manager_custom.conf`, preserving other accounts and file ownership. It performs `manager reload`, never an Asterisk restart.
- Private password-protected Redis on loopback port 16379, maximum 128 MB, separate from any existing Redis on 6379.
- `sanequeue`, `sanequeue-collector`, `sanequeue-redis` services and `sanequeue-inventory.timer`.
- Root-only inventory task every 30 seconds. It exports a sanitized internal-phone/trunk list to `/run/sanequeue/inventory.json`; the web service does not read SIP secrets or execute the Asterisk CLI.

Queues are discovered from AMI automatically. Standard Issabel internal phones are classified from generated endpoint definitions with `context=from-internal`; numeric trunk names are not treated as extensions. For customized dialplans, a local administrator can edit `/etc/sanequeue/inventory.ini`: section `[inventory]`, `internal_contexts=from-internal,internal-sales`. This is an exact allowlist (up to 32 names, no wildcard); never add a trunk context. The installer preserves existing values. Refresh with `systemctl start sanequeue-inventory.service`; active calls are unaffected. Configure the separate transfer context for the site's dialplan as appropriate. An unsupported driver or missing RTCP value remains unavailable, not healthy.

## Network and permissions

A private IPv4 HTTP origin binds the chosen private address/port. A DNS/HTTPS origin uses a loopback gateway on port 5000: configure your TLS reverse proxy and firewall separately using `deploy/nginx.conf.example`. The installer does not obtain certificates or open a public firewall. Never expose AMI or Redis publicly. Enable trusted forwarded headers only behind your own trusted proxy.

Controls use authenticated role + menu + queue/action grants, fresh collector state, CSRF and exact target validation. Standard managed mode does not require a temporary queue gate. Administrator accounts have intrinsic all-queue authority; other roles require explicit grants. Configure minimum staffing, pause reasons and alert thresholds under Queue policies. Telephone controls remain installation-specific beta features: test supervision audio, transfer contexts and parking on each site.

## Verify and upgrade

```bash
systemctl is-active sanequeue sanequeue-collector sanequeue-redis
systemctl list-timers sanequeue-inventory.timer
journalctl -u sanequeue -u sanequeue-collector --since '10 minutes ago'
```

Open the printed panel URL and verify login, queue membership, waiting counts, the extension catalogue and role restrictions against the PBX. Use an isolated test call for phone controls. A 202 response indicates acceptance. Check the subsequent observed result. Administrators assign extensions under Users & access. Profile password changes require the current password and invalidate existing sessions.

Rerun the tagged installer for upgrades. It takes a private backup under `/var/backups/sanequeue/<timestamp>-installer` before changing configuration/state and restores the previous source/configuration/services on failure. Keep that backup private. State copies are made with web/collector stopped. A successful upgrade does not require restoring old call statistics or deleting current data.

For manual rollback, stop the SaneQueue web/collector/inventory timer, restore the matching private `/etc/sanequeue`, state and systemd files from the installer backup, repoint `/opt/sanequeue` to `previous_source` in `result.json`, restore the backed-up AMI files with ownership, run `asterisk -rx 'manager reload'`, `systemctl daemon-reload`, and start the previous services. Review current data before restoring state: rollback can discard changes made since the backup. Never restart Asterisk just to roll back this dashboard.

Account hashes, session keys, AMI/Redis credentials, notification tokens and destinations are private. They must never enter GitHub or release archives. Apply organizational backup, log rotation and retention policies. Docker and remote-PBX installation remain advanced, separately validated deployment paths.

## Emergency disable and removal

Settings → Module disables AMI collection, alert delivery and call controls while leaving the management page available for reactivation. The independent collector closes its AMI connection and waits; Redis reads fail closed immediately. The inventory timer skips disabled runs. Already-running PBX calls, recording and dialplan continue independently. A command accepted before disabling may already be executing on the PBX and cannot be rolled back by this switch.

If the panel itself is unavailable, run `sudo sanequeuectl disable`. This stops and disables only SaneQueue web, collector, inventory and private Redis services. Restore with `sudo sanequeuectl enable`. Check using `sudo sanequeuectl status`.

`sudo sanequeuectl uninstall --yes` stops module services, removes only its managed AMI block and module unit files, and reloads AMI. Source, private data/configuration and a removal backup are deliberately retained for recovery. Reinstall the release to restore removed services. This is service uninstallation, not a destructive purge of private data. Neither command restarts Asterisk or hangs up PBX channels.

Settings → Organization identity changes the organization name, subtitle and logo shown in the dashboard and login. Uploads are reencoded PNG; SVG/HTML and external logo URLs are not accepted. Copyright/license notices remain in LICENSE/NOTICE.
