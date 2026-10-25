# Independent review · beta.22 candidate

An external Gemini review was requested after the initial automated, browser and test-PBX acceptance. Its findings were checked against the actual source and regression tests; a model opinion is not execution evidence or production certification.

## Actual coverage

The advanced-model round read six complete account/security modules supplied as text: `qpanel/local_accounts.py`, `sanequeue/security/login.py`, `permissions.py`, `profile.py`, `organization.py`, and `sessions.py`. The imported repository archive was not fully extracted by the review interface. No complete-repository external approval is claimed.

A compact JSON source export covers 150 active runtime, deployment and test files without images/vendor binaries. Parts 1–3 of 10 were acknowledged; the large conversation became unresponsive after sending part 4. Review continued in smaller module conversations: seven AMI/state/journey/API modules; installer, provisioner, emergency lifecycle, four service/timer definitions and two test modules; six control/policy/ledger/permission modules plus the complete application bootstrap; the complete operations JavaScript, main template, accessibility stylesheet and organization/planning scripts; and eight gateway, alert, inventory, entrypoint, planning and privacy modules. Several files occur in multiple rounds. Vendor code, every historical test and the imported ZIP were not independently read. Advanced-model quota became unavailable during the engine round; subsequent replies used the lightweight model. Neither transport failure nor a model's approval is a passing runtime check.

## Findings and independently verified resolutions

| Finding | Assessment and change | Regression evidence |
|---|---|---|
| One user's repeated successful logins can evict other users from a global session cap | Valid P1. Limit each user to the latest 10 sessions, migrate existing rows on startup, retain deterministic insertion order even with equal/backward clocks, add expiry indexes. | `test_repeated_login_only_retires_the_same_users_oldest_sessions`, `test_existing_session_rows_are_capped_during_upgrade` |
| Non-object organization JSON breaks all rendered pages | Valid P2. Bound file size, validate the decoded object and public fields, fall back to safe identity defaults. | `test_corrupt_branding_structure_cannot_break_page_context` |
| Image decoder exceptions escape the organization upload handler | Valid P2. Convert invalid image exceptions to validation errors; dependency/storage failures return 503. | Actual oversized PNG header in `test_decompression_bomb_header_returns_validation_error` |
| Menus cannot be reset through explicit `None` | API ambiguity confirmed; “permanent lock” overstated because selecting all permitted sections already worked. Separate omitted values from explicit reset, preserve least privilege on role edits, add a select-all-role-sections control. | `test_menu_reset_is_explicit_while_omitted_permissions_are_preserved` |
| Clearing an optional phone unnecessarily depends on live inventory | Valid P2. Administrator/viewer may clear a phone with the current password even when inventory is absent; agent/supervisor still require a phone. | `test_clear_phone_does_not_require_available_inventory` |
| Reused account name inherits an old avatar; admin list drops display name | Valid P3. Remove the avatar before completing account deletion, expose the saved display name, provide self-service picture removal. | `test_avatar_removal_and_account_reuse_do_not_expose_old_picture` |
| Late packets from expired collector requests become live events | Confirmed by a failing regression before the fix. Ignore unmatched packets carrying our `sq-` request namespace while preserving events tagged by other AMI clients. | `test_expired_snapshot_packets_cannot_become_live_events`; 30 engine/security tests and 9 subtests passed |
| Uninstall leaves modified AMI configuration after reload failure | Confirmed. Restore the backed-up file and its ownership/mode on apply/reload errors, then attempt to reload the restored configuration; leave the module stopped and report failure. | `test_failed_manager_reload_restores_original_configuration`; 9 maintenance tests passed |
| Customized internal endpoint contexts are classified as trunks | Previously documented limitation, now implemented as a validated root-owned exact context allowlist; upgrades preserve existing values and numeric trunks stay excluded. | `test_custom_context_is_explicit_and_does_not_admit_numeric_trunks`, `test_custom_context_configuration_is_bounded_and_validated` |
| Four native dialogs lack accessible names | Confirmed. Associate each dialog with its title and connect extension-field helper text. | Browser located the profile dialog by its accessible Persian name and verified closing returns focus to `profile-open` |

Additional in-house findings addressed canonical username/menu consistency, shared-IP login budgets, atomic runtime account-config replacement, serialized account deletion with grant/session cleanup, account-limit validation before writing, and server-policy alert sound ordering.

Global Flask request size is already limited to 1 MB; the individual upload decoders also enforce 512 KB and 4 megapixels. The review's generic multipart-limit suggestion did not establish an unbounded-buffer defect in the installed streaming WSGI adapter.

## Findings rejected after checking the actual code

- `complete=False` during reconciliation and PBX reload is intentional: concurrent events are journaled while the old state is not current, so supervision must fail closed. Gemini withdrew the unsafe suggestion to keep it actionable.
- There are no concurrent `synchronize()` callers in this implementation; three pending loops do not exceed the limit of eight. Backoff does not permanently terminate the collector.
- Channel/bridge state is bounded and rebuilt periodically from the PBX; bridges use `_put`. The claim of unlimited orphan growth was withdrawn. A guessed TTL could wrongly remove a valid long call.
- Cross-queue journeys require all touched queues; number-restricted projections clear caller, destination and timeline details. Gemini withdrew its unsubstantiated leak finding.
- Cache expiry uses monotonic time; both wait operands use epoch time. There is no mixed-unit subtraction. NTP steps remain an operational clock consideration.
- `QueueBusy` has a server-mode Flask handler in `demo_monitor.py` returning HTTP 409; absence from an isolated controller excerpt is not evidence of a 500 in the installed application.
- Python `Path.is_file()` follows valid file symlinks. Distribution service files and the CLI symlink are different objects; the installed unit files are regular files.
- The initial stale check is guarded by `lastReceipt`; HTTP refresh uses a `pending` lock and clears retry timers. Gemini withdrew its startup/retry claims after inspecting those guards.
- Private wallboard numbers require permission and an explicit checkbox, reset on exit, and cannot unmask server-redacted data. The generic leak assertion was withdrawn.
- Queue policies normalize and validate `cooldown_seconds` before alert delivery; a missing-key error from a hand-built unnormalized policy was not reproduced on the production path.
- Per-snapshot Flask request contexts recheck authentication and revocation. A repeated client allocation alone is not demonstrated memory leakage; broad viewer concurrency still needs deployment-specific measurement.
- Native dialog focus restoration was verified in Chrome. Announcing every frequently rebuilt table body was not adopted: existing live summary/status regions convey updates with less screen-reader noise.

HTTPS repository downloads verify certificates. Independent release signatures/checksums are supply-chain hardening, not an established TLS bypass. HTTP on a private address is a documented laboratory option; production acceptance must configure the supported HTTPS origin/reverse proxy. No trustworthy site certificate or domain is invented automatically.

## Disposition and target-environment acceptance

The core module review/fix/follow-up rounds above are complete; confirmed defects were corrected and unsupported findings were rejected against code or browser evidence. This does not certify all repository lines or prove absence of every defect. Final CI and candidate identity are recorded in the pull request/release. Other PBX versions, realistic RTP/recording/supervision and viewer load, full directional supervision audio, HTTPS/site configuration and assistive-technology combinations remain target-installation acceptance tasks. Theme-aware capacity colors and section-only visibility refresh were also improved during the in-house follow-up.

فارسی: دورهای نقد و اصلاحِ ماژول‌های اصلی بالا انجام شدند و موارد معتبر با تست یا شاهد مرورگر بررسی شدند. خوانده‌شدن تمام خطوط مخزن توسط Gemini یا تضمین نبود همهٔ باگ‌های ممکن ادعا نمی‌شود؛ پذیرش نسخه‌های مختلف سرور، بار صوتی واقعی، تنظیمات محل و ابزارهای کمکی در محیط هدف انجام می‌شود.
