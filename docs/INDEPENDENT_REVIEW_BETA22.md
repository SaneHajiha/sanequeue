# Independent review · beta.22 candidate

An external Gemini review was requested after the initial automated, browser and test-PBX acceptance. Its findings were checked against the actual source and regression tests; a model opinion is not execution evidence or production certification.

## Actual coverage

The advanced-model round read six complete account/security modules supplied as text: `qpanel/local_accounts.py`, `sanequeue/security/login.py`, `permissions.py`, `profile.py`, `organization.py`, and `sessions.py`. The imported repository archive was not fully extracted by the review interface. No complete-repository external approval is claimed.

A compact JSON source export covers 150 active runtime, deployment and test files without images/vendor binaries. Part 1 of 10 was acknowledged. Further exchange is pending restoration of the browser connection; the advanced model quota also became unavailable, with only the lightweight model remaining. These are review-transport limitations, not passing checks.

## Findings and independently verified resolutions

| Finding | Assessment and change | Regression evidence |
|---|---|---|
| One user's repeated successful logins can evict other users from a global session cap | Valid P1. Limit each user to the latest 10 sessions, migrate existing rows on startup, retain deterministic insertion order even with equal/backward clocks, add expiry indexes. | `test_repeated_login_only_retires_the_same_users_oldest_sessions`, `test_existing_session_rows_are_capped_during_upgrade` |
| Non-object organization JSON breaks all rendered pages | Valid P2. Bound file size, validate the decoded object and public fields, fall back to safe identity defaults. | `test_corrupt_branding_structure_cannot_break_page_context` |
| Image decoder exceptions escape the organization upload handler | Valid P2. Convert invalid image exceptions to validation errors; dependency/storage failures return 503. | Actual oversized PNG header in `test_decompression_bomb_header_returns_validation_error` |
| Menus cannot be reset through explicit `None` | API ambiguity confirmed; “permanent lock” overstated because selecting all permitted sections already worked. Separate omitted values from explicit reset, preserve least privilege on role edits, add a select-all-role-sections control. | `test_menu_reset_is_explicit_while_omitted_permissions_are_preserved` |
| Clearing an optional phone unnecessarily depends on live inventory | Valid P2. Administrator/viewer may clear a phone with the current password even when inventory is absent; agent/supervisor still require a phone. | `test_clear_phone_does_not_require_available_inventory` |
| Reused account name inherits an old avatar; admin list drops display name | Valid P3. Remove the avatar before completing account deletion, expose the saved display name, provide self-service picture removal. | `test_avatar_removal_and_account_reuse_do_not_expose_old_picture` |

Additional in-house findings addressed canonical username/menu consistency, shared-IP login budgets, atomic runtime account-config replacement, serialized account deletion with grant/session cleanup, account-limit validation before writing, and server-policy alert sound ordering.

Global Flask request size is already limited to 1 MB; the individual upload decoders also enforce 512 KB and 4 megapixels. The review's generic multipart-limit suggestion did not establish an unbounded-buffer defect in the installed streaming WSGI adapter.

## Remaining review gate

Complete the remaining source exchange and follow-up critique of the AMI engine, action plans, deployment rollback and frontend. Then run relevant regressions and publish the final candidate identity and acceptance record. Testing other PBX versions, realistic RTP/recording/supervision load and full directional supervision audio remain target-installation acceptance tasks.

فارسی: یافته‌های معتبر بالا اصلاح و با تست بررسی شدند. بازبینی خارجیِ کل مخزن هنوز تکمیل نشده و تأیید کامل Gemini یا تضمین نبود همهٔ باگ‌های ممکن ادعا نمی‌شود.
