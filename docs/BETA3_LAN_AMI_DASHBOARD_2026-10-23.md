# SaneQueue 2.1.0-beta.3 — LAN AMI and live visualization

This is a **local, isolated Windows ZIP** for supervised testing. The full changed source **is not yet synced to this GitHub branch**; the branch and PR remain documentation-only. The production default branch is unchanged.

## New local implementation

- Read-only queue monitoring accepts RFC1918 private IPv4 AMI hosts (10/8, 172.16/12, 192.168/16) as well as 127.0.0.1. Arbitrary queue IDs within a restricted identifier pattern can be *read*. Public and link-local destinations are blocked.
- AMI connection probe, successful live parser activation, and request errors remain separate. No settings are discarded when the probe fails, no password is written to disk.
- Staged **write** actions remain bounded to test queue 8001 / test member/supervisor and expire after 30 minutes; this is independent of read-only queue selection.
- Six operational metrics, waiting/ready observed trend plots, staffing donut, queue/agent panels, threshold alerts, Wallboard and mobile RTL.
- Optional on-demand and redacted AMI health probes: CoreShowChannels, PJSIPShowEndpoints, ParkedCalls. No raw caller IDs are returned from these probes.
- In-app catalog distinguishes built beta components from future OpDesk/FOP2-style modules (Transfers, parking controls, WebRTC, CRM/contacts, RTP quality, AI copilot, production RBAC).
- Windows launcher on 127.0.0.1:18881 keeps diagnostics visible and writes startup logs.

## Security

Prefer an SSH tunnel and AMI account permitted on PBX loopback. A direct AMI LAN connection uses plaintext TCP; only allow exact workstation source IP with a /32 ACL on the test PBX, without exposing AMI to the Internet. All previously disclosed test passwords should be rotated.

## Verification

- 36 Python offline/regression tests passed, including AMI mock socket protocol, RFC1918 validation, queue parsing, role safety gate and redacted health output.
- Python compile and Node JS syntax validation passed.
- Chromium mocked-API preview showed six metrics, two SVG trends, staffing donut, 12 capability cards and 3 health buttons without JS page errors; mobile had no horizontal overflow.
- **No actual test-PBX connection or write-action test was made by the assistant.**
- Production/multiuser deployment, WebRTC, transfer and parking controls, trunk monitoring, CRM and AI copilot remain to be developed.
- Historical reporting intentionally remains out of scope.

The ZIP handoff includes Persian/English README, LAN/SSH AMI instructions, updated feature matrix, tests and source code. Do not merge documentation-only PR as a functional release.