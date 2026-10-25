# Compatibility and resource limits · beta.23

| Platform | Evidence | Remaining acceptance |
|---|---|---|
| Rocky Linux 8.10 / Asterisk 20.12.0 / Python 3.11 | Automatic install, queue/control calls, messages, RTCP, bounded Local load | Real SIP/RTP concurrency and long-duration soak |
| Asterisk 16 / 18 | AMI event/parser fixtures | Actual versions, modules, privileges and telephone controls |
| Issabel 4 / 5 | Standard generated SIP/PJSIP definitions supported by the local adapter | Actual OS/package repositories, Python bootstrap, ACL/menu integration and full host acceptance |
| PJSIP / Local queue members | Actual three registered phones/two queues and supervision/transfer/parking/pickup | Site-specific contexts and endpoint naming |
| chan_sip | Actual trunk inventory plus parser fixtures | Actual SIP-agent audio and control acceptance |
| Python 3.10–3.12 | CI matrix and isolated-runtime design | OS/runtime availability on each target |
| Docker / remote PBX | Supplied advanced configuration | Image/network/volume and privileged inventory adapter validation |

Standard local discovery defaults to internal endpoint context `from-internal`. Customized contexts are supported by the root-owned `/etc/sanequeue/inventory.ini` exact allowlist (`[inventory] internal_contexts=from-internal,internal-sales`, up to 32 names, no wildcard); the installer preserves existing configuration. Never classify trunk contexts as internal. Unsupported/unavailable values remain unknown. No driver migration or endpoint/dialplan change is performed. Issabel's native ACL/Smarty integration is not claimed; this is an independently authenticated web application.

## Monitoring cost

The standard installer uses one long-lived read/reporting AMI collector, bounded in-memory state, Redis snapshots and authenticated scoped WebSockets. Normal HTTP/browser refreshes do not connect to AMI. QueueStatus reconciliation is periodic (120 seconds), independent of browser count. Controls use a separate restricted identity and fresh cached state with action confirmation. The optional local phone/trunk inventory runs a bounded root task every 30 seconds; the web process never executes CLI commands. Legacy five-second AMI snapshots are a separate rollback path, not the standard managed deployment.

A staged laboratory test reached 100 simultaneous Local queue callers. Total six-vCPU utilization was 22.09%, Asterisk RSS 146.91 MB, web RSS 81.58 MB and collector RSS 40.60 MB; 100 HTTP requests at concurrency 20 had p95 1.5660 seconds and zero HTTP errors. Additional web AMI collections: zero. All generated call legs were removed. [Full evidence and limits](AUDIT_BETA23.md).

Local calls do not emulate SIP registration, transcoding, RTP transport, recording or concurrent ChanSpy. These measurements cannot establish production capacity or absence of audio impact at 100 real calls. Test representative codecs, trunks, recording and supervision on the target PBX before production. One worker is required for the current local account/policy/cache design; multiple tenants and high availability are not implemented.

RTCP is observed metadata, not an audio processing path. RTT is converted from Asterisk seconds to milliseconds; loss from fraction/256 to percent. Jitter remains RTP timestamp ticks without a verified codec clock rate; MOS is not fabricated. SIP qualify RTT is signaling reachability, not RTP latency.

فارسی: این جدول مرز آزمون واقعی و پشتیبانی طراحی‌شده را روشن می‌کند. تست ۱۰۰ تماس Local جای تست ۱۰۰ تماس صوتی واقعی را نمی‌گیرد. ایزابل ۴/۵ و Asterisk ۱۶/۱۸ هنوز به نصب و پذیرش روی همان نسخه نیاز دارند.
