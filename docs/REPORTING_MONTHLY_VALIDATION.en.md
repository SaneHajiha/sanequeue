# Synthetic monthly reporting validation

Executed on the authorised lab server, 2026-10-28. Dataset: September 1–30, 2026, Tehran time; exactly 1,000 synthetic call identities per day. Total: **30,000 identities, 33,330 queue visits, 193,500 events**. Transfers explain the difference between identities and visits. Scenarios include caller/agent-ended segments, transfers, abandonment, open/incomplete evidence, multi-queue membership and unanswered ring attempts. No live calls, audio, CDR/CEL or RTP were generated.

All 65 primary checks passed, including daily/monthly aggregates, chart totals, distinct identities, exact exports and explicit safety-limit behavior. An additional 60 daily agent-ranking comparisons passed. The monthly chart contained 30 days and 33,330 visits; the hourly heatmap matched the same total. Thirty unanswered attempts matched visits, totaling 60 known ring seconds.

Both CSV and XLSX contained exactly **33,330 distinct visit rows**, with matching per-queue counts. CSV: 17.41 seconds wall / 7.42 CPU seconds / 5,870,149 bytes. XLSX: 59.18 wall / 29.18 CPU seconds / 3,728,110 bytes. The principal verifier took 83.71 seconds wall, 40.14 CPU seconds and 34,020 KiB peak child RSS.

Generation and initial verification took 331.06 seconds wall, 89.17 CPU seconds and 27,268 KiB peak child RSS. Runs were sequential, with a half-CPU quota, 256 MiB cgroup memory limit and low IO weight. RSS excludes cgroup page-cache accounting; observed generation MemoryCurrent reached about 244 MiB. Asterisk PID 133041 was unchanged before/after generation and the principal verifier. This is not proof of live-call latency, packet quality or concurrent capacity.

The new partial ring-event index avoided scanning unrelated events; the monthly ring calculation took roughly 8 ms. Existing archives without the index retain the conservative bounded fallback. Initial index creation on a large existing archive requires a separate controlled migration measurement.

**Monthly rankings and monthly presence remain incomplete:** they correctly returned the existing visit/interval limits without publishing partial results. Daily rankings passed for all 30 days. Safe background aggregation is still required for full monthly ranking/presence at this volume. Counts such as answered, transferred and incomplete overlap and must not be summed as exclusive categories.

Reproduce using `tools/generate_reporting_month.py` with `--write --destination NEW_DIRECTORY --days 30 --calls-per-day 1000`, then `tools/verify_reporting_month.py --fixture NEW_DIRECTORY --write-exports --export-output ANOTHER_NEW_DIRECTORY`. Destinations must be isolated and new. The running application was not pointed at this fixture; deployed UI/HTTP and live telephony acceptance remain separate. See the Persian companion for detailed evidence and limitations.
