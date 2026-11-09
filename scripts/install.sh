#!/usr/bin/env bash
# Isolated runtime; never replaces Issabel Python or restarts Asterisk.
set -euo pipefail
umask 077
MODE=install
case "${1:-}" in
  '') ;;
  --preflight) MODE=preflight; shift ;;
  *) echo 'Usage: bash scripts/install.sh [--preflight]' >&2; exit 2 ;;
esac
[[ $# -eq 0 ]] || { echo 'Unexpected installer arguments.' >&2; exit 2; }
[[ $(id -u) -eq 0 ]] || { echo 'Run with sudo/root.'; exit 1; }
command -v systemctl >/dev/null || { echo 'A systemd Linux host is required.'; exit 1; }
command -v asterisk >/dev/null || { echo 'Install on the PBX host.'; exit 1; }
SOURCE=$(cd -- "$(dirname -- "$0")/.." && pwd)
STAGE=
cleanup() { case "$STAGE" in /tmp/sanequeue-install.*) rm -rf -- "$STAGE" ;; esac; }
trap cleanup EXIT
if [[ ! -f "$SOURCE/requirements/modern.txt" ]]; then
  [[ $MODE == install ]] || { echo 'Preflight requires an extracted release.' >&2; exit 1; }
  REF=${SANEQUEUE_REF:-}
  ARCHIVE_SHA256=${SANEQUEUE_ARCHIVE_SHA256:-}
  [[ "$REF" =~ ^[a-f0-9]{40}$ && "$ARCHIVE_SHA256" =~ ^[a-fA-F0-9]{64}$ ]] ||
    { echo 'Standalone installation requires the complete commit SHA and reviewed archive SHA-256.' >&2; exit 1; }
  command -v curl >/dev/null || { echo 'curl is required.'; exit 1; }
  STAGE=$(mktemp -d /tmp/sanequeue-install.XXXXXXXX)
  curl --fail --location --retry 2 --connect-timeout 15 --max-time 180 --proto '=https' --tlsv1.2 "https://github.com/SaneHajiha/sanequeue/archive/$REF.tar.gz" -o "$STAGE/source.tar.gz"
  (cd "$STAGE" && printf '%s  source.tar.gz\n' "$ARCHIVE_SHA256" | sha256sum -c -)
  mkdir "$STAGE/source"
  tar -xzf "$STAGE/source.tar.gz" -C "$STAGE/source" --strip-components=1
  SOURCE="$STAGE/source"
fi
for required in VERSION scripts/provision.py requirements/modern.txt requirements/reporting.txt sanequeue/asgi.py; do
  [[ -f "$SOURCE/$required" ]] || { echo "Incomplete release: $required" >&2; exit 1; }
done
PYTHON=${PYTHON:-}
if [[ -z "$PYTHON" ]]; then
  for candidate in python3.11 python3.12 python3.10 /opt/sanequeue/.venv/bin/python; do
    if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; assert (3,10)<=sys.version_info[:2]<=(3,12)' 2>/dev/null; then PYTHON=$candidate; break; fi
  done
fi
[[ -n "$PYTHON" ]] || { echo 'Install a verified Python 3.10–3.12 runtime with venv first.' >&2; exit 1; }
"$PYTHON" -c 'import ensurepip, socket, sqlite3, ssl, sys, venv; assert (3,10)<=sys.version_info[:2]<=(3,12), "Use Python 3.10-3.12"'
command -v redis-server >/dev/null || { echo 'Install redis-server from an approved OS package repository first.' >&2; exit 1; }
RELEASE_VERSION=$("$PYTHON" -B -c "import sys;sys.path.insert(0,sys.argv[1]);import qpanel;print(qpanel.__version__)" "$SOURCE")
[[ "$RELEASE_VERSION" =~ ^[A-Za-z0-9._-]+$ ]] || { echo 'Invalid package version.'; exit 1; }
[[ $(<"$SOURCE/VERSION") == "$RELEASE_VERSION" ]] || { echo 'Inconsistent release version.' >&2; exit 1; }
if [[ $MODE == preflight ]]; then
  . /etc/os-release
  [[ ${ID:-} == rocky && ${VERSION_ID:-} =~ ^8(\.|$) ]] ||
    { echo 'Release target requires Rocky Linux 8.' >&2; exit 1; }
  [[ $(rpm -q --qf '%{VERSION}' issabel-system) =~ ^5(\.|$) ]] ||
    { echo 'Release target requires Issabel 5.' >&2; exit 1; }
  [[ $(asterisk -rx 'core show version') =~ Asterisk[[:space:]]20\. ]] ||
    { echo 'Release target requires running Asterisk 20.' >&2; exit 1; }
  [[ -r /etc/asterisk/manager.conf ]] || { echo 'Missing readable manager.conf.' >&2; exit 1; }
  "$PYTHON" -c 'import socket; socket.create_connection(("127.0.0.1", 5038), 3).close()'
  printf 'Preflight passed: SaneQueue %s, Rocky %s, Issabel 5, Asterisk 20, local Redis binary and AMI listener.\n' "$RELEASE_VERSION" "$VERSION_ID"
  exit 0
fi
command -v flock >/dev/null || { echo 'flock is required for a serialized install.' >&2; exit 1; }
exec 9>/run/lock/sanequeue-install.lock
flock -n 9 || { echo 'Another SaneQueue installer is running.' >&2; exit 1; }
# Release files and its virtualenv must be readable by the service user.
umask 022
RELEASE="/opt/sanequeue-releases/${RELEASE_VERSION}-$(date +%Y%m%d%H%M%S)"
install -d -m 755 /opt/sanequeue-releases
mkdir -m 755 "$RELEASE"
tar -C "$SOURCE" --exclude=.git --exclude=.venv --exclude=__pycache__ --exclude=var --exclude=logs --exclude=output --exclude=outputs --exclude=tmp --exclude=work --exclude=.agents --exclude=node_modules --exclude=tools/ui-workbench --exclude=config.ini --exclude='*.sqlite*' --exclude='local_*.json' --exclude='ssh_*' --exclude='*.key' --exclude='*.pem' --exclude=session.key --exclude='.env' --exclude='.env.*' -cf - . | tar -C "$RELEASE" -xf -
"$PYTHON" -m venv "$RELEASE/.venv"
PIP_SOURCE=()
if [[ -n ${SANEQUEUE_WHEELHOUSE:-} ]]; then
  [[ $SANEQUEUE_WHEELHOUSE == /* && -d $SANEQUEUE_WHEELHOUSE ]] ||
    { echo 'SANEQUEUE_WHEELHOUSE must be an absolute directory.' >&2; exit 1; }
  PIP_SOURCE=(--no-index --find-links "$SANEQUEUE_WHEELHOUSE")
fi
nice -n 10 "$RELEASE/.venv/bin/python" -m pip install --disable-pip-version-check --timeout 120 "${PIP_SOURCE[@]}" -r "$RELEASE/requirements/modern.txt" -r "$RELEASE/requirements/reporting.txt"
"$RELEASE/.venv/bin/python" -m pip check
"$RELEASE/.venv/bin/pybabel" compile -d "$RELEASE/qpanel/translations"
if [[ -t 0 || ( -f /var/lib/sanequeue/local_accounts.json && -n ${SANEQUEUE_PUBLIC_ORIGIN:-} ) ]]; then "$RELEASE/.venv/bin/python" "$RELEASE/scripts/provision.py" --release "$RELEASE";
else "$RELEASE/.venv/bin/python" "$RELEASE/scripts/provision.py" --release "$RELEASE" </dev/tty; fi
