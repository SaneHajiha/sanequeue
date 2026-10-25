# Beta.25 acceptance evidence · 2026-10-25

## Automated and laboratory acceptance

- Windows Python 3.11: **346 passed, 4 skipped, 104 subtests passed**, 149.55 seconds. Two Linux provisioning tests and two Redis integration tests require their respective environment; they were not treated as passing locally.
- JavaScript syntax checks cover operations, planning, activity, organization and telephone modules. CI runs Python 3.10/3.11/3.12 with Redis; consult the linked commit checks for its actual outcome.
- Rocky Linux 8.10, Asterisk 20.12.0, PJSIP laboratory phones, two queues. API reads for operations, profile activity, notification configuration and telephone modules returned 200. Bundled prompt HTTP download matched SHA256 `f8ccb57efb71cbc174b0525c932c57d8e8ab107141d2a166069229d868698618` (240156 bytes).
- Real caller hangup was recorded as caller evidence (92 seconds talk / 2 seconds wait). No historical end-party inference was invented.
- Human confirmed callback prompt/confirmation, callback ringing/connection, corrected names on both phones, and key-1 waiting then connection when the destination became idle.
- Final callback job observed requester answer, target bridge and source end; measured connected duration **22.62 seconds**. This proves observed bridging/timing, not microphone quality on every telephone.
- Telegram and Bale: existing configured destination discovery and test-send APIs accepted delivery. Real credentials and destination IDs remain private.
- The user's actual AVIF image with a `.webp` filename saved successfully as a sanitized PNG logo; the private organization image is not a repository asset.
- CLI disable/restore reproduced all three original files byte-for-byte and restored uid/gid/mode. Reapply succeeded. Web disable/enable returned 200 and toggled the FastAGI bypass sentinel immediately. Asterisk PID remained unchanged.

## Bounded queue/web load

Owned, synthetic **Local** channels on the laboratory PBX; no external destinations. Stages 10/25/50/100 waiting calls, 100 HTTP requests per stage, 20 concurrent HTTP clients. 77.59 seconds total.

| Waiting calls | HTTP p95 | HTTP errors |
| --- | ---: | ---: |
| 10 | 0.469 s | 0 |
| 25 | 0.697 s | 0 |
| 50 | 1.119 s | 0 |
| 100 | 1.664 s | 0 |

At 100: total system CPU 20.94% across 6 vCPUs; web 85.18 MB, collector 41.25 MB, Redis 9.8 MB, Asterisk 146.84 MB. Per-process CPU values use a single-core scale and should not be confused with total system percentage. No additional AMI snapshot collections were triggered by web reads. Owned test legs were cleaned up, the member pause state restored, and 100 synthetic module-ledger rows removed. PBX cumulative counters were deliberately not reset.

This is **not** a test of 100 SIP/RTP conversations, transcoding, recording, sustained peak traffic or carrier behavior.

## Visual checks

1. Captured the live queue/operations screen before editing. Findings: overloaded vertical hierarchy, ambiguous healthy label for zero ready staff, an orphan performance tile and tiny ring captions.
2. Checked the updated light and dark queue views. Fixed row alignment, queue identity/health separation, staffing labels and distinct service-level ring.
3. At a 390-pixel viewport, queue cards stacked without document horizontal overflow. Performance tiles reflowed into two columns.
4. At 1440 pixels, fullscreen contained all eight summary tiles in one row; their bounds were inside the viewport. The source-aligned wallboard clock matched the latest snapshot to one second. Browser viewport overrides were reset after testing.

Screenshots are retained in the local acceptance artifact. The public documentation retains synthetic demonstration images; private organization logos and trunk/contact identifiers were not added to public screenshots. Screenshot checks do not certify WCAG compliance.

## Remaining gates and limitations

- Independent installations on Issabel 4/5 and Asterisk 16/18/20, both SIP/PJSIP, remain required. One laboratory PBX does not establish the complete matrix.
- The structural telephone adapter recognizes the existing supported legacy hooks and refuses unknown/drifted files. Fresh or customized dialplans require an explicitly supported adapter; silent generic hooking is not claimed.
- Structural apply/restore defers while calls are active. The web disable flag bypasses new managed telephone actions without restarting Asterisk; it cannot undo an already bridged call.
- Deep historical queue_log/CDR analytics, CRM, WebRTC and voice AI remain separate phases. Observed daily activity/callback rows are not a full historical reporting warehouse.
- Directional whisper/barge audio still needs microphones on both relevant phones. API acceptance or a bridge event alone is insufficient proof of all audio directions.
- No claim of zero bugs, universal production safety or a 10/10 certification is made. Start with a backup and a limited pilot, then run the installation-specific acceptance checklist.
