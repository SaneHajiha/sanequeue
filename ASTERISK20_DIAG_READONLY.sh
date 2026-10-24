#!/usr/bin/env bash
# Read-only local Asterisk diagnostics for SaneQueue, no AMI credentials, no config changes.
set -u
printf '\n== Asterisk version ==\n'
asterisk -rx 'core show version'
printf '\n== Queue 8001 ==\n'
asterisk -rx 'queue show 8001'
printf '\n== Device hint for extension 100 ==\n'
asterisk -rx 'core show hints' | grep -F '100@ext-local' || echo 'Hint not found in listed hints'
printf '\n== Endpoint 100 (PJSIP, if configured) ==\n'
asterisk -rx 'pjsip show endpoint 100'
printf '\n== Presence of manager TCP service (no credentials displayed) ==\n'
asterisk -rx 'manager show settings' | grep -Ei 'Enabled|Bind|Port|TLS' || true
printf '\n== Connected calls ==\n'
asterisk -rx 'core show channels count'
printf '\nIMPORTANT: Redact public numbers, passwords, addresses and customer data before sharing output.\n'
