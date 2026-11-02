# Queue-visit report builder

Open the builder under Reports. This release supports the fixed `queue_visits` dataset. A conversation visiting several queues may produce several visits: this is not a unique-conversation or arbitrary CDR report. No free-form SQL is accepted.

1. Set the main report date range to at most 31 days. Table dates use Asia/Tehran and the panel language's calendar.
2. Select queues and columns in the builder. These queues are independent of the main page's queue filter; current queue grants always apply.
3. Leave grouping empty for detail rows, or choose up to two dimensions: queue, agent and outcome.
4. Optionally choose outcomes and minimum/maximum wait or queue-talk seconds. Empty means no condition. Zero is an actual numeric threshold. Unknown durations do not match numeric conditions.
5. Preview. Detail pages show 50 rows; Next page uses a bounded keyset cursor. Aggregates allow at most 500 groups and fail explicitly beyond this limit.
6. Enter a name and save a private definition. Editing and saving creates a new immutable version. New starts a separate definition. Limits are 100 definitions per owner, 50 versions each and 1,000 definitions per PBX. No audio or source-data retention policy changes.

## Metric contract

| Metric | Meaning / denominator |
|---|---|
| visits | Matching queue-visit records, not unique conversations |
| answered_known | Visits with a known answer timestamp |
| abandoned | Visits whose recorded outcome is abandoned |
| average_wait_seconds | Average of known wait values; denominator `wait_known` |
| average_queue_talk_seconds | Average of known queue-segment talk values; denominator `talk_known` |
| queue_talk_seconds | Sum of known queue segments, not necessarily all post-transfer talk |

Unknown is not zero. Empty results do not prove that no real calls occurred or that every source was complete. Grouped time is not an agent-presence/occupancy metric. Entry timestamps are filtered to `[start, end)`, clipped by the account assignment cutoff where applicable. Agents remain restricted to their authorized agent identities.

Each preview request reads the current archive. Late facts may arrive between pages: the definition version is immutable, but preview data is not a frozen snapshot. Use the official export center for snapshot-based files.

Caller masking is applied on the backend using current permissions. Revoking any queue in a definition blocks its preview instead of silently dropping that queue. Template IDs do not grant access to another owner's definitions. Metadata lives in a separate private SQLite database with immutable versions; no call records or recordings are copied into definitions.

## Limits and exports

Requests are limited to 16 KiB; archive reads have a two-second deadline. Backend detail pages are capped at 100 rows, aggregates at 500 groups. Invalid fields, SQL-like expressions, excessive date ranges and limits fail explicitly.

Custom-layout CSV/XLSX/PDF export is **not implemented**. Use the official export center for files; the builder's selected columns/grouping are not transferred there. The builder only reads the local reporting archive: it performs no AMI/PBX operations and no source-database queries.

If another edit changed the saved version, reload it before saving. A missing grant, expired scope or failed query produces an error rather than fabricated zero metrics. Deployment/load acceptance on live servers remains a separate test.
