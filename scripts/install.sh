#!/usr/bin/env bash
set -euo pipefail
[[ $(id -u) -eq 0 ]] || { echo 'Run with sudo.'; exit 1; }
SOURCE=$(cd -- "$(dirname -- "$0")/.." && pwd)
DEST=/opt/sanequeue
PYTHON=${PYTHON:-python3}
"$PYTHON" -c 'import sys; assert (3,10) <= sys.version_info[:2] <= (3,12), "Use Python 3.10–3.12; set PYTHON=python3.11 if needed"'
[[ ! -e "$DEST" ]] || { echo "$DEST already exists. Follow docs/INSTALL.md for upgrades."; exit 1; }
id sanequeue >/dev/null 2>&1 || useradd --system --home-dir /var/lib/sanequeue --shell /sbin/nologin sanequeue
install -d -m 755 "$DEST" /etc/sanequeue
install -d -m 750 -o sanequeue -g sanequeue /var/lib/sanequeue
tar -C "$SOURCE" --exclude=.git --exclude=.venv --exclude=config.ini --exclude=var --exclude=__pycache__ --exclude=local_accounts.json --exclude=session.key --exclude=local_ami_settings.json --exclude=local_queue_policies.json --exclude=logs --exclude=*.sqlite* -cf - . | tar -C "$DEST" -xf -
"$PYTHON" -m venv "$DEST/.venv"
"$DEST/.venv/bin/pip" install -r "$DEST/requirements/modern.txt"
"$DEST/.venv/bin/pybabel" compile -d "$DEST/qpanel/translations"
"$DEST/.venv/bin/python" "$DEST/scripts/configure.py" /etc/sanequeue/config.ini
chown -R sanequeue:sanequeue /var/lib/sanequeue
chown root:sanequeue /etc/sanequeue/config.ini
chmod 640 /etc/sanequeue/config.ini
install -m 644 "$DEST/deploy/sanequeue.service" /etc/systemd/system/sanequeue.service
systemctl daemon-reload
echo 'Installed. Grant sanequeue read access to queue_log (see docs/INSTALL.md), then:'
echo '  systemctl enable --now sanequeue'
echo 'Dashboard binds to 127.0.0.1:5000. Configure the documented reverse proxy.'
