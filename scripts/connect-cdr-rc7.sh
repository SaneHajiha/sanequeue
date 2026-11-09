#!/usr/bin/env bash
set -euo pipefail
umask 077

config=/etc/sanequeue/reporting-sql.ini
envfile=/etc/sanequeue/reporting.env
unit=sanequeue-reporting.service
python=/opt/sanequeue/.venv/bin/python
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

if ! socket=$(mysql --protocol=socket --connect-timeout=5 -u root -p --batch --skip-column-names --execute="
CREATE USER 'sanequeue'@'localhost' IDENTIFIED VIA unix_socket;
GRANT SELECT ON asteriskcdrdb.cdr TO 'sanequeue'@'localhost';
GRANT SELECT ON asteriskcdrdb.cel TO 'sanequeue'@'localhost';
SELECT @@socket;
"); then
  echo 'MariaDB setup stopped. Review the error and check whether the local sanequeue account was created.' >&2
  exit 1
fi
[[ $socket == /* && $socket != *$'\n'* && -S $socket ]] || {
  echo 'MariaDB did not return an accessible absolute socket path.' >&2
  exit 1
}
runuser -u sanequeue -- "$python" -I - "$socket" <<'PY'
import sys
import pymysql

with pymysql.connect(user="sanequeue", unix_socket=sys.argv[1], connect_timeout=5,
                     read_timeout=2, write_timeout=2, local_infile=False) as db:
    with db.cursor() as cursor:
        cursor.execute("SELECT calldate, uniqueid, linkedid FROM asteriskcdrdb.cdr LIMIT 0")
        cursor.execute("SELECT id, eventtime, eventtype, uniqueid FROM asteriskcdrdb.cel LIMIT 0")
print("Local read access verified as sanequeue.")
PY

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
      fi
    fi
    if (( config_installed )); then rm -f -- "$config"; fi
    echo 'The local MariaDB account may exist. Review it before retrying.' >&2
  fi
  rm -f -- "$stage/sql.ini" "$stage/reporting.env"
  rmdir -- "$stage"
}
trap cleanup EXIT
printf '[reporting]\nhost=localhost\nunix_socket=%s\nuser=sanequeue\npassword=\ndatabase=asteriskcdrdb\ntimezone=%s\n' \
  "$socket" "$zone" > "$stage/sql.ini"
printf 'REPORTING_SQL_ARGS=--mysql-config %s\n' "$config" > "$stage/reporting.env"
chown root:sanequeue "$stage/sql.ini" "$stage/reporting.env"
chmod 0640 "$stage/sql.ini" "$stage/reporting.env"
ln -- "$stage/sql.ini" "$config"
config_installed=1
mv -- "$stage/reporting.env" "$envfile"
env_installed=1
systemctl restart "$unit"
systemctl is-active --quiet "$unit"
echo 'CDR/CEL source configured. Check import progress with the RC7 launcher --reports-status option.'
