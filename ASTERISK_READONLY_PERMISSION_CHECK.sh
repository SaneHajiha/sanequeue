#!/usr/bin/env bash
# SaneQueue Asterisk 20 permission diagnostic. READ ONLY. No credentials printed.
set -u
asterisk -rx 'core show version'
asterisk -rx 'module show like res_pjsip_manager'
for action in QueueStatus CoreShowChannels PJSIPShowEndpoints PJSIPShowContacts PJSIPShowRegistrationsOutbound ParkedCalls QueuePause QueueAdd QueueRemove QueuePenalty Hangup Originate; do
 echo "=== $action ==="
 asterisk -rx "manager show command $action" | grep -E 'Privilege|Synopsis|not found|not registered|^=+' || true
done
