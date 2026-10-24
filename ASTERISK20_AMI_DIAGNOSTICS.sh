#!/usr/bin/env bash
# SAFE READ ONLY. Runs on the Asterisk host. Does not read manager.conf secrets.
set -u
printf 'SaneQueue — Asterisk 20 AMI capabilities (read-only)\n'
asterisk -rx 'core show version'
for a in ListCommands QueueStatus QueueSummary CoreShowChannels PJSIPShowEndpoints PJSIPShowContacts PJSIPShowRegistrationsOutbound ParkedCalls QueuePause QueueAdd QueueRemove QueuePenalty QueueChangePriorityCaller Hangup Originate Redirect BlindTransfer Park; do
 printf '\n=== %s ===\n' "$a"
 asterisk -rx "manager show command $a" | grep -Ei 'Privilege|Synopsis|Action not found|No such|not found' || true
done
printf '\n=== loaded module probes ===\n'
for mod in app_queue res_pjsip res_pjsip_outbound_registration res_parking parking_manager; do
 echo "-- $mod"; asterisk -rx "module show like $mod" | tail -n 5
done
printf '\n=== AMI user sq ACL and classes (review and REDACT anything sensitive) ===\n'
asterisk -rx 'manager show user sq' | grep -Ei 'Username|Read|Write|ACL|Permit|Deny|User|Event|Display' | head -n 35 || true
