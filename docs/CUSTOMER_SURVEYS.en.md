# Customer DTMF surveys

This is a separate module from happy-call/agent work-session reports. The store,
versioned form editor, scoped response reports and isolated FastAGI adapter are
implemented. No telephone route is installed automatically. A real PBX survey,
phone playback and DTMF acceptance have **not** been certified by these tests.

## Form and reporting workflow

1. Grant the **Customer surveys** menu. Supervisors additionally need `view` and
   `survey_reports` on each queue. Administrators design forms; supervisors read
   only currently authorised queues. Requests reload account/menu/queue grants.
2. A technical operator first registers an approved binding with a reserved form
   ID, queue and existing local prompt names. Without a binding the editor cannot
   activate a telephone integration. Neither a URL nor generated speech is used.
3. Select the binding, title, questions, numeric keys, labels and forward branches.
   Choose the CSAT question and the keys counted as satisfied. Star opts out.
   A recording must actually describe the selected keys and star; administrative
   question text is **not** automatically spoken.
4. Save an immutable version. Existing sessions retain their original form,
   queue, recorded member, caller channel ID and visit evidence. Approving a new
   exact version in the root configuration is a separate technical action.
5. Filter responses by Tehran calendar dates and authorised queue. Details show
   valid answers, timeouts, invalid attempts and attribution evidence. No customer
   telephone number or call recording is exposed by this module.

**CSAT numerator:** sessions with a valid satisfied answer to their pinned CSAT
question. **Denominator:** sessions with any valid answer to that question,
including a score in an otherwise partial form. No score means no denominator
entry. Recorded invitations are not all answered calls, a customer count or a
response-adoption denominator. Branch-skipped questions are not scored.

States distinguish completed, no valid response, partial, abandoned before a valid
answer, declined and expired/unknown completion. A `COMPLETECALLER` in the original
call never triggers a fresh callback or an artificial customer response.

## Explicit technical integration

Initial integration is deliberately manual and optional. The supplied service is
not enabled by the installer. Use an isolated test queue before any real route.

Prepare actual PCM WAV prompts under `/var/lib/asterisk/sounds`, mono, signed
16-bit, 8 kHz, at most 15 seconds each. They must be readable by the service and
Asterisk and managed by the technical operator. No audio is bundled for survey
questions: the software cannot invent or verify their spoken meaning.

Create `/etc/sanequeue/survey-bindings.json`, owned by root, group `sanequeue`,
mode `0640`, with a fresh random 64-hex token and reserved 32-hex form ID:

```python
# Run as root on the intended test server; refuses an existing configuration.
import grp, json, os, secrets, uuid
path = '/etc/sanequeue/survey-bindings.json'
form_id = uuid.uuid4().hex
config = {'token': secrets.token_hex(32), 'bindings': {'support': {
    'queue': '8001', 'form_id': form_id, 'form_version': 1, 'enabled': False,
    'prompts': {'rating': 'custom/organization/satisfaction-fa'}
}}}
fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o640)
with os.fdopen(fd, 'w') as stream:
    json.dump(config, stream); stream.flush(); os.fsync(stream.fileno())
os.chown(path, 0, grp.getgrnam('sanequeue').gr_gid)
os.chmod(path, 0o640)
print('Reserved form ID:', form_id)  # Never print the token.
```

Use the web editor to create that form's first version. Check the actual prompt
against the keys/branches. The web API cannot change root bindings, tokens, PBX
routes or installed prompt names. Overrides for isolated tests are
`SANEQUEUE_SURVEY_CONFIG`, `SANEQUEUE_SURVEY_ACCOUNTS` and
`SANEQUEUE_SURVEY_POLICIES`; worker CLI paths must match the intended stores.

Review the root-pinned version and enable only that binding. Install the supplied
`deploy/sanequeue-surveys.service` as an optional systemd unit, create the explicit
`/etc/sanequeue/surveys.enabled` marker and start it deliberately. Removing this
marker or setting the global module-disabled flag stops new survey processing
on the next request. The module emergency-disable command also stops an installed
survey service; enabling the module does not install or opt into this service.
The listener
binds only `127.0.0.1:19052`; it needs read access to the local `queue_log` and
approved sounds. The service is limited to 10% CPU / 128 MiB and does not use AMI.
Its default state directory is `/var/lib/sanequeue`.

Render the subroutine for private technical review:

```sh
umask 077
/opt/sanequeue/.venv/bin/python -m sanequeue.surveys.adapter --render \
  --config /etc/sanequeue/survey-bindings.json > /root/sanequeue-surveys-review.conf
```

The rendered file contains a private loopback token. Do not upload it to GitHub.
An operator must install/include it through a supported custom dialplan location
and preserve existing options, macros, routing and permissions. After the existing
queue call, add an explicit hook in the **same caller channel**. A minimal isolated
example is:

```asterisk
same => n,Queue(8001,c)
same => n,Gosub(sanequeue-customer-survey,s,1(support))
; Continue the original dialplan here. No new customer call is originated.
```

Do not replace an existing Queue application's other arguments with this example.
Do not overwrite generated PBX configuration. This implementation does not perform
a reload, route rewrite, dialing, transfer or hangup. Withdraw the binding or stop
the optional service to prevent subsequent survey steps. A prompt already being
read is bounded but is not forcibly interrupted by this module.

## Evidence and compatibility boundaries

For Asterisk 16/18/20, Queue's lower-case `c` continues the caller dialplan when
the callee hangs up. `F` instead transfers the **called member** after the caller
hangs up and is unsuitable for questioning that caller. Dial's lower-case `g`
has different application semantics. Direct Dial surveys are **not** supported by
this first adapter: they require independent verified answer/end instrumentation.
Sources: [Asterisk 16 Queue](https://raw.githubusercontent.com/asterisk/asterisk/16.30.1/apps/app_queue.c),
[Asterisk 18 Queue](https://raw.githubusercontent.com/asterisk/asterisk/18/apps/app_queue.c),
[Asterisk 20 Queue](https://docs.asterisk.org/Asterisk_20_Documentation/API_Documentation/Dialplan_Applications/Queue/),
[Asterisk 20 Dial](https://raw.githubusercontent.com/asterisk/asterisk/20/apps/app_dial.c).

The adapter additionally requires matching `ENTERQUEUE`, `CONNECT` and
`COMPLETEAGENT` lines for the exact caller unique ID and queue. Transfers, another
completion, a second ambiguous CONNECT or a later queue re-entry invalidate the
proof. The bounded 256 KiB incremental tail can miss long/rotated history; missing
proof skips the survey instead of guessing. Queue-log member text is kept exactly
as recorded; Local names are not converted into guessed SIP/PJSIP identities.
`observed_linkedid`, when present, is metadata, not cross-call ownership proof.

`checked_prompt_hashes` describe validated local files at check time. The PBX
opens those paths later: hashes do not prove playback, sound heard, semantic
correctness or immunity to a concurrent administrative file replacement.

Limits are 5 questions, 10 numeric keys, 2 attempts, 3–10 seconds per response,
10 answer steps and 300 seconds per session. Root-approved prompts are capped at
15 seconds. Reports use indexed queue/time scope, 100-row keyset pages, at most
31 days / 50,000 sessions and a 0.5-second SQLite query deadline. Store limits
(1,000 form versions / 1,000,000 sessions) refuse new writes rather than silently
delete historical data. There is no transcript, audio-recording, outbound SMS,
voice-note or NPS implementation in this slice.

Before enabling a real route, test agent-first/caller-first hangup, all valid and
invalid keys, timeout/retry, partial/declined, queue re-entry, transfers, Local
optimisation, multiple queue membership, service loss and root-binding withdrawal.
CPU/RTP load and multi-version PBX installation remain acceptance work; no
zero-load or universal compatibility guarantee is made.
