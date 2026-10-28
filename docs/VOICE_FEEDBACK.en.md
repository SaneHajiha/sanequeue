# Customer voice feedback — manual intake

This working slice accepts an existing recording uploaded by an authorized
administrator or supervisor. It does **not** install a telephone recording
hook, call a customer, accept an untrusted PBX webhook, or verify who spoke.
No ASR or AI analysis is claimed. No AMI request, transcoding subprocess or GPU
is used by intake or review.

## Operator workflow

1. Open **Customer voice feedback** under customer satisfaction.
2. Select an authorized queue. Choose an actual mono, 16-bit PCM WAV recorded
   at 8000 Hz, no longer than 60 seconds or 1 MiB. This version does not convert
   MP3/stereo/16 kHz files; use an approved recording prepared in that format.
3. Optionally enter an existing DTMF survey session ID. The server checks that
   the session exists in the selected queue, then freezes its session ID and
   raw agent identity. Attaching a file manually is not proof that the file
   came from that caller or conversation. `linkedid` is never accepted as proof.
4. Upload. A successful response means both audio and intake audit committed.
   A retry with the same idempotency key and content returns the same item;
   different content with that key fails rather than overwriting it.
5. Review the item, choose a status, optionally assign an authorized reviewer
   of the same queue, and add a note/follow-up date. Concurrent edits use a
   version fence; reload after a conflict. Follow-up time is scheduled metadata,
   not an automatic notification or completed action.
6. Playback needs `recording_play`; download separately needs
   `recording_download`. Both also require current `view` and `survey_reports`
   grants and the surveys menu. Audit records a request before serving audio;
   it does not prove that a human listened to it. Revocation denies new requests.

`new`, `reviewing`, `followup`, `resolved` and `discarded` are review statuses.
None deletes data or audio. Reports count uploaded feedback items, not unique
callers, survey invitations or all conversations. Queue-filtered status counts
cover all statuses; the status selector filters the displayed rows. No CSAT
score or sentiment is inferred from this free-form audio.

## Storage and bounds

The private `STATE/voice-feedback/feedback.sqlite3` stores audio as SQLite BLOBs
and metadata/audit in the same transaction. This avoids a file publication vs.
database commit orphan window. The directory is mode 0700 and the database
0600 on Unix. Keep this state outside public/static directories, including its
SQLite WAL/SHM sidecars; use one state directory per PBX and its queue policy.
There are no user-selected filesystem paths or original filenames.

Caps are 1000 items, 256 MiB of retained audio, 1 million audit events, 1000
characters per review note, 50 rows per report page, 100 audit events per item
page, and a cooperative 0.5-second SQL budget with 0.1-second busy timeout.
Writes require at least 256 MiB free disk. Reaching a cap rejects new writes;
there is no automatic retention deletion. Audio quotas do not include SQLite
indexes, WAL or audit text, so monitor total disk usage and back up the complete
database consistently. A failed audit write denies audio delivery.

## Integration for maintainers

The independent API is installed with:

```python
from sanequeue.surveys.voice_feedback_api import install
install(app, state)
```

Include `voice_feedback.html` and load `static/js/voice-feedback.js` after the
existing `ops-config` JSON. Register view `voice-feedback`, view element
`voice-feedback-view`, guarded by existing `surveys` menu permission, and a
customer satisfaction submenu. The script restores this view, aborts requests
and revokes audio object URLs on leaving it, and uses no polling. Settings may
override authorization paths with `SANEQUEUE_VOICE_ACCOUNTS` and
`SANEQUEUE_VOICE_POLICIES` (Flask config or environment).

Routes: `GET/POST /api/voice-feedback`, `GET/POST /api/voice-feedback/<id>`,
`GET /api/voice-feedback/<id>/audio/play`, `/audio/download`, and `/audit`.
Intake is a raw WAV request body with queue/session in query parameters,
`X-CSRF-Token`, and `Idempotency-Key`. It does not parse multipart uploads.
Current accounts and queue grants are reloaded on each request.

Telephone collection requires a separate explicit trusted intake adapter,
consent/retention policy, bounded capture and verified call/queue attribution.
It is intentionally not activated by this slice. Synthetic WAV/API/Node tests
are automated evidence; visual browser and real telephone tests remain separate.
