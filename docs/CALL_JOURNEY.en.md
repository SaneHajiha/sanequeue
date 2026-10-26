# Reading call paths and hangup evidence

Open **Reports → Queue visits → Journey & audio → Show journey & recorded
relationships**. The selected dates, historical assignment cutoff, agent scope
and every queue linked to the proven channel identity still apply. A route is
partial evidence, never a complete conversation or an audio permission.

## Two different endings

**Queue segment ended by** comes from explicit queue completion evidence. It
describes that queue visit. Transfer, parking or another call leg can continue
after a segment ends. This label is never copied into the final-call answer.

**Consistent direct hangup evidence** is shown only for exactly two proven legs,
one direct-pair identity and explicit agreeing CEL cause identities on both legs.
All current HANGUP records for each leg must agree; the last timestamp does not
override contradictions. Hangups before the direct connection do not establish
its final cause. Repeated identical causes are allowed. Raw uniqueids, channel
names, dialplan strings and audio paths are not shown by this report.

The final party may be the caller, the explicitly connected queue agent, or an
identified leg whose human role is not established. Do not infer the human from
the first channel to disappear. Standard CEL data may lack the explicit
`hangupsource_uniqueid` field required here; missing evidence stays unknown.

The panel explains unknown results: incomplete direct-peer evidence, missing
cause, conflicting causes, cause before connection, complex transfer/conference,
restricted or unproven legs, or an evidence limit. Even a proven direct cause
does not certify complete end-to-end coverage of a transferred conversation.

## IVR before the queue

The owned caller's recorded IVR app/selection events can now appear **before**
queue entry, inside the selected period and assignment cutoff. Explicit safe
`ivr-N` app contexts identify menu N. A known `IVRSelection`/`SaneQueueIVR`
USER_DEFINED event supplies a key; an explicit numeric `ivr_id`, if present,
identifies its menu. For example, `IVR 3 · Key: 2` means recorded evidence, not a
guess that every caller entered that menu. The application does not install new
PBX hooks or collect ordinary in-call DTMF for this feature.

Earlier CDR numbers, relationships, unrelated apps and downstream legs do **not**
gain a wider window. A UID also associated with a queue outside the user's grants
blocks its CEL details, including pre-queue IVR. Missing imported events or IVR
instrumentation cannot be reconstructed from timing, linkedid or audio alone.

## Performance and migration

Projection version 9 adds a small current-source CEL identity projection indexed
by `(pbx, uid, ts, event_id)`. The existing reporting worker builds/replays it in
bounded batches; raw evidence and import checkpoints remain intact. No HTTP
request builds an index or replays history. CEL graph output waits until the
projection catches up, while the report remains explicitly partial.

The actual journey query seeks this UID/time index, then primary-key/current
source-version rows. It no longer scans unrelated JSON payloads to locate a UID.
The shared five-second maximum read deadline, 100 UID / 1,000 evidence entry /
4 MiB evidence limits still apply. A fresh identity is refused when its proof
budget is exhausted; the graph does not bypass foreign-queue checks.

Browser requests are cancelled/invalidated on filter changes, detail close,
navigation, report reload or DOM replacement. Old success/error responses cannot
restore prior private data. Reopening fetches current authorization. New labels,
reason text and IVR references follow the panel language and Tehran time zone.

## Verification boundary

Tests exercise conflicting/duplicate/missing and pre-connection causes, cutoff
and foreign-queue IVR protection, no widened CDR/downstream graph, source identity
correction, worker migration with no HTTP DDL, exhausted ownership budgets, and
`EXPLAIN QUERY PLAN` on the actual query with unrelated CEL rows. The shipped JS
is tested with stale success/failure, dialog close, navigation/reentry, detached
DOM and escaped text. These are not real-phone, visual, load or multi-PBX
certification; complete IVR instrumentation and ambiguous transferred-call final
attribution remain outside the proven scope.
