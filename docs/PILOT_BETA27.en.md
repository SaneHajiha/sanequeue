# SaneQueue beta.27 reporting pilot

This is a controlled pilot, not cross-PBX or concurrent-call certification. Current source is on `feature/reporting-phase2`; master does not contain all reporting development. See the [Persian acceptance record](PILOT_BETA27.fa.md), [service control contract](SERVICE_MODULE_CONTROL.md) and [open reporting scope](REPORTING_COMPLETION_CHECKLIST.en.md).

```bash
REF=feature/reporting-phase2 # replace with the complete reviewed commit SHA
curl -fL --proto '=https' --tlsv1.2 \
  "https://raw.githubusercontent.com/SaneHajiha/sanequeue/$REF/scripts/install.sh" \
  -o /tmp/sanequeue-install.sh
sudo env SANEQUEUE_REF="$REF" bash /tmp/sanequeue-install.sh
sudo sanequeuectl status
```

Run on the Linux/systemd PBX host. The first installation asks for the administrator's chosen password, optional supervisor extension and panel origin. No shared default password. Existing accounts survive upgrades. The isolated Python environment does not replace Issabel Python. Asterisk/MariaDB are not restarted; SaneQueue services are restarted. No development browser/design dependencies or AI models are installed by this script.

Queue data comes from queue_log. CDR/CEL requires an explicitly provisioned SELECT-only local SQL configuration at `/etc/sanequeue/reporting-sql.ini`; administrator PBX database credentials are never copied into the web app. Missing/disabled sources remain unavailable, not zero evidence. Telephone adapters are a separate idle-guarded activation stage.

```bash
sudo sanequeuectl disable --module plans --dry-run
sudo sanequeuectl disable --module plans
sudo sanequeuectl enable --module plans
sudo sanequeuectl disable --module reporting --cascade
sudo sanequeuectl enable --module reporting
sudo sanequeuectl enable --module exports
sudo sanequeuectl enable --module plans
```

Supported worker groups: monitoring, reporting, exports, plans, ai, generative, surveys, media. Optional AI and telephone surveys require explicit configuration/opt-in. Disabling a parent checks dependents; re-enabling a parent does not automatically enable children. Persistent systemd conditions preserve disabled intent across service restarts/upgrades. Callback, internal wait and caller-ID features share FastAGI and use their own panel settings, not a separate FastAGI shutdown.

Evidence: 1010 local Python passes/20 skips/334 subtests at the recorded checkpoint; 30 Chromium tests; installed administrator login, actual charts/calendar and CSV/XLSX/PDF downloads. The actual filtered archive returned 491 visits/43 answers/448 abandoned. Projection-copy migration retained all 17603 raw events, caught up at version10 in10.7s wall/2.7sCPU/~23MiBRSS. Actual plans disable/restart-condition/enable passed. No host reboot was tested.

Synthetic monthly agent aggregation validated 30000 IDs/33330 visits at25% of one CPU:53.4s wall/13.3sCPU/~32MiBRSS. This was offline data processing, not SIP/RTP or50–100 concurrent calls. Two upgrade bugs were fixed (legacy state alias and owner-only export directories). Automatic rollback was observed on failed initialization/web acceptance. Asterisk PID stayed unchanged; that alone does not certify call continuity on every PBX.

The monthly operator CLI still lacks live-permission job/API integration. Independent CDR builder/custom PDF, proven pre-queue intervals and other explicit completion gaps remain development. External trunks and additional PBX versions need separate acceptance. Keep the pilot's claims aligned with the completion checklist.
