#!/usr/bin/env bash
# Download the tested RC7 pilot and select a private address for a new LAN install.
set -euo pipefail
umask 077

mode=${1:-install}
case "$mode" in
  install) [[ $# -eq 0 ]] ;;
  --preflight) [[ $# -eq 1 ]] ;;
  *) printf 'Usage: bash %s [--preflight]\n' "${0##*/}" >&2; exit 2 ;;
esac
if [[ $(id -u) -ne 0 ]]; then
  exec sudo --preserve-env=SSH_CONNECTION bash "$0" "$@"
fi
export PYTHON=/usr/bin/python3.11
if [[ $(uname -m) != x86_64 || ! -x "$PYTHON" ]]; then
  echo 'SaneQueue RC7 requires x86_64 and /usr/bin/python3.11 with venv.' >&2
  exit 1
fi

release_url=https://github.com/SaneHajiha/sanequeue/releases/download/v2.1.0-rc.7
release=SaneQueue-2.1.0-rc.7.tar.gz
wheels=SaneQueue-rc7-wheelhouse-rocky8-x86_64-py311.tar.gz
stage=$(mktemp -d /tmp/sanequeue-rc7-lan.XXXXXXXX)
cleanup() { case "$stage" in /tmp/sanequeue-rc7-lan.*) rm -rf -- "$stage" ;; esac; }
trap cleanup EXIT

download() {
  local file=$1 digest=$2
  curl --fail --show-error --location --retry 2 --connect-timeout 15 --max-time 1800 \
    --proto '=https' --proto-redir '=https' --output "$stage/$file" "$release_url/$file"
  (cd -- "$stage" && printf '%s  %s\n' "$digest" "$file" | sha256sum --strict --check)
}

download "$release" ab0d42bae3e2d16d82a2afbeaebedf0af112ca2cc15f604ced3d831d627c919b
tar -xzf "$stage/$release" -C "$stage"
installer="$stage/SaneQueue-2.1.0-rc.7/scripts/install.sh"
bash "$installer" --preflight
[[ $mode != --preflight ]] || exit 0

if ! asterisk -rx 'core show channels count' | grep -Eq '^0 active channels?[[:space:]]*$'; then
  echo 'Installation requires an idle PBX. No installation was started.' >&2
  exit 1
fi

if [[ -e /etc/sanequeue/gateway.env || -e /opt/sanequeue/VERSION ]]; then
  # Preserve the site origin on upgrades. Read the config as data, never as shell code.
  origin=$(sed -n 's/^SANEQUEUE_PUBLIC_ORIGINS=\([^,]*\).*/\1/p' /etc/sanequeue/gateway.env)
  if [[ $origin != http://* && $origin != https://* ]]; then
    echo 'Could not identify the existing SaneQueue panel address; no upgrade was started.' >&2
    exit 1
  fi
else
  addresses=$("$PYTHON" - <<'PY'
import ipaddress
import json
import os
import subprocess

private_ranges = tuple(ipaddress.ip_network(network) for network in (
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
))
interfaces = json.loads(subprocess.check_output(["ip", "-j", "-4", "addr", "show", "scope", "global"]))
local = sorted({
    ipaddress.ip_address(entry["local"])
    for interface in interfaces for entry in interface["addr_info"]
    if any(ipaddress.ip_address(entry["local"]) in network for network in private_ranges)
})
ssh_connection = os.environ.get("SSH_CONNECTION", "").split()
ssh_address = next((address for address in local if len(ssh_connection) == 4 and str(address) == ssh_connection[2]), None)
for address in ([ssh_address] if ssh_address else local):
    print(address)
PY
  )
  if [[ -z $addresses ]]; then
    address=127.0.0.1
    echo 'No private IPv4 address found. The panel will listen on localhost; use an SSH tunnel.'
  else
    mapfile -t choices <<< "$addresses"
    if [[ ${#choices[@]} -eq 1 ]]; then
      address=${choices[0]}
    else
      [[ -t 0 ]] || { echo 'Multiple private addresses found. Run the installer in an interactive SSH terminal.' >&2; exit 1; }
      PS3='Choose the private IP for the panel: '
      select address in "${choices[@]}"; do
        [[ -n $address ]] && break
      done
      [[ -n ${address:-} ]] || exit 1
    fi
  fi
  origin="http://$address:5000"
fi
printf 'SaneQueue panel address: %s/operations\n' "$origin"

download "$wheels" 8749aebfc101468604252bce41a539b720992c7ef2a1f58cebdcba1bf8c5eb16
tar -xzf "$stage/$wheels" -C "$stage"
(cd -- "$stage/wheelhouse" && sha256sum --strict --check SHA256SUMS >/dev/null)
export SANEQUEUE_WHEELHOUSE="$stage/wheelhouse"
export SANEQUEUE_PUBLIC_ORIGIN="$origin"
export SANEQUEUE_ACTIVATE_TELEPHONY=0
bash "$installer"
