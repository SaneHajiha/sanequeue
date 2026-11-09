# SaneQueue 2.1.0-rc.1

This candidate combines the beta.27 reporting and PBX history changes with the RTL/LTR navigation and accessibility foundations, preserving the existing queue, agent, organizational and general-PBX reporting workflows.

- Contact center: queue visit history, service and wait metrics, agent activity, call journeys, scoped CSV exports, and existing report builder and schedules.
- General PBX: observed CDR segments, extension/trunk/DID summaries, trends, classification, full-range filters and exports. The summary shows ingestion and projection freshness separately from historical coverage.
- Operations: explicit unknown metrics, consistent filters, scope checks on controls, staffing reservations, per-account WebSocket limits, and server-side session revocation.
- Installer: checked archive for remote bootstrap, read-only preflight, isolated Python and optional offline wheelhouse, package checks, serialized installation, health gates and backup restoration that retains failed installation data.

Use the [Persian operating guide](INSTALL_RC1.fa.md) on an isolated Issabel 5 / Rocky Linux 8 / Asterisk 20 clone. Production acceptance requires exercising an upgrade and snapshot recovery, actual call paths, SQL/CDR/CEL ingestion, recordings, and concurrent call load on representative infrastructure. See the [integration record](ai-workflow/INTEGRATION_20261109.md) for the branch and feature matrix.
