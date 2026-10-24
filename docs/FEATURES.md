# Monitoring feature matrix · beta.18

Status describes implemented behavior, not a promise of universal PBX compatibility.

| Area / بخش | Status | Behavior and evidence |
|---|---|---|
| Live queues / صف زنده | Live tested | QueueStatus, waiting callers, members, counters and Asterisk SL |
| Queue scope / مجوز صف | Automated + live UI | Admin/supervisor/agent/viewer roles, server-side grants |
| Pause/resume / توقف | Live tested | Pause reason, minimum staffing checks, session control gate |
| Penalty / وزن کارشناس | Live tested | Changed to 1 and restored to 0 |
| Dynamic membership / عضویت پویا | Live tested | Added/removed test supervisor endpoint |
| Caller priority / اولویت | Live tested | Synthetic internal caller moved to front; actual priority checked |
| Hangup / قطع تماس | Live tested | Only the synthetic test caller leg ended |
| Listen/whisper/barge / نظارت صوتی | Beta | ChanSpy request accepted; audio needs manual confirmation |
| Minimum readiness / حداقل آمادگی | Automated | Per-queue absolute/percentage guard; does not cover external changes |
| Caller name/number/state / اطلاعات منتظر | Live tested | Queue-scoped details and role masking |
| Queue alerts / هشدار | Implemented beta | Thresholds, cooldown, optional Bale integration; outbound delivery not tested here |
| SIP/PJSIP health / سلامت داخلی | Live tested | Endpoint/peer and registration inventory; not RTP/MOS quality |
| Channels/parking inventory | Live tested | Read-only; active channel legs are not unique calls |
| Call journey / مسیر تماس | Beta | Bounded live AMI event history; no pre-connection historical recovery |
| Wallboard/charts/theme / نمایش | Browser tested | Persian/English, RTL/LTR, dark/light, latest browser samples |
| Shift planning / شیفت | Automated + browser | Queue scope, timezone-aware dates, overlap rejection; no automatic PBX changes |
| Directory / دفترچه | Automated + browser | Scoped shared contacts, no click-to-call or CRM sync |
| Audit / ثبت عملیات | Implemented | Accepted/rejected requests; 202 does not establish execution |
| Blind/attended transfer, pickup | Planned | Requires PBX-specific target and bridge validation |
| Park/retrieve controls | Planned | Inventory only in this release |
| Historical reporting / گزارش‌گیری | Next phase | No historical KPI/export acceptance claim |
| AI, STT, WebRTC, tenant isolation | Planned | Separate architecture, deployment and privacy work required |

The monitoring scope was compared against the [VoiPing public feature list](https://voiping.ir/product/ماژول-گزارشات-و-مانیتورینگ-آنلاین-صف/), accessed 2026-10-24. This is an independent implementation. Conference-style supervision refers to barge, not a full conference-room management system.

ChanSpy behavior and mode flags follow the [official Asterisk documentation](https://docs.asterisk.org/Asterisk_20_Documentation/API_Documentation/Dialplan_Applications/ChanSpy/).
