# Unanswered queue-member ring attempts

Open Reports → Unanswered ring attempts, choose the main dates/queue and calculate. Maximum range is 31 days; the visit-outcome filter does not apply.

One row is an archived RINGNOANSWER event, not a unique customer/conversation or abandonment. One caller can generate several offers to endpoints and queues. Do not infer human intent or blame. RINGCANCELED is excluded. Totals and queue/endpoint groups cover the full range; details are keyset pages of up to 100. The chart uses those exact groups, with local SVG/PNG export. Raw channels and caller numbers are not returned. Unknown endpoint identity remains unknown. Only currently authorized administrators/supervisors are supported; agent access needs separate historical member-assignment proof.

Source milliseconds become seconds. A valid zero is distinct from unknown. Means use known durations only, with an explicit count denominator. Membership in multiple queues does not erase actual offers; offer counts are never labelled unique conversations.

Visit correlation requires PBX, queue, call identity and a unique proven temporal interval. Missing entry, answer timestamp ties, ambiguous reentry and projection lag remain unproven. A visit reference grants no media access.

## Bounds and evidence

No AMI, PBX SQL or request-time DDL. Existing local archive time index only. Limits: at most five seconds or the archive's smaller deadline, 10,000 source events in the range including unrelated kinds, 4 MiB relevant payloads, 4 KiB per payload, 1,000 groups, 1,000 visit candidates per identity and 10,000 candidates overall. Exceeding limits fails explicitly rather than publishing partial totals. Narrow busy ranges; this is not certified as an unrestricted million-event report. Current source versions prevent correction duplication. Source health/no events never proves complete historical capture. Pagination is not a pinned export snapshot; new evidence can change subsequent reads.

API: GET /api/history/ring-attempts with the existing report date/queue contract. Responses, including denied/unauthenticated responses, are no-store. Python core/API tests and the actual-script frontend harness cover known/unknown/zero, repeated attempts, reentry, scope/cutoff, current versions, source limits, safe text and late-response/filter/navigation disposal. Synthetic checks do not replace real phone or load acceptance.

Event semantics and milliseconds: [official Queue Logs documentation](https://docs.asterisk.org/Operation/Logging/Queue-Logs/).


CSV summary: /api/history/ring-attempts.csv uses the same complete filtered groups (not the visible detail page), at most 1000 groups/512 KiB, with a fresh report_export grant on every selected queue. A denied export does not remove permitted viewing. Unknown numeric values are blank; spreadsheet formulas are neutralized. The UI hides stale export controls on filter/view changes. CSV is recomputed at download time, not a pinned asynchronous export snapshot. Standard queue-visit Excel/CSV controls now live inside the queue-visit report, so another report is not accidentally exported as visits.
