# SaneQueue application design system · 2026-11

> Scope: Operations UI for SaneQueue 2.1.0-beta.26. **Presentation-only** unless a later PR explicitly includes approved product functionality. Every module in the existing 18-item navigation remains available with its server-side permissions.

## Principles

1. **No fake data.** Live counters are derived from AMI/Redis and browser-observed samples as annotated by each feature. Never imply that a sampled browser chart is a durable historic report.
2. **Fidelity before decoration.** Alert thresholds, queue identity, connection freshness, and operator availability must remain readable at a glance. Asterisk channels are not unique calls.
3. **Safe supervisor actions.** Hide nothing about confirmation, test-target scope, stale data, unknown outcomes, and permission failures. AMI acceptance is not proof of an audio result.
4. **Local-first bilingual UX.** Persian RTL and English LTR share a single semantic layout using logical CSS properties. Never reverse telephone numbers or queue codes.
5. **Role-appropriate information.** Admin, supervisor, agent and viewer permissions remain enforced on the server; UI grouping is not authorization.
6. **Token-first design.** Use the new `sanequeue-design-system.css` as the single late-loaded override instead of adding more ad-hoc selectors to `operations.css`.

## Navigation architecture

| Group (FA / EN) | Existing view keys | Main task |
|---|---|---|
| عملیات لحظه‌ای / Live operations | `live`, `queues`, `calls`, `waiting`, `wallboard` | Understand live load and prioritize service |
| کارشناسان و تیم / Team & contacts | `agents`, `presence`, `shifts`, `directory` | Manage people, memberships and contacts |
| سرپرستی و کنترل / Supervision | `control`, `alerts`, `audit`, `policies` | Authorized controls, incident response and traceability |
| سیستم و مدیریت / System & admin | `pbx`, `features`, `users`, `telephony`, `settings` | Diagnose infrastructure and administer the system |

Maintain all 18 `data-view` values and all 18 matching `*-view` panels. On mobile, the existing `#view-jump` selector exposes **every authorized section**; do not replace it with fewer curated links. Group headings are decorative/structural and do not affect permissions.

## Visual tokens

| Role | Light | Dark | Purpose |
|---|---|---|---|
| Canvas | `#f4f7fa` | `#0d1b2b` | Reduce nonessential contrast |
| Surface | `#ffffff` | `#172b3b` | Cards, tables, controls |
| Text primary | `#142d3f` | `#edf4f9` | Essential data |
| Text muted | `#526b7d` | `#adc3d3` | Metadata, legends |
| Border | `#d8e3eb` | `#365064` | Distinguish panels |
| Action accent | `#087f87` | `#6edbd7` | Focus and interactive status |
| Success | `#177c67` | `#67d9b5` | Ready, healthy (only with evidence) |
| Warning | `#a76e17` | `#f1c37d` | Elevated wait / pending |
| Danger | `#b43847` | `#ff8997` | Confirmed fault or destructive action |

Do **not** use red only to distinguish state. Every status needs visible text or a companion symbol. Queue identity colors must not override semantic fault colors. Test foreground/background contrast for all themes, including selected navigation and badges.

| Foundation | Values |
|---|---|
| Type | Vazirmatn (locally bundled), Segoe UI fallback |
| Body / table | 14px / 12–13px with approximately 1.7 line-height |
| Headline | fluid 21–28px; panel titles 15px |
| Metrics | fluid 23–31px; tabular numerals |
| Spacing | 4, 8, 12, 16, 20, 24, 32px |
| Radii | 8, 12, 16, 20px |
| Touch targets | at least 44px for primary actions on mobile |
| Desktop canvas | 1760px max content width |
| Breakpoints | 1450, 1300, 1100, 930, 760, 420px |

## Page-level visual expectations

- **Overview:** critical alerts and connection freshness above or beside first-decision KPIs. Capacity, waiting callers and available staff can be compared without scrolling on standard desktops.
- **Queues:** queue identity, service level target and provenance, ready/busy/paused counts, longest wait, and pressure by capacity.
- **Calls:** sortable/searchable primary table with explicit trunk/source and call-chain context when known; show **unknown** rather than inventing hangup/transfer causes.
- **Waiting:** wait duration and queue position take priority; phone number remains masked unless allowed.
- **Agents / presence:** distinguish ready, ringing, talking, wrap-up, paused and unavailable; show queue membership scope.
- **PBX:** no accidental green 'healthy' when RTCP/PJSIP data is unknown. RTCP jitter units and missing measurements must be labeled.
- **Supervisor controls:** show the target, action, permission and confirmation; pending and unknown operations require reconciliation before retry.
- **Alerts / policies:** separate per-queue thresholds from notification channel configuration; surface cooldown and tests.
- **Wallboard:** support TV distance, anti-burn-in refresh and a safe masked-number mode.
- **Users, shifts and directory:** consistent form labels, empty states and server validation errors.
- **Telephony modules:** differentiate installed/beta/planned controls and label callback completion evidence.
- **Audit:** operations log is not historical CDR/reporting.

## Historical reports: design is **not implementation**

The current beta documents historical reporting as *next phase*. When implementing reporting, maintain two clear future product areas:

1. **Call-center reporting:** queue SLA with denominator/target, abandoned patterns, ASA, AHT, occupancy (state assumptions), wait distribution, agent activity, transfer path, callback outcomes and queue-level permissions.
2. **PBX-wide reporting:** CDR for all authorized extensions/trunks, direction, duration/billsec, answer/termination when observable, call-chain journey, missed calls, per-department and per-trunk breakdowns.

Reports must show timezone, retention, data completeness, joins between `queue_log` and CDR, filter scope and export permission. Do not present them as ready until backend data acceptance tests exist.

## Chart rules

1. Use line/area for *time series*, horizontal bars for queue or agent comparison, stacked bars for states with a clearly labeled total, and histograms for duration distributions.
2. The x-axis is always an explicit local clock range. Show sampled vs persisted data. A blank metric means 'not measured', never zero.
3. Charts must have accessible data equivalents (table or summary) and series legends with text. Avoid 3D, excessive gradients, and red/green-only encoding.
4. Limit chart animation when `prefers-reduced-motion` is set. Keep plotted values anchored to real API fields.

## Responsive contract

- 1440px desktop: six compact KPI cards and a three-column overview when capacity permits.
- 930px tablet: two overview columns or single-column fallback.
- 760px mobile: mobile jump selector, readable actions, two KPI columns, vertically stacked content, horizontal scrolling **within tables only**.
- 420px: keep actions tappable and avoid truncating a customer's critical wait/connection status.
- LTR and RTL: use `margin-inline`, `padding-inline`, `text-align:start`, and `bdi dir=ltr` for numerical identifiers.

## Tests and acceptance

Automated contract tests: render template safely for each role; exactly 18 known view mappings in source; all menu buttons have corresponding panels; all new assets are linked; no changes to AMI event parsing, command dispatch or RBAC. Run the existing full Python suite and the new `tests/test_design_system_contract.py`.

Manual acceptance matrix (test in **fa-IR RTL and en-US LTR**, **light and dark**, **1440 / 1024 / 768 / 390** viewport):
- Every available navigation button opens the correct panel; denied sections stay denied.
- Mobile dropdown reaches every authorized panel.
- Live socket connected / stale / disconnected / fallback states distinguish data confidence and keep unsafe actions disabled.
- Number masking, scope and origin of metrics are preserved.
- Focus visibility, keyboard-only navigation, scroll containment and reduced motion work.
- Confirm dialogs, transfer/park/spy controls and empty states do not overlap.
- Jinja and browser console have no errors, and none of the 18 sections are missing.
- Real Asterisk control and audio tests run only in an isolated, approved test PBX.

## Release plan

1. Review CSS and IA changes in this branch.
2. Run repo CI plus manual browser matrix in staging.
3. Complete individual page refinements and durable reporting in separately reviewable PRs.
4. Only merge to `master` after live-data verification and sign-off; do not deploy a prototype directly to production.
