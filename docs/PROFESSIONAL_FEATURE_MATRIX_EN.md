# SaneQueue 2.1.0-beta.2 — live-operations feature inventory

**Development test build, not production-ready.** Reference products: [FOP2](https://www.fop2.com/), [VoiPing online queue monitor](https://voiping.ir/product/ماژول-گزارشات-و-مانیتورینگ-آنلاین-صف/), [QueueMetrics](https://www.queuemetrics.com/), [OpDesk](https://github.com/Ibrahimgamal99/OpDesk), and [VICIdial](https://www.vicidial.com/features/).

| Capability | Current status | Notes |
|---|---|---|
| Live queue monitoring, waiting callers, member state, queue service counters | Prototype | Asterisk 20 QueueStatus adapter for test queue 8001; owner live validation pending |
| Live calls, active agent capacity, agent filters, wait timers | Prototype | Call-channel details disabled until independently validated |
| Dark responsive Persian RTL / English operations dashboard | Prototype | Local preview and JavaScript validated; further UX work pending |
| Wallboard, waiting-time, congestion and pause alerts | Prototype | Threshold rules and basic sound, not enterprise alerting |
| Queue pause/resume with reason | Staged control | QueuePause; only temporary test gate |
| Queue membership, agent penalty | Staged control | Dynamic member operations; static members remain Issabel-managed |
| Queue priority/move to front, waiting caller hangup | Staged control | Current queue membership must be verified by backend |
| Listen/Whisper/Barge | Staged control | Originate/ChanSpy to a specific test supervisor on consenting test calls |
| Scoped access and audit | Prototype | Local demo automatically logs in as admin; not multi-user production authentication |
| All-extension Presence/DND/registration, trunks | Not implemented | Requires dedicated endpoint/trunk adapters |
| Blind/attended transfer, Park/Pickup, conferences | Not implemented | No fake controls displayed for unsupported actions |
| CRM, phonebook, Caller ID normalization | Not implemented | Integration stage |
| WebRTC phone, recording controls, mobile push | Not implemented | Additional services and privacy/security review required |
| AI live suggestions / STT / speech analysis | Not implemented | Planned, strictly advisory with human approval |
| Multi-PBX, tenant isolation, production role security and performance testing | Not implemented | Required before commercial deployment |
| Historical reports and Excel | Deferred by owner | Intentionally excluded from current phase |

The vendor feature inventory is a benchmark only. SaneQueue source does not include copied proprietary vendor components.
