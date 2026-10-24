#!/usr/bin/env bash
# Safe read-only inspection. No queue configuration is modified.
asterisk -rx 'queue show'
for f in /etc/asterisk/queues_additional.conf /etc/asterisk/queues_custom.conf /etc/asterisk/queues.conf; do
  if test -r "$f"; then
    echo "--- $f ---"
    grep -nE '^\[[^]]+\]' "$f" || true
    grep -nEi '(^|[[:space:]])#include' "$f" || true
  fi
done
