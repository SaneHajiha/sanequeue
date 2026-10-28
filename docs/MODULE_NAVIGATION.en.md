# Modules and navigation

The reporting preview groups the authorized navigation into six modules. Expand a module with a click or Enter. Backend authorization remains mandatory for every endpoint.

| Module | Sections |
|---|---|
| Live monitoring | Overview, queue status, active calls, waiting calls, wallboard |
| Reports & analytics | Overview, calls and recordings, agent performance, duty and pauses, state intervals, calls during pauses |
| Team & shifts | Agents and membership, extensions and presence, shift planning |
| Telephony | Call controls, directory, extension waiting and callback, caller ID formatting, voice prompts, callback requests |
| Alerts & health | Active alerts, PBX health, audit trail |
| Administration | Queue rules and thresholds, users and permissions, organization and service, Telegram and Bale, capability status |

The mobile section selector uses the same authorized groups and shortcuts. Shortcuts open their parent view and focus the destination section. Keyboard navigation, reduced-motion preferences, Persian RTL/English LTR and existing light/dark tokens are preserved. No external UI runtime, remote font, or new PBX polling is introduced.

## Recording availability

Playback and download are separate capabilities, checked across all queues associated with a shared file, including basename/dated aliases. Audio waits at least 120 seconds after call completion, fresh caught-up SQL/CEL and queue-log import health, and a complete local projection.

Transferred or incomplete conversations, unknown downstream tails, ambiguous file ownership, multi-hop identity graphs and CDR durations extending beyond the known queue end are currently denied. Non-queue pause recordings require one proven CDR leg and permissions for every observed pause membership. Originals are never removed by this guard. A settling interval alone cannot prove completeness of arbitrarily delayed sources.

## Import safety and provenance

Pending CDR work drains before CEL enqueue, including at the 20,000-item capacity. A high-fanout identity no longer blocks the entire batch: the fallback inspects one identity with at most four lookup SELECTs per cycle. Outliers are retained as unresolved `identity_fanout_limit` and require explicit reconciliation; their raw CEL is preserved.

Source health exposes allowlisted reason codes only. Missing indexes, CEL reset, capacity and density failures remain distinguishable without exception details or private paths. A queue-log rotation coverage warning persists through later healthy cycles; unread rotated tails are not claimed recovered.

Identity evidence is frozen at first projection, reused on rebuild, and reused across metadata-only versions with unchanged channel identity. Legacy data without historical inventory is labeled `first_projection_inventory`; it is not a claim of historical inventory accuracy.

## Scope

Recording ownership is computed once per recording within each HTTP request, with a shared one-second proof budget and a maximum 200ms SQLite reader budget per proof; grants are rechecked separately and are never cached between users or requests. If the proof budget is exhausted, remaining recording controls stay unavailable for that response.

New queue-log checkpoints bound rotation uncertainty using the last caught-up observation (or the source timestamp while behind), with a 120-second safety margin. Only calls overlapping a retained gap are denied: calls completed safely before that boundary remain eligible. Up to 32 gap ranges are retained; older ranges are conservatively merged rather than forgotten. Legacy rotation markers without a lower boundary remain ambiguous and need explicit reconciliation.

This is navigation and reporting hardening in a draft preview, not a production certification. The collector, importer, web service and telephony adapter remain independent. Async large exports, scheduled reports, adherence analytics, full post-transfer conversation ownership and durable AI jobs are still separate work. Cross-version PBX and real RTP load tests remain necessary.
