#!/usr/bin/env bash
# Download the tested RC7 pilot and select a private address for a new LAN install.
set -euo pipefail
umask 077

mode=${1:-install}
case "$#:$mode" in
  0:install|1:--preflight) ;;
  *) printf 'Usage: bash %s [--preflight]\n' "${0##*/}" >&2; exit 2 ;;
esac
if [[ $(id -u) -ne 0 ]]; then
  exec sudo --preserve-env=SSH_CONNECTION bash "$0" "$@"
fi
fail() { printf '%s\n' "$1" >&2; exit 1; }
export PYTHON=/usr/bin/python3.11
[[ $(uname -m) == x86_64 ]] || fail 'SaneQueue RC7 requires x86_64.'
. /etc/os-release
[[ ${ID:-} == rocky && ${VERSION_ID:-} =~ ^8(\.|$) ]] || fail 'SaneQueue RC7 requires Rocky Linux 8.'
issabel=$(rpm -q --qf '%{VERSION}' issabel-system 2>/dev/null) || fail 'Issabel 5 is required.'
[[ $issabel =~ ^5(\.|$) ]] || fail 'Issabel 5 is required.'
asterisk_version=$(timeout 8 asterisk -rx 'core show version') || fail 'Could not check the running Asterisk service.'
[[ $asterisk_version =~ Asterisk[[:space:]]20\. ]] || fail 'Asterisk 20 is required.'

require_idle() {
  local channels
  channels=$(timeout 8 asterisk -rx 'core show channels count') || fail 'Could not check Asterisk channels.'
  grep -Eq '^0 active channels?[[:space:]]*$' <<< "$channels" || fail 'Installation requires an idle PBX. No installation was started.'
}

missing_prerequisites() {
  packages=()
  if [[ ! -x $PYTHON ]] || ! "$PYTHON" -B -c 'import ensurepip, venv' 2>/dev/null; then
    echo 'Missing Python 3.11 with venv/ensurepip at /usr/bin/python3.11.' >&2
    packages+=(python3.11 python3.11-pip)
  fi
  if ! command -v redis-server >/dev/null; then
    echo 'Missing redis-server.' >&2
    packages+=(redis)
  fi
}

if [[ $mode == install ]]; then
  require_idle
fi
missing_prerequisites
if [[ $mode == install || ${#packages[@]} -gt 0 ]]; then
  # A stopped or uninterruptible package manager may hold locks indefinitely.
  blocked=$(ps -C dnf,dnf-3,yum,rpm -o pid=,stat=,comm= | awk '$2 ~ /^[DTt]/' || true)
  if [[ -n $blocked ]]; then
    printf 'Blocked package manager processes (PID, state, command):\n%s\n' "$blocked" >&2
    fail 'Resolve the host package-manager wait before retrying. No package-manager process or lock was modified.'
  fi
fi
if [[ ${#packages[@]} -gt 0 ]]; then
  printf 'Required Rocky packages: %s\n' "${packages[*]}" >&2
  if [[ $mode == --preflight || ! -t 0 ]]; then
    fail 'Run this installer in an interactive terminal to review and install the missing packages.'
  fi
  echo 'Checking Rocky BaseOS and AppStream. Review the transaction and confirm at the DNF prompt to install.'
  if ! dnf --repo=baseos --repo=appstream \
      --setopt=exit_on_lock=True --setopt=timeout=20 --setopt=retries=1 \
      --setopt=assumeyes=False --setopt=defaultyes=False \
      --exclude='asterisk*' --exclude='issabel*' install "${packages[@]}"; then
    fail 'Prerequisites were not installed. Review the DNF output above for a declined transaction, lock or repository error.'
  fi
  missing_prerequisites
  [[ ${#packages[@]} -eq 0 ]] || fail 'The required Python/Redis commands are still unavailable.'
fi

release_url=https://github.com/SaneHajiha/sanequeue/releases/download/v2.1.0-rc.7
release=SaneQueue-2.1.0-rc.7.tar.gz
wheels=SaneQueue-rc7-wheelhouse-rocky8-x86_64-py311.tar.gz
stage=$(mktemp -d /tmp/sanequeue-rc7-lan.XXXXXXXX)
cleanup() { case "$stage" in /tmp/sanequeue-rc7-lan.*) rm -rf -- "$stage" ;; esac; }
trap cleanup EXIT

cache=$stage
if [[ $mode == install ]]; then
  cache=/var/cache/sanequeue-installer-rc7
  if [[ ! -e $cache && ! -L $cache ]]; then
    mkdir -m 0700 -- "$cache" || [[ -d $cache ]] || fail 'Could not create the installer cache.'
  fi
  [[ -d $cache && ! -L $cache && $(stat -c '%u %a' "$cache") == '0 700' ]] || fail 'Unsafe installer cache directory.'
  exec 9>"$cache/install.lock"
  flock -n 9 || fail 'Another SaneQueue RC7 launcher is running.'
fi

verified() {
  [[ -f $1 ]] && printf '%s  %s\n' "$2" "$1" | sha256sum --strict --status --check
}

download() {
  local file=$1 digest=$2 target part status
  target="$cache/$file"
  part="$target.part"
  local -a options=(--ipv4 --fail --show-error --location --retry 2 --connect-timeout 15
    --max-time 1800 --retry-max-time 1800 --speed-limit 1024 --speed-time 45
    --progress-bar --proto '=https' --proto-redir '=https' --output "$part")
  if verified "$target" "$digest"; then
    printf '%s: OK (cached)\n' "$file"
    return
  fi
  if ! verified "$part" "$digest"; then
    printf 'Downloading %s from GitHub.\n' "$file"
    if [[ -s $part ]]; then
      if curl "${options[@]}" --continue-at - "$release_url/$file"; then
        :
      else
        status=$?
        case "$status" in
          22|33|36) rm -f -- "$part"; curl "${options[@]}" "$release_url/$file" || fail "Download failed for $file; retry to resume." ;;
          *) fail "Download failed for $file; retry to resume." ;;
        esac
      fi
    else
      curl "${options[@]}" "$release_url/$file" || fail "Download failed for $file; check HTTPS access to the GitHub release."
    fi
  fi
  if ! verified "$part" "$digest"; then
    rm -f -- "$part"
    fail "Checksum mismatch for $file; retry to download it again."
  fi
  mv -f -- "$part" "$target"
  printf '%s: OK\n' "$file"
}

download "$release" ab0d42bae3e2d16d82a2afbeaebedf0af112ca2cc15f604ced3d831d627c919b
tar -xzf "$cache/$release" -C "$stage"
installer="$stage/SaneQueue-2.1.0-rc.7/scripts/install.sh"
bash "$installer" --preflight
[[ $mode != --preflight ]] || exit 0

if [[ -e /etc/sanequeue/gateway.env || -e /opt/sanequeue/VERSION ]]; then
  # Preserve the site origin on upgrades. Read the config as data, never as shell code.
  origin=$(sed -n 's/^SANEQUEUE_PUBLIC_ORIGINS=\([^,]*\).*/\1/p' /etc/sanequeue/gateway.env) || fail 'Could not read the existing SaneQueue panel address.'
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
tar -xzf "$cache/$wheels" -C "$stage"
(cd -- "$stage/wheelhouse" && sha256sum --strict --check SHA256SUMS >/dev/null)
export SANEQUEUE_WHEELHOUSE="$stage/wheelhouse"
export SANEQUEUE_PUBLIC_ORIGIN="$origin"
export SANEQUEUE_ACTIVATE_TELEPHONY=0
require_idle
bash "$installer"
