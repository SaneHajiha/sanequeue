#!/usr/bin/env bash
# Isolated runtime; never replaces Issabel Python or restarts Asterisk.
set -euo pipefail
[[ $(id -u) -eq 0 ]] || { echo 'Run with sudo/root.'; exit 1; }
command -v systemctl >/dev/null || { echo 'A systemd Linux host is required.'; exit 1; }
command -v asterisk >/dev/null || { echo 'Install on the PBX host.'; exit 1; }
SOURCE=$(cd -- "$(dirname -- "$0")/.." && pwd)
REF=${SANEQUEUE_REF:-v2.1.0-beta.25}
[[ "$REF" =~ ^[A-Za-z0-9._-]+$ ]] || { echo 'Invalid release reference.'; exit 1; }
STAGE=$(mktemp -d /tmp/sanequeue-install.XXXXXXXX)
cleanup() { case "$STAGE" in /tmp/sanequeue-install.*) rm -rf -- "$STAGE" ;; esac; }
trap cleanup EXIT
if [[ ! -f "$SOURCE/requirements/modern.txt" ]]; then
  command -v curl >/dev/null || { echo 'curl is required.'; exit 1; }
  curl --fail --location --proto '=https' --tlsv1.2 "https://github.com/SaneHajiha/sanequeue/archive/refs/tags/$REF.tar.gz" -o "$STAGE/source.tar.gz"
  mkdir "$STAGE/source"
  tar -xzf "$STAGE/source.tar.gz" -C "$STAGE/source" --strip-components=1
  SOURCE="$STAGE/source"
fi
[[ -f "$SOURCE/scripts/provision.py" ]] || { echo 'Incomplete release.'; exit 1; }
PYTHON=${PYTHON:-}
if [[ -z "$PYTHON" ]]; then
  for candidate in /opt/sanequeue/.venv/bin/python python3.11 python3.12 python3.10; do
    if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; assert (3,10)<=sys.version_info[:2]<=(3,12)' 2>/dev/null; then PYTHON=$candidate; break; fi
  done
fi
if [[ -z "$PYTHON" ]]; then
  echo 'Downloading isolated Python from Astral; system Python remains unchanged.'
  install -d -m 755 /opt/sanequeue-runtime/bin /opt/sanequeue-runtime/python
  curl --fail --location --proto '=https' --tlsv1.2 https://astral.sh/uv/install.sh -o "$STAGE/uv-install.sh"
  UV_INSTALL_DIR=/opt/sanequeue-runtime/bin UV_NO_MODIFY_PATH=1 sh "$STAGE/uv-install.sh"
  export UV_PYTHON_INSTALL_DIR=/opt/sanequeue-runtime/python
  /opt/sanequeue-runtime/bin/uv python install 3.11
  PYTHON=$(/opt/sanequeue-runtime/bin/uv python find 3.11)
fi
"$PYTHON" -c 'import sys; assert (3,10)<=sys.version_info[:2]<=(3,12), "Use Python 3.10-3.12"'
if ! command -v redis-server >/dev/null; then
  if command -v dnf >/dev/null; then dnf install -y redis;
  elif command -v yum >/dev/null; then yum install -y redis;
  elif command -v apt-get >/dev/null; then apt-get update; apt-get install -y redis-server;
  else echo 'Install redis-server using the distribution package manager.'; exit 1; fi
fi
VERSION=$("$PYTHON" -c "import sys;sys.path.insert(0,sys.argv[1]);import qpanel;print(qpanel.__version__)" "$SOURCE")
[[ "$VERSION" =~ ^[A-Za-z0-9._-]+$ ]] || { echo 'Invalid package version.'; exit 1; }
RELEASE="/opt/sanequeue-releases/${VERSION}-$(date +%Y%m%d%H%M%S)"
install -d -m 755 "$RELEASE"
tar -C "$SOURCE" --exclude=.git --exclude=.venv --exclude=__pycache__ --exclude=var --exclude=logs --exclude=outputs --exclude=work --exclude=config.ini --exclude='*.sqlite*' --exclude='local_*.json' --exclude=session.key --exclude='.env' -cf - . | tar -C "$RELEASE" -xf -
"$PYTHON" -m venv "$RELEASE/.venv"
nice -n 10 "$RELEASE/.venv/bin/python" -m pip install --disable-pip-version-check --timeout 120 -r "$RELEASE/requirements/modern.txt"
"$RELEASE/.venv/bin/pybabel" compile -d "$RELEASE/qpanel/translations"
if [[ -t 0 || ( -f /var/lib/sanequeue/local_accounts.json && -n ${SANEQUEUE_PUBLIC_ORIGIN:-} ) ]]; then "$RELEASE/.venv/bin/python" "$RELEASE/scripts/provision.py" --release "$RELEASE";
else "$RELEASE/.venv/bin/python" "$RELEASE/scripts/provision.py" --release "$RELEASE" </dev/tty; fi
