# Optional generative transcript assistance

This opt-in slice sends an already completed ASR transcript to an operator-approved **loopback** chat-completions service. It does not install/download a model, perform inference in HTTP/PBX workers, or send audio. Results contain suggested summaries, themes and follow-up ideas with references to pinned source segments and original-recording offsets. They are always machine-generated, require human review and do not trigger actions, employee ratings or employment decisions. A citation does not prove an inference is correct.

Open a permitted recording's completed ASR card and choose **Optional generative analysis** next to its transcript button. Select Persian/English, confirm human review, submit and manually refresh status. Citation links reveal the corresponding original transcript excerpt and timestamps, never model-provided URLs or new audio grants.

## Operator opt-in

Disabled by default. Prepare and independently resource-limit an existing model service outside the web/telephony process. The [official llama.cpp server documentation](https://github.com/ggml-org/llama.cpp/tree/master/tools/server) describes one compatible protocol implementation; no particular model, Persian accuracy or inference performance was verified by this change.

Create `/etc/sanequeue/generative.json` as a regular private `0600` file readable by the `sanequeue` worker:

```json
{"enabled":true,"allow_local_transcript_processing":true,"endpoint":"http://127.0.0.1:8080/v1/chat/completions","model":"local-model-id","timeout_seconds":30,"max_tokens":1024,"json_mode":false}
```

Use the actual served model ID. Optional `api_key` belongs only in this file, never HTTP forms, jobs or logs. Enable `json_mode` only if the service supports `response_format: json_object`; complete validated JSON is required either way. Set web environment `SANEQUEUE_TEXT_ANALYSIS_ENABLED=1` to allow creation. The optional [systemd unit](../deploy/sanequeue-generative.service) has `ConditionPathExists=/etc/sanequeue/generative.enabled`. Adapt its explicit paths to the installation; do not point its private generative job database at the ASR store or archive.

Worker CLI:

```sh
python -m sanequeue.reporting.generative_worker --jobs /var/lib/sanequeue/generative-jobs.sqlite3 --sources /var/lib/sanequeue/ai-jobs.sqlite3 --archive /var/lib/sanequeue/history.sqlite3 --config /etc/sanequeue/generative.json --scratch /var/lib/sanequeue/generative-scratch --accounts /var/lib/sanequeue/local_accounts.json --policies /var/lib/sanequeue/local_queue_policies.json --once
```

Remove `--once` for the optional service loop. Config `enabled=false` or the existing module-disable switch prevents publication and terminates an active child request at its next check. Removing the systemd Condition marker alone does not stop an already running process. UI cancellation prevents result publication; closing the client connection does not guarantee that the separate model server stops computing.

## Explicit constraints

- Only HTTP literal `127.0.0.1`/`::1`, ports 1024–65535, exact `/v1/chat/completions`; no DNS hostnames, userinfo, query, fragments, redirects, environment proxy or cloud URL. Operators must ensure a loopback service is not itself a cloud proxy; this client cannot attest to that service's internals.
- Source job/spec and transcript/segments are pinned by SHA-256. At most 16,000 text characters, 48 KiB, 200 segments; text must match complete segment content. Oversize/misaligned input is rejected, never truncated. HTTP request/response limits are 64 KiB; private result limit is 128 KiB. Citation IDs and original evidence are independently validated.
- Model socket timeout at most 30 seconds; the actual wall-clock fence is the supervised worker's 45-second budget and killable child. Do not run the network helper standalone: a socket timeout alone does not impose a hard deadline on slow-drip headers/body. One worker at a time. Queued/running quota: three per owner, ten globally; lease recovery at most three attempts. Resource deferral does not consume an attempt.
- Owner isolation and current role, reports/audit menus, all frozen/current queue grants, caller-details and recording-play proof are checked before/during/after processing and on reads. Source changes deny publication/read. Summaries are private; lists never read full results. No transcript/audio/report retention deletion is introduced. Only this worker's temporary files are cleaned.
- The unit's `CPUQuota=10%`/`MemoryMax=192M` constrain the network worker and its child, **not the separate inference service**. Real-model load, Persian accuracy and live-call impact still require independent acceptance tests. Synthetic HTTP/worker tests do not establish production inference performance.

## Integration

Call `sanequeue.api.generative.install(app, ai_store, archive, role=role, sections=sections, can_queue=can_queue, authorize_source=callback)` once. The callback receives `(source_spec, deadline=None)`, performs current exact-identity recording/visit authorization and returns proven recording queues, not a boolean. Existing `ai_authorized(..., by_identity=True, deadline=deadline)` is suitable. The adapter then rechecks every capability across the frozen/current union. Load `generative-reports.js` using the project's `theme_static` helper with `defer`, after `ai-reports.js`. Existing ASR code is unchanged.
