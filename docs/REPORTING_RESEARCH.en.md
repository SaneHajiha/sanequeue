# Reporting and AI architecture research

Research date: 2026-10-25. **Design and acceptance specification, not a declaration that these features are implemented.** The detailed feature catalogue is in [Persian](REPORTING_RESEARCH.fa.md).

## Confirmed requirements

- Move agent activity, handled-call counts and hangup evidence into a unified reporting area, retaining a scoped self-service shortcut.
- Keep original reporting history without automatic deletion; archives, backups and capacity monitoring are required.
- Play and download existing call recordings using separate permissions and audited access. Reporting does not implicitly enable recording on all calls.
- Support local and cloud AI as optional configurable adapters. No cloud provider or transmission destination has been chosen, and no recordings have been sent externally.
- Lightweight normal installation: no mandatory GPU, heavy inference server, container platform or additional PostgreSQL service. Telephone processing takes priority.

## Sources reviewed

Official pages for Connect Stats, the two supplied VoiPing products, the public VOIZ CDR module, QueueMetrics reports/features, Asternic PRO, and Asterisk queue_log/CDR/CEL/MixMonitor documentation were reviewed. These establish published feature descriptions and event semantics, not independently verified commercial-product performance. No third-party product installer was executed.

- [Connect Stats](https://voipiran.io/products/connect-stats/)
- [VOIZ](https://github.com/voipiran/VOIZ)
- [Queue reports](https://voiping.ir/product/ماژول-گزارشات-و-مانیتورینگ-آنلاین-صف/)
- [PBX reporting](https://voiping.ir/product/ماژول-گزارش-گیری-حرفه-ای-از-مرکز-تلفن-voip/)
- [QueueMetrics reporting](https://www.queuemetrics.com/asterisk-call-center-reports.jsp)
- [QueueMetrics features](https://www.queuemetrics.com/features.jsp)
- [Asternic PRO](https://www.asternic.net/about.php)

## Reporting navigation

1. Management overview and period comparison.
2. Call details, conversation/leg/queue-visit distinction and event timeline.
3. Queue outcomes, waiting distribution, configurable SLA policies and overflow.
4. Agent activity, availability, reasoned pauses, workload and union-of-time accounting across concurrent queues.
5. Unanswered callers and auditable follow-up workflow.
6. Outbound/internal calls and activities performed while paused.
7. Callback/waiting request lifecycle with verified bridging evidence.
8. Recording studio: player, lazy waveform, timestamped notes, bookmarks and authorized downloads.
9. Business outcomes, reasons, tags and versioned notes.
10. Human-reviewed QA scorecards and actual survey responses.
11. Saved reports, filters, asynchronous CSV/Excel/PDF exports, scheduling and APIs.
12. Data sources, ingestion health, coverage, archival and recovery.
13. Optional AI transcription, analysis and evidence-backed decision support.

## Correctness rules

A CDR row is not necessarily a unique customer conversation. Each report distinguishes conversations, legs, queue visits and ringing attempts. Local channels and transfers must not multiply customer totals. Source IDs include PBX identity; historical agent assignments have validity intervals.

Queue completion party and final conversation hangup party are different. COMPLETEAGENT/COMPLETECALLER provide queue-segment evidence; later transfers need further explicit evidence. First observed Hangup ordering alone is not sufficient.

CDR billsec can include hold time. AHT must not add hold twice and must not fabricate missing wrap-up time. SLA policy, denominator, short-abandon exclusion, period anchor and source coverage are visible and versioned. Repeat contact is not proof of failed first-call resolution. Ring-no-answer does not prove intentional rejection.

A sample of 20 recent recording references resolved to existing WAV files on the laboratory host. This is not proof of content matching, audio quality or user playback authorization. Importer correctness, recording access and UI acceptance remain implementation gates.

## Lightweight architecture

Reuse the existing Python/ASGI application and existing Redis coordination. Build a separate reporting namespace and a durable reporting database; Redis is not the historical source of truth. Base mode uses indexed SQLite WAL with one writer and bounded jobs. PostgreSQL is an optional backend for greater scale or concurrent writers, not a mandatory base dependency. The current 90-day observed stores require migration into the non-expiring historical store before cache cleanup can discard unarchived data.

Use incremental queue_log checkpoints and rotation generations; CEL keyset ingestion by ID; CDR bounded indexed reads with late-arrival overlap and idempotent source fingerprints. The inspected CDR schema has no numeric primary key, so a generic `id > last_id` importer is invalid here. Do not run historical ingestion in HTTP request handlers or add browser-triggered AMI queries.

Use keyset pagination, precomputed aggregates, explicit report refresh and cached derived assets. Generate waveform peaks, PDF, ZIP and audio conversions on demand, with one low-priority worker, resource limits, deadlines and cancellation. Pause backfill/AI on pressure without restarting Asterisk. No zero-load or zero-latency guarantee is made; measure actual CPU, RAM, I/O, latency and call quality.

Store canonical times in UTC and record the source timezone of naive SQL dates. Display Persian/Gregorian calendars as presentation choices. Source clock skew and coverage gaps remain visible. Keep historical records without automatic deletion, while distinguishing expiring download artifacts/cache from original data and recordings.

## Recording and access model

Separate report visibility, full numbers, export, playback, download, bulk export, QA and AI permissions. Apply tenant/PBX/queue/agent/assignment scope to summaries, detail rows, background jobs, files and semantic retrieval alike. Never treat hidden navigation as authorization.

Recording paths come from validated source metadata and configured roots, not arbitrary browser paths. Use no-follow descriptors/type checks, private authenticated range streaming and access auditing. Recordings may be missing, still being written, unsupported or split into multiple segments. Unknown matching is not guessed.

Webhook delivery uses configured destinations, signatures, bounded retries and SSRF protection. Message scheduling rechecks permissions at execution and retrieval. Report builders use an allowlist of fields/operators, not arbitrary SQL supplied by users or models.

## Optional AI

- Timestamped Persian/English/mixed-language transcripts, synchronized player and reviewed corrections.
- Speaker separation based on actual separate channels where available; mono diarization remains inferred and does not identify a person from voice.
- Evidence-linked summaries, topics, intent, stated outcomes, promised actions and follow-up suggestions.
- Semantic search and natural-language questions restricted to authorized records; numeric answers are calculated by the reporting engine.
- Proposed QA grading with cited segments and human confirmation; no automatic adverse personnel decisions or AMI actions.
- Trend/anomaly analysis and capacity suggestions. Forecasts require sufficient history, backtesting and uncertainty intervals.
- Cost/duration quotas, job status, cancellation, model/prompt/schema versions and idempotent reprocessing.

Base installation does not download AI model weights. Local CPU/int8 ASR is an optional benchmarked adapter; cloud processing requires an explicitly selected provider, credentials and data policy. Heavy local LLM inference is not a PBX dependency. Local statistical/rule analysis is labelled accurately rather than presented as semantic AI.

Transcripts are untrusted data: instructions embedded in speech cannot trigger SQL, tools, messages or webhooks. Raw audio, transcripts, summaries and embeddings have consistent access scope. Evaluate silence/music hallucinations, Persian names/numbers, overlapping speakers, word/character errors, diarization errors, factual support, processing time, peak resources and cost before acceptance.

Candidate technical references: [faster-whisper](https://github.com/SYSTRAN/faster-whisper), [Whisper](https://github.com/openai/whisper), [pyannote.audio](https://github.com/pyannote/pyannote-audio). Model quality and speed on 8kHz telephone audio are not inferred from vendor benchmarks.

## Delivery and acceptance order

1. Persistent historical archive, schema migrations, bounded source adapters and source-health view.
2. Reporting navigation, filters and migration of existing activity; call/queue/agent reports.
3. Secure recordings and timeline linkage.
4. Comparison charts, outbound/callback/follow-up and asynchronous exports.
5. QA, real survey integration, report designer/schedules and optional AI adapters.
6. Replay/rotation/late-data tests, multi-leg and midnight cases, scope/recording security tests, recovery, measured load and actual installation compatibility pilots.

Runtime reporting and AI have not been installed by this research-only change. The existing PBX configuration and call processing were not altered.


## Implementation edge-case addendum

- Preserve explicit CEL LOCAL_OPTIMIZE relationships and channel aliases. Blind/attended transfers have distinct consultation intervals and handoff evidence; never infer a customer hangup from disappearance of a Local leg.
- Model ring-group/follow-me routing visits only with verified inventory/context evidence. Conference membership is an interval relation, not permission to merge all participating conversations.
- Optional versioned shift definitions distinguish login coverage, schedule adherence and tardiness; observation gaps do not prove absence. Historical VIP membership and explicit blacklist rejection evidence support separate reports.
- Bound online SQLite reads to five seconds with progress handlers and close readers promptly. Monitor WAL size/checkpoint lag; use bounded snapshots/jobs for exports. Monthly/quarterly archival shards require crash-safe manifests, complete checkpoint and no live writer before immutable access. Never place live WAL on a network filesystem or copy only a live .db file.
- Recording offsets remain nullable with source/confidence. VAD/ASR trimming preserves a segment-to-original timeline map and original audio. Pre-bridge speech is not blindly discarded; no fixed 40% cost reduction or hallucination elimination is promised.
- Persian ITN retains raw text, normalized text and span mapping, preserving leading zeros and distinguishing phone numbers, identifiers, amounts and currency units.
- Number display policies are full/masked/pseudonymous/hidden. Stable aliases use tenant/PBX-scoped HMAC with a secret key and version, not reversible-by-enumeration plain phone hashes. Contact names, transcripts, filenames and exports must obey the same policy.
