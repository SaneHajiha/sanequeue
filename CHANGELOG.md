# 2.1.0-beta.26 · 2026-10-25

- Fix Rocky/EL8 private-state permission provisioning using no-follow file descriptors; add Linux regression coverage.
- Includes all beta.25 queue, notification, directory and telephone-module improvements.
- Beta.25 public installer rolled back safely; use beta.26 for installation.

# 2.1.0-beta.25 · 2026-10-25

- Queue/operations visual hierarchy, accurate health labels and fullscreen summaries.
- Explicit observed daily metrics, agent activity and callback outcome evidence.
- Optional bounded FastAGI callback/waiting/caller-ID modules with bundled audio and safe restore.
- Notification languages and debounced critical PBX health alerts.
- Directory editing, AVIF logo upload and immediate telephone-module disable fixes.
- See [release notes](docs/RELEASE_BETA25.md) and [test evidence / pilot limits](docs/AUDIT_BETA25.md).

# 2.1.0-beta.24 · 2026-10-25

- Browser visual follow-up: keep all three dashboard panels in their desktop columns, remove legacy queue-card grid tracks and prevent mobile profile-header overflow.
- Fullscreen toggle now exits the embedded fallback correctly, shows its current action, and supports Escape when native fullscreen is unavailable.
- New desktop/mobile screenshots and documented visual acceptance; beta.23 monitoring and scope behavior retained.

# 2.1.0-beta.23 · 2026-10-25

- Correct wildcard RBAC controls in the browser, optional per-queue staffing enforcement and discovered-extension membership management.
- Supervisor wallboard keeps its summary inside fullscreen; stable queue identity colors, compact waiting sparklines and a labelled readiness/waiting comparison replace empty charts.
- Independent count/time rules, reason cards and custom reason labels; staffing restrictions remain an explicit separate option.
- Personal first/last name, queue status, internal callback dialing and bounded daily activity by pause reason, with assignment-scoped personal history.
- Queue-scoped directory caller names and optional saved-contact outbound dialing with server-resolved destinations.
- Bounded IVR entry/selection observations and explicit queue-leg hangup evidence; unknown final parties remain unknown.
- Off-loop bounded SQLite activity writes, reconnect coverage boundaries and stale-writer rejection; no per-request AMI queries added.
- Tests cover scope, race protection, Local channel evidence, daily activity boundaries and directory destination validation.

# 2.1.0-beta.22 · 2026-10-25

- Automatic isolated installation: private Redis, separate restricted AMI identities, independent collector/gateway, sanitized local phone/trunk inventory and rollback backup.
- Correct internal-phone selection excludes numeric SIP trunks; server rejects assigning a trunk as a user phone.
- Role ceilings, per-user menu selection, API section checks and queue-action permissions; managed RBAC removes the manual temporary queue gate.
- Self-service name/phone/password/avatar; current-password checks and session revocation for sensitive changes.
- Per-queue count/time thresholds with independent enable switches and any/all matching. Telegram and Bale private configuration, test delivery and durable independent retries/cooldowns.
- Real fullscreen supervisor wallboard with optional permission-checked caller numbers, rotating waiting lists and clearer capacity/trend charts.
- Contextual Persian/English help for all 17 sections, generated illustrated manuals and updated installation/validation records.
- Actual RTCP reception and bounded 100-concurrent-Local-call acceptance; these do not certify 100 SIP/RTP calls or all Issabel/Asterisk versions.
- External review regressions: discard expired collector snapshot replies, restore AMI configuration if uninstall reload fails, and bound account sessions/branding inputs.
- Explicit root-owned internal-context allowlist supports customized PBX dialplans without admitting numeric trunks by name; theme-aware capacity colors and section-only tab refresh.

# Changelog

## 2.1.0-beta.21 — 2026-10-25

- Opt-in Redis-backed HTTP and authenticated WebSocket gateway; ordinary browser reads never fall back to AMI.
- Separate read/control identities, shared session revocation, durable command ledger, fenced capacity reservations and optional alert outbox.
- Exact scoped blind/attended transfer, park/retrieve, pickup, internal click-to-call and active hangup; phone acceptance for transfer/parking/pickup on the test PBX.
- Fix Local channel provenance across bridges, ringing scope, transferred-device target discovery, RTCP sample direction and late command outcomes.
- Audit and fix light/dark contrast, caption sizes, keyboard focus and narrow-screen controls across monitoring and management views.
- Add bilingual deployment guidance and strict evidence-based audit. Reporting, WebRTC and AI remain deferred; broad PBX version certification is not claimed.

## 2.1.0-beta.20 — 2026-10-24

- Add an opt-in independent asyncio AMI collector: bounded transport/state, event journal, heartbeat, reconnect/resync and Redis lease fencing.
- Preserve external cancellation when AMI responses race with shutdown; fix bridge switches, late leaves, channel rename, wrap-up expiry and queue re-entry counters.
- Add real Redis CI tests and live shadow validation on Asterisk 20.12. The existing web adapter is not migrated and WebSocket is not delivered in this release.
- Add secure offline password recovery, branded asset URLs with traversal tests, bilingual architecture/recovery documentation, strict scored audit and database migration/indexing plan.
- Preserve legal third-party attribution. No Asterisk restart or dialplan change is required.


## 2.1.0-beta.19 — 2026-10-24

- Product Design audit follow-up: derive capability status totals from the catalogue and localize their numbers.
- Add a labeled mobile section selector with all authorized views, replacing the long horizontal menu below 760px.
- Keep desktop navigation and existing call-control safeguards unchanged.


## 2.1.0-beta.18 — 2026-10-24

- Add isolated Linux WSGI server deployment and external private state.
- Coalesce snapshots across viewers, back off AMI failures and cache optional health probes.
- Resolve SIP/PJSIP hint targets from actual channels; reject ambiguous targets.
- Fix successful queue-control HTTP response handling and AMI health timeout handling.
- Protect the last admin, reject duplicate phones and invalidate changed-password sessions.
- Add scoped SQLite shift planning and directory with overlap checks.
- Fix new-menu headings; provide bilingual login and photographed guides.
- Validate actual Asterisk 20.12 queue controls; document unverified platforms and audio clearly.

## SaneQueue 2.1.0-beta.16 — Read-only call journeys and transfer tracking

- Persistent read-only AMI event listener with bounded memory and reconnect/backoff.
- Incoming trunk stage (verified configured map or explicit ingress tag; else unverified/unknown), queue join, ringing, answering, Blind/Attended transfer, destination ringing/bridge, final observed Hangup.
- Timeline lives in main dashboard, queue monitoring, detailed active calls, and public Wallboard (caller numbers hidden).
- Existing active/waiting calls, queue member status, agent controls, users, alerts and other advanced views preserved; quick links from queue monitoring.
- Privacy: only scopes with access to every queue touched by a multi-queue call see its journey; no AMI Linkedid or channel ID in API; contact numbers only to authorized users.
- Quality: no false bridge confirmation from a mere Newstate Up or a single BridgeEnter; recognizes standard channel ID suffixes.
- Limitations: no command to transfer calls from web yet; best-effort memory tracking, no history recovery, no multiworker HA, no authoritative trunk without mapping, real PBX events not tested.

## 2.1.0-beta.15 — Simpler navigation & click-first user grants (2026-10-23)
- Eight visible primary menu choices: five monitoring, three admin-only; legacy details remain internally accessible from existing shortcuts.
- PJSIP endpoint inventory and queue-members fallback fill user phone selectors; PBX trunk names are excluded by default from the numeric extension picker.
- Queue access is checkbox multi-select; action permissions are checkbox-based; account and grant save are processed together via /api/accounts/with-grants.
- One-click AMI test-LAN / SSH tunnel presets; custom settings behind an advanced option; AMI credentials remain typed by the admin and are never baked into ZIP.
- Corrected a new API route declared after blocking app.run, so it is registered before Flask starts.
- Offline checks: 64 selected Python unit/regression tests plus Chromium mocked-API UX check with 4 viewport sizes passed.
- New shift scheduling and transferred-call tracking architecture documented but NOT deployed or live validated.

## 2.1.0-beta.15 — Simpler navigation & click-first user grants (2026-10-23)
- Eight visible primary menu choices: five monitoring, three admin-only; legacy details remain internally accessible from existing shortcuts.
- PJSIP endpoint inventory and queue-members fallback fill user phone selectors; PBX trunk names are excluded by default from the numeric extension picker.
- Queue access is checkbox multi-select; action permissions are checkbox-based; account and grant save are processed together via /api/accounts/with-grants.
- One-click AMI test-LAN / SSH tunnel presets; custom settings behind an advanced option; AMI credentials remain typed by the admin and are never baked into ZIP.
- Corrected a new API route declared after blocking app.run, so it is registered before Flask starts.
- Offline checks: 64 selected Python unit/regression tests plus Chromium mocked-API UX check with 4 viewport sizes passed.
- New shift scheduling and transferred-call tracking architecture documented but NOT deployed or live validated.

## 2.1.0-beta.14 — Queue UX, supervisor wallboard and user center
- New all-screen per-queue Wallboard and queue selection
- Clear ring/talk/hold/pause/offline status chips
- Cumulative queue KPIs and member lists in Queue menu
- Dedicated admin accounts/grants center with real API form handlers
- Dark/light responsive styles and browser regression tests
- No change to AMI call-control implementation; live validation required

## v2.1.0-beta.9 — 2026-10-23
- Correct outbound survey agent Pause reason, no IVR; modal reason picker and per-queue survey activity counter.
- Fixed missing policy/editor/queue-summary JavaScript handlers previously causing runtime initialization errors.
- Six-stage redacted AMI diagnosis plus independent CLI and private-LAN target defaults.
- Fixed all-queue waiting diagnostic aggregation, added 78-test selected regression suite and browser-mock UI verification.
- Local-only Windows debug launcher port 18887.

## 2.1.0-beta.6 — 2026-10-23
- Reference-style operational dashboard with live queue readiness rings, waiting room, agent roster and compact active-call table.
- Rebuilt agent action grouping: consistent primary pause and 3-column operation grid.
- Suppressed false no-ready alert for completely empty default queue.
- Audit UI now labels HTTP accepted distinctly from verified PBX action outcome.
- Isolated Windows port 18884, no PBX configuration changes.

## Earlier history

## 2.1.0-beta.4 — UI consistency & test readiness (2026-10-23)
- 12 operational subpages get dedicated responsive page identity and four live-derived metrics.
- Queue comparison lane bars, waiting spotlight, agent roster tiles, queue-presence summary, wallboard statistics, alert triage and clearly locked supervisor control status.
- Browser actions remain blocked without both a validated live source and time-limited test authorization; API retains its independent server-side gate.
- Offline browser visual verification: pages, 390/768/1300 layouts, mocked API, no JavaScript errors, no horizontal mobile overflow.
- No direct test-PBX command executed by the assistant. Existing beta3 AMI adapter is unchanged.
- No production deployment; SSH tunnel / scoped test account remains recommended.

See docs/FEATURE_STATUS_FA.md and START_HERE_18882_FA.md.
## [2.1.0-beta.3] - 2026-10-23

- Private LAN IPv4 and arbitrary valid queue for read-only AMI diagnostics; write scopes unchanged.
- Live sampled waiting/ready trends and capacity donut with no historical database.
- Read-only PBX inventory for CoreShowChannels, PJSIPShowEndpoints and ParkedCalls (permission-dependent).
- Professional feature catalog with clearly marked beta/planned modules.
- Isolated 18881 Windows launch with persistent logs and updated bilingual docs.
- 36 offline/regression tests passed; no live PBX validation performed.

# Changelog

## [2.1.0-beta.1] — 2026-10-23

### Added
- Dark dashboard redesign, six KPI tiles, three-column overview, waiting/agent/presence/call-control/wallboard/alerts views, quick navigation, mobile layout.
- Native read-only Asterisk 20 AMI QueueStatus event adapter and staged diagnostics (probe vs data adapter).

### Fixed
- Failed AMI tests no longer clear typed values or disable an existing live data session.
- Legacy QPanel parser is no longer required to render queue 8001 data in local test mode.
- Isolated startup on port 18879 with no unit tests run during launch.

### Safety
- API settings hide secret; no AMI password stored on disk; localhost-only server and SSH tunnel; scoped 30-minute test control gate remains.
- No live Asterisk integration or supervisor command validation claimed.

---

# 2.0.0-beta.6 — 2026-10-23

- Add short-lived, test-queue-scoped supervisor control guard (off by default; 30 minute expiration).
- Add temporary test control enable/disable controls, live AMI state and test notes to the Persian/English UI.
- Require same-origin and CSRF on AMI control/settings mutations.
- Store AMI password in memory only; strip previous plaintext credentials if local settings file is carried forward.
- Launch on isolated port 18878, preserving prior previews.
- Preserve all existing queue/live calls/agent screens; Classic view and historical reporting remain out of scope.
- Document Asterisk 20 manager.conf privileges and rollback.

## 2.0.0-beta.4 — 2026-10-22

- Moved Windows demo to 18877 to avoid occupied preview ports; independent build identity and preflight.
- Added local-only AMI queue diagnostics and SSH tunnel guide; no credentials or live call writes.
- Existing beta.3 scope continues; no real-PBX validation yet.

## 2.0.0-beta.3 — 2026-10-22

### Fixed
- Avoid old local demo on port 8765: this sample-data build now binds to 127.0.0.1:8766 by default.
- Display version dynamically from the Python package, not an obsolete static sidebar label.
- Add localhost-only build identity endpoint and read-only Windows process/port diagnostic.
- Cache-bust dashboard styles/scripts by package version.

### Documentation / Design
- Source-grounded live feature matrix (VoiPing and FOP2), read-only Asterisk test procedure and AI roadmap.
- Standalone GitHub profile kit with banner and avatar extracted from user-provided old CV.
- UI concept artwork is labelled conceptual and is not a screenshot of the working application.

### Validation
- Static release smoke tests. Mock AMI tests require project Python dependencies and do not imply production compatibility.

# Changelog

## 2.0.0-beta.2 — 2026-10-22

### Added
- Queue Health view with per-queue capacity, overload/zero-ready indicators and longest waiting caller.
- Live Calls view with active queue-member sessions and a focused waiting-room table.
- Operational shortcuts (`/` search and `R` refresh), responsive queue cards and clearer visual severity.
- Masking of displayed caller numbers by default to reduce casual exposure in shared operations rooms.
- Release/recovery documentation and professional GitHub profile draft.

### Changed
- Reports removed from the operator navigation; historical reporting remains out of scope.
- Optional AMI channel details extended with `LiveChannel` and `LiveChannelState` for scoped queue members.
- Python 3.13 compatibility: removed legacy distutils usage without requiring legacy setuptools.
- Explicit title, navigation and visual design improvements; version advanced to beta.2.

### Validation
- Mocked AMI unit tests and static checks are required before staging; production PBX controls remain unverified.

## 2.0.0-beta.1 — 2026-10-22

### Added
- Persian/English operations dashboard, local fonts, dark theme and wallboard.
- Queue/agent filters, live waiting callers, staffing indicators and browser audio alerts.
- Explicit viewer/agent/supervisor/admin roles and own-interface agent controls.
- Pause reasons, minimum staffing count/percentage checks, immediate caller priority.
- Allowlisted supervisor listen/whisper/barge, dynamic membership and penalty controls.
- Scoped supervisor audit trail and optional active channel details.
- Modern Flask runtime compatibility, dedicated-user installer, systemd and Docker templates.
- Installation, security, feature and contribution documentation.

### Fixed
- Python 3 queue filtering previously used an unevaluated map iterator.
- Historical routes now require authentication and authorized queue access.
- Arbitrary form credentials no longer implicitly authenticate control requests.
- Call controls require a role, CSRF token and authorized target.
- Connection failure is distinguished from valid zero traffic.

### Scope
- Monitoring beta; reports are deferred to phase two and disabled by default.
- Live control/audio behavior requires a controlled pilot on each PBX.
- Legacy Python 3.6 compatibility is for migration, not a recommendation for new installs.

## Upstream history

See [the original QPanel repository](https://github.com/roramirez/qpanel) for versions through 1.1.1 and the inherited Git history.

## [2.1.0-beta.2] - 2026-10-23

- Separate Windows test build on loopback port 18880.
- Fix failed live-adapter reconnect from deactivating a previously working session.
- Resolve Asterisk `hint:100@ext-local` to PJSIP/100 for *test-queue only* ChanSpy prefix.
- Detect static members before QueueRemove; preserve `Membership` from QueueStatus.
- Increase AMI connection-request timeout to 30 seconds without changing 15-second dashboard polling timeout.
- Add offline regression tests, dedicated Windows safe-test runner and environmental preflight.
- Add professionally benchmarked Persian feature inventory identifying implemented/test-only/planned scope.
- No real Asterisk writes or production compatibility certified.

## [2.1.0-beta.5] - 2026-10-23
- Monitoring can read all AMI queues using `*`; writing actions remain explicitly authorized per selected queue.
- On-demand AMI `ListCommands` capability matrix differentiates action grants from event-read permission; redacted classified errors.
- PJSIP Contacts and outbound registrations read-only inventory, plus channels/endpoints/parking.
- Entire dashboard and internal cards receive coordinated dark/light theme overrides, responsive layouts, contrast corrections, and a new top-to-bottom content order based on reference design.
- Port 18883, persistent Windows startup logs, additional regression tests. No live PBX write command executed by the assistant.

## v2.1.0-beta.8 — 2026-10-23
- Per-queue live summary modal with SL, hold/talk, answered, abandoned and ready/paused counters.
- Configurable per-queue live alert thresholds and optional Bale notifications (disabled unless explicitly configured).
- Custom Pause reasons, configurable staffing roster and 50%/count exit ceilings.
- Queue/permission-scoped supervisor policy engine and local editing UI (real authentication still pending).
- Single-process pending-action reservations for rapid concurrent pause/remove requests.
- Local port 18886, standalone Windows launcher and test documentation.
