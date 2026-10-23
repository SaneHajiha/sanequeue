# SaneQueue beta.6 — controlled AMI supervisor testing

Development handoff dated 2026-10-23. **This is a documentation-only GitHub update. The complete beta.6 source is still distributed as a local ZIP and is not yet pushed to this branch.**

## What's new in the local test ZIP

- Separate local-only port **18878** to avoid old 8765/8766/18877 demos.
- AMI connection panel with Test Connection, Enable Live Data, and sanitized status.
- Explicit test-control arming: exact phrase `ENABLE 8001`, 30-minute expiry, manual disarm, no persistence across restart.
- Server-side target restrictions: test queue `8001`, member interfaces `Local/100@from-queue/n` and `PJSIP/100`, supervisor `PJSIP/101`.
- Pausing, membership, penalty, priority, waiting-caller hangup, Listen/Whisper/Barge are eligible for staged tests; no production validation yet.
- Legacy QPanel routes redirect to modern operations UI in local preview; historical reports still deferred.
- Password never saved to disk by beta.6; older plaintext beta.5 settings must be deleted separately.

## AMI privilege reference

Use a **separate test-only** AMI user in `manager_custom.conf`, restricted to Asterisk loopback and accessed only through an SSH tunnel:

```ini
[sq_supervisor_test]
secret = CHOOSE_A_NEW_RANDOM_SECRET_LOCALLY
deny = 0.0.0.0/0.0.0.0
permit = 127.0.0.1/255.255.255.255
read = agent,call,system,reporting
write = agent,call,originate
```

Actions/permission classes should be checked on the deployed Asterisk 20 version with `asterisk -rx "manager show command QueuePause"`, and equivalent commands for QueueAdd/QueueRemove/QueuePenalty/QueueChangePriorityCaller/Hangup/Originate. **AMI grants classes, not queue-specific privileges**, so this account is inappropriate for production. Do not grant `all`/`config`/`command`.

See official Asterisk documentation for [AMI permissions](https://docs.asterisk.org/Configuration/Interfaces/Asterisk-Manager-Interface-AMI/The-Asterisk-Manager-TCP-IP-API/) and [Originate](https://docs.asterisk.org/Asterisk_20_Documentation/API_Documentation/AMI_Actions/Originate/).

## Verification and pending work

Ten offline unit/static tests passed, Python files compile, JS syntax check passed; full Flask integration and real Asterisk write actions still require test host validation. Do not merge this documentation-only PR as a release of beta.6.

## Safe rollback

Disable live controls in panel (or stop local server). Remove the temporary AMI section and run `asterisk -rx "manager reload"`. Preserve pre-existing read-only account.