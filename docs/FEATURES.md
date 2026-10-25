# Monitoring feature matrix · beta.23

Status describes implemented behavior, not a promise of universal PBX compatibility.

| Area / بخش | Status | Behavior and evidence |
|---|---|---|
| Live queues / صف زنده | Live tested | QueueStatus, waiting callers, members, counters and Asterisk SL |
| Profile and help / پروفایل و راهنما | Live + automated | Password/phone changes revoke sessions; bounded avatars; bilingual help for 17 sections |
| Menu scope / دسترسی منو | Live + automated | Role ceilings, per-user allowed menus and server-side API checks |
| Queue scope / مجوز صف | Automated + live UI | Admin/supervisor/agent/viewer roles, server-side grants |
| Pause/resume / توقف | Live tested | Pause reason, minimum staffing checks, managed RBAC or legacy session gate |
| Penalty / وزن کارشناس | Live tested | Changed to 1 and restored to 0 |
| Dynamic membership / عضویت پویا | Live tested | Added/removed test supervisor endpoint |
| Caller priority / اولویت | Live tested | Synthetic internal caller moved to front; actual priority checked |
| Hangup / قطع تماس | Live tested | Only the synthetic test caller leg ended |
| Listen/whisper/barge / نظارت صوتی | Beta | Live ChanSpy connection and agent audio confirmed; directional audio/isolation incomplete |
| Minimum readiness / حداقل آمادگی | Automated | Per-queue absolute/percentage guard; does not cover external changes |
| Caller name/number/state / اطلاعات منتظر | Live tested | Queue-scoped details and role masking |
| Queue alerts / هشدار | Implemented beta | Per-queue count/time/AND/OR, durable cooldown/retries; Telegram and Bale delivery verified |
| SIP/PJSIP health / سلامت داخلی | Live tested | Root-exported extension/trunk inventory; web does not execute CLI |
| Channels/parking inventory | Live tested | Read-only; active channel legs are not unique calls |
| Call journey / مسیر تماس | Beta | Bounded live AMI event history; no pre-connection historical recovery |
| Wallboard/charts/theme / نمایش | Browser tested | Persian/English, RTL/LTR, dark/light, latest browser samples |
| Shift planning / شیفت | Automated + browser | Queue scope, timezone-aware dates, overlap rejection; no automatic PBX changes |
| Directory / دفترچه | Automated + browser | Queue-scoped caller-name matching and permissioned click-to-call; external saved contacts require opt-in |
| Audit / ثبت عملیات | Implemented | Accepted/rejected requests; 202 does not establish execution |
| Blind/attended transfer, pickup | Live beta | Exact scoped legs and local destinations; user-confirmed test-PBX acceptance |
| Park/retrieve controls | Live beta | Park slot observed, retrieval connected supervisor 300; user confirmed |
| Redis API / WebSocket | Live beta | No AMI fallback; 20 concurrent sockets tested; logout revokes existing socket |
| RTCP observations | Actual PJSIP RTCP + automated/UI | Only available scoped samples; no MOS estimation; jitter is RTP ticks |
| Daily agent activity / کارکرد روزانه | Automated + live | Observed state durations and pause reasons, Tehran day boundaries, own-assignment privacy; collector gaps excluded |
| Historical reporting / گزارش‌گیری | Next phase | No historical KPI/export acceptance claim |
| AI, STT, WebRTC, tenant isolation | Planned | Separate architecture, deployment and privacy work required |


ChanSpy behavior and mode flags follow the [official Asterisk documentation](https://docs.asterisk.org/Asterisk_20_Documentation/API_Documentation/Dialplan_Applications/ChanSpy/).

Current evidence, partial inventory privileges and limits: [beta.23 audit](AUDIT_BETA23.md). [Automatic installation](INSTALL.md) is the standard path.
