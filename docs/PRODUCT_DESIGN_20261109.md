# Product design and reporting requirements

Status: incremental design specification for the audited `master` baseline. See [audit and tracker](PRODUCT_AUDIT_20261109.md). Review evidence uses generated data from the loopback demo.

## Competitive review

| Reference | Published workflows and presentation | Requirement for SaneQueue |
| --- | --- | --- |
| QueueMetrics | Supervisor real-time panel, permissioned agent page, configurable wallboards and distinct report filters. | Start supervision at a filtered queue, show capacity and outliers together, and preserve filters when opening records. [Real-time panel](https://docs.loway.ch/QueueMetrics/060_TheRealTimeStatusPanel.html) · [Wallboard](https://docs.loway.ch/QueueMetrics/065_Wallboard.html) · [Agent page](https://docs.loway.ch/QueueMetrics/075_AgentPage.html) |
| VOIPIRAN Connect Stats | Persian contact-center reporting and visual analysis. A separate VOIZ project exposes telephone call details. | Use Persian labels and Jalali presentation consistently, with separate queue and telephone reporting entry points. [Connect Stats](https://voipiran.io/products/connect-stats/) · [VOIZ](https://github.com/voipiran/VOIZ) |
| VoiPing | Queue-specific live monitoring and response/abandonment/service-level reports. Separate PBX workflows provide source/destination and date filters, recordings, reason codes and Excel/CSV. | Keep queue visit filters separate from PBX origin/destination filters. Use separate permission checks for recordings and exports. [Queue reporting](https://voiping.ir/product/ماژول-گزارشات-و-مانیتورینگ-آنلاین-صف/) · [PBX reporting](https://voiping.ir/product/ماژول-گزارش-گیری-حرفه-ای-از-مرکز-تلفن-voip/) |
| FreePBX / PBXact | Queue Reporting and CDR Pro are listed separately, with configurable periods and call detail. | Surface the report grain and interval in the page title, chart and export, and provide a drill-down to evidence. [PBXact capabilities](https://www.freepbx.org/pbxact-features/) |
| Asternic | Lite and PRO distinguish reports from commercial supervisor actions, recordings, report designer and API capabilities. | Keep dashboards usable without active controls, and expose permissions and feature availability in context. [Edition comparison](https://asternic.net/litevspro.php.html) |

This matrix uses vendor documentation and product materials. Interactive commercial demos, comparative performance and site compatibility are outside this review.

## Workflows and navigation

Current backend roles are admin, supervisor, agent and viewer. Department and executive manager are workflow personas; they require a defined reporting permission model before distinct role rollout.

| Group | Existing views or entry points | Primary workflow and proposed access |
| --- | --- | --- |
| Monitor | Dashboard, Queues, Active calls, Waiting calls, Agents, Wallboard, Alerts | Supervisor selects an assigned queue, examines longest waits and readiness, then drills into a caller or member. Agent sees allowed queues and self activity. A wallboard hides caller identity by default. |
| Intervene | Call controls, agent membership/pause actions, Queue policies & alerts, Audit trail | Supervisor checks selected target, grant, state freshness and staffing; confirms an eligible action and follows the command's observed status. Admin manages policy. |
| Analyze queues | Agent daily activity, profile activity, optional queue summary endpoint | Department manager selects interval, team and queue, compares volume/service level, inspects visits, and exports with a separate grant. Executive sees aggregated trend and exceptions. |
| Analyze telephone | Existing call journey entry points, PBX health and Extensions & presence | Admin starts from a PBX/trunk/extension exception, correlates scoped evidence and asks for additional capture only if needed. Department manager sees PBX call metrics filtered by historical assignments. |
| Configure | Users & access, Organization & service, Telephone modules, Capabilities, Shift planning, Directory | Admin checks service/inventory health and grants, validates settings, and monitors installation or recovery. Supervisor uses scoped roster and directory. Agent uses the profile shortcut. |

Keep all 18 current menu choices reachable with the same grants. Derive desktop groups and the mobile jump menu from the same permission-filtered definitions. Show the queue selection and metric period together, keep contextual help collapsible, and preserve only non-sensitive filter choices in shareable URLs. Apply backend scope again on every details request.

## UI rules

- Keep existing Jinja, vanilla JS and CSS. Reuse `operations.css` variables for surface, ink, muted ink, line, focus, semantic alert and chart colors. Contrast-test color pairs in both themes before promoting them to shared tokens.
- Use Vazirmatn for Persian, the existing English sans-serif stack, logical alignment, and `bdi` for extension, channel and number values. Localize headings, status badges, units and empty messages independently of PBX-provided labels.
- Prefer heading, scope, status, KPIs, exceptions and then detail. Keep keyboard focus when polling redraws rows, restore focus when closing dialogs, and use a text label as well as a semantic color for connection status.
- Distinguish loading, no matches, observed zero, missing/partial coverage, stale, permission denied and service error. Avoid exposing caller details in generic errors, shared links or wallboard mode.
- Use readable integer ticks for counts and explicit time units. Compare queues with a common scale. Timeline labels and selected period follow the configured timezone, with UTC preserved in stored evidence.
- Verify responsive behavior at desktop, tablet, mobile and wallboard sizes. Check keyboard-only tab order, focus visibility, zoom/reflow, target sizes, status announcements and contrast before claiming WCAG 2.2 AA. [WCAG 2.2](https://www.w3.org/TR/WCAG22/)

## Metric and evidence dictionary

| Metric | Grain, calculation and source | Coverage rule |
| --- | --- | --- |
| Waiting now / longest wait | Current queue entries from AMI QueueStatus plus subsequent events. Count entries; take max elapsed wait. | Requires current complete collector state. Empty list after an authoritative snapshot is zero waiting. |
| Ready / ringing / busy / paused | Queue memberships from AMI QueueMember status and subsequent events, with wrap-up modeled by the collector. | One extension can appear in multiple queues. Show state unknown if endpoint status is missing. |
| Active calls / channels | Scoped observed call journeys and AMI channel events. A channel leg and a busy member are separate counts. | Keep active membership and channel metrics labeled. Unique conversations need a validated correlation model. |
| Answered / abandoned today | Persisted observed inbound records in `calls.sqlite3` with a start in the Tehran calendar day. An answered record has an answer time; a recorded abandon comes from the queue outcome. | Global recorder coverage can contain interruptions. Preserve observed zero only after a collection observation in the day. |
| Average speed of answer | Sum of answered observed waiting seconds divided by answered observations. | No denominator yields unknown. Avoid conflating PBX counter mode and daily observations. |
| Observed service level | Answers meeting configured threshold divided by answered plus abandoned observed visits. | Unknown if the denominator is zero or an included answer lacks a known threshold. Abandon-only coverage yields zero percent. PBX counter mode uses separate AMI semantics. |
| Mean talk / AHT / occupancy | Mean talk uses observed talk seconds per answer. AHT requires validated talk, hold and after-call-work definitions. Occupancy requires unioned duty and busy intervals. | Do not backfill unknown wrap-up or assume CDR billsec excludes hold. |
| Historical queue/PBX reports | queue_log for queue visits; CDR for billing paths and dispositions; CEL for channel/bridge/transfer stages. Keep source keys, import coverage, linked IDs and timezones. | Unobserved periods remain unknown. A CDR row may be one leg. Number or linked ID matching alone is insufficient for recording ownership or terminal causality. |

References for event semantics: [Queue log](https://docs.asterisk.org/Operation/Logging/Queue-Logs/) · [CDR specification](https://docs.asterisk.org/Configuration/Reporting/Call-Detail-Records-CDR/CDR-Specification/) · [CEL specification](https://docs.asterisk.org/Configuration/Reporting/Channel-Event-Logging-CEL/CEL-Specification/).

## Diagnostic workflow

Start with PBX identity, time window, queue visit and authorized unique/linked channel identifiers. Label queue entry, answer and completion observed only when the relevant event exists. Show a transfer as requested, completed by signaling, target answered, or outcome unavailable according to source evidence. To investigate a disconnect, align CEL bridge/transfer transitions with SIP dialog evidence before attributing a BYE or release to a participant. For one-way audio, capture directional RTP or RTCP and SIP offer/answer endpoint data for a short isolated call. Direct media, NAT, unavailable telemetry and external carrier hops limit what can be concluded. Restrict raw captures to authorized administrators, redact parties and retain them only for the documented diagnostic window.
