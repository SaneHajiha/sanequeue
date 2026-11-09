#!/usr/bin/env bash
set +x
set -euo pipefail
umask 077

config=/etc/sanequeue/reporting-sql.ini
envfile=/etc/sanequeue/reporting.env
unit=sanequeue-reporting.service
python=/opt/sanequeue/.venv/bin/python
account=sanequeue_report_ro
[[ $EUID == 0 && -x $python ]] || { echo 'Run as root on the installed SaneQueue host.' >&2; exit 1; }
exec 9>/run/lock/sanequeue-install.lock
flock -n 9 || { echo 'SaneQueue installation or configuration is in progress.' >&2; exit 1; }
[[ ! -e $config && ! -L $config && -f $envfile && ! -L $envfile &&
   $(<"$envfile") == 'REPORTING_SQL_ARGS=' ]] || {
  echo 'Reporting SQL settings already exist or differ from the fresh install. Review them before proceeding.' >&2
  exit 1
}
[[ $(systemctl show -p User --value "$unit") == sanequeue ]] || {
  echo 'The reporting service does not use the expected operating-system account.' >&2
  exit 1
}
systemctl is-active --quiet "$unit"
zone=$(timedatectl show -p Timezone --value)
"$python" -I -c 'from zoneinfo import ZoneInfo; import sys; ZoneInfo(sys.argv[1])' "$zone"
backup=$(mktemp -d /var/backups/sanequeue/reporting-sql.XXXXXXXX)
cp -a -- "$envfile" "$backup/reporting.env"
printf 'Reporting config backup: %s/reporting.env\n' "$backup"

read -r password password_hash <<< "$("$python" -I - <<'PY'
import hashlib
import secrets

password = secrets.token_urlsafe(32)
first = hashlib.sha1(password.encode("ascii"), usedforsecurity=False).digest()
digest = hashlib.sha1(first, usedforsecurity=False).hexdigest().upper()
print(password, "*" + digest)
PY
)"
[[ $password =~ ^[A-Za-z0-9_-]{43}$ && $password_hash =~ ^\*[0-9A-F]{40}$ ]] || {
  echo 'Could not generate the reporting account credential.' >&2
  exit 1
}
if ! socket=$(mysql --protocol=socket --connect-timeout=5 -u root -p --batch --skip-column-names --skip-force <<SQL
CREATE USER '$account'@'localhost' IDENTIFIED VIA mysql_native_password USING '$password_hash';
GRANT SELECT ON asteriskcdrdb.cdr TO '$account'@'localhost';
GRANT SELECT ON asteriskcdrdb.cel TO '$account'@'localhost';
SELECT @@socket;
SQL
); then
  printf 'MariaDB setup stopped. Review the error and the local %s account before retrying.\n' "$account" >&2
  exit 1
fi
[[ $socket == /* && $socket != *$'\n'* && -S $socket ]] || {
  echo 'MariaDB did not return an accessible absolute socket path.' >&2
  exit 1
}
stage=$(mktemp -d /etc/sanequeue/.reporting-sql.XXXXXXXX)
config_installed=0
env_installed=0
cleanup() {
  local code=$?
  if (( code != 0 )); then
    if (( env_installed )); then
      if cp -a -- "$backup/reporting.env" "$envfile"; then
        systemctl restart "$unit" || echo 'Reporting service restart failed after restoring its configuration.' >&2
      else
        printf 'Restore %s/reporting.env to %s before restarting the reporting service.\n' "$backup" "$envfile" >&2
        config_installed=0
      fi
    fi
    if (( config_installed )); then rm -f -- "$config"; fi
    printf 'The local MariaDB account %s may exist. Review it before retrying.\n' "$account" >&2
  fi
  rm -f -- "$stage/sql.ini" "$stage/reporting.env"
  rmdir -- "$stage"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
printf '[reporting]\nhost=localhost\nunix_socket=%s\nuser=%s\npassword=%s\ndatabase=asteriskcdrdb\ntimezone=%s\n' \
  "$socket" "$account" "$password" "$zone" > "$stage/sql.ini"
unset password password_hash
printf 'REPORTING_SQL_ARGS=--mysql-config %s\n' "$config" > "$stage/reporting.env"
chown root:sanequeue "$stage" "$stage/sql.ini" "$stage/reporting.env"
chmod 0710 "$stage"
chmod 0640 "$stage/sql.ini" "$stage/reporting.env"
runuser -u sanequeue -- "$python" -I - "$stage/sql.ini" <<'PY'
import sys

sys.path.insert(0, "/opt/sanequeue")
from sanequeue.reporting.sql_source import SQLSource

source = SQLSource.from_file(sys.argv[1])
with source._connect() as db, db.cursor() as cursor:
    source._columns(cursor, "cdr")
    source._columns(cursor, "cel")
print("Local read access and schema verified as sanequeue.")
PY
ln -- "$stage/sql.ini" "$config"
config_installed=1
mv -- "$stage/reporting.env" "$envfile"
env_installed=1
systemctl restart "$unit"
systemctl is-active --quiet "$unit"
echo 'CDR/CEL source configured. Check import progress with the RC7 launcher --reports-status option.'
