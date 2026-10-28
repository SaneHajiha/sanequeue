# SaneQueue development instructions

## Scope and source of truth
- Continue the existing SaneQueue application. Preserve current features and API contracts.
- Read docs/ai-workflow/PROJECT_CONTEXT.md, FEATURE_INVENTORY.md and DEVELOPMENT_STATUS.md first.
- Inspect the actual cwd, Git remote, branch, revision and dirty/untracked files before changes.
- Do not assume local HEAD matches the published reporting branch or the deployed preview.
- Never reset, clean, stash all, force-push, or overwrite unrelated work.

## Approval gates
- Get explicit user approval before push, deployment, broad architecture changes, dependency installation or a substantial visual implementation.
- Present a concrete design/proposal and preserve the approval decision in DECISIONS.md.
- Ask before changing this AGENTS.md. Small low-risk fixes can use a proportionate workflow.

## Product and design workflow
- Inspect code and inventory features before auditing or redesigning.
- Use available Product Design and UI UX Pro Max guidance; record missing or unconfigured tools honestly.
- Design approved editable screens/components in Figma when file access is available; do not claim synchronization without a verified result.
- Reuse existing Flask/Jinja, vanilla JavaScript, CSS and local assets. No framework rewrite without approval.
- Keep an isolated HTML/Vite Storybook or workbench outside the production runtime after approval.
- Cover Loading, Empty, Error, Success, Disabled and permission-denied states.
- Support Persian RTL and English LTR, light/dark themes, keyboard/focus accessibility, responsive dense tables and reduced motion.
- Give each KPI a source, unit, denominator, period and clear unknown-data treatment; add contextual guidance.

## Telephony, reports and privacy
- No AMI/PBX SQL polling per HTTP request. Preserve collector/cache/WebSocket boundaries and bounded background workers.
- Keep report readers short, bounded and read-only; do not pin WAL for long exports.
- Union overlapping agent-duty intervals across queues; do not label visits/legs/offers as unique conversations.
- Recheck current role/menu/all-queue permissions for reports, audio, transcripts, exports and background publication.
- Unknown evidence stays unknown; linked IDs or matching numbers alone do not prove ownership or causality.
- Do not run disruptive PBX actions or restart Asterisk/MariaDB during UI tests. Use deterministic synthetic fixtures.
- Do not publish credentials, access files, SSH keys, tokens, live databases, customer audio/transcripts or private screenshots.
- Preserve required licenses and notices.

## Quality and evidence
- Use repeatable Playwright E2E/visual tests only after approved setup, plus existing Python and real-script frontend tests.
- Test navigation, controls, forms, filters, permissions, stale responses, RTL/LTR, themes and responsive states.
- Compare screenshots for the same viewport, locale, theme, state and synthetic dataset.
- A snapshot image, API 200 or passing CI alone does not certify all visual/live/load behavior.
- Record exact revision, commands, passed/failed/skipped tests and untested cases in TEST_RESULTS.md.
- Update feature inventory, design tokens, Figma references, decisions and development status after approved changes.
- Report outcomes in Persian. Never claim a tool ran, a feature is complete or a live check passed without evidence.
