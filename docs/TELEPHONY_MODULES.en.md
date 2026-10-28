# SaneQueue telephone modules

Administrators with the Telephone modules menu grant can configure busy-extension waiting (key 1), internal callback requests (key 2), caller-number normalization and three voice prompt slots.

## Callback and waiting

Only discovered numeric internal destinations are permitted. Wait and request expiry are 30–1800 seconds; dispatch checks are 5–60 seconds. When both phones are idle and reachable, the requester rings first; answering dials the target through the normal internal context. Callback names identify the opposite party on both phones, subject to endpoint display behavior. Pending pairs are deduplicated. An uncertain send is never automatically retried. Pending capacity is 200, with at most one dispatch per interval.

Key 1 waits up to the configured bound before continuing the normal dial path. Key 2 records the request, plays the PBX enabled and thank-you prompts, then ends that request call.

## Bundled and organization audio

The owner-provided Persian menu is included unchanged in [assets/audio](../assets/audio/). The installer verifies SHA-256 and PCM WAV format (mono, 16-bit, 8 kHz, approximately 14.84 seconds) and installs `custom/sanequeue/callback-menu-fa`. Existing `custom/callback.wav` is preserved. Default enabled/thank-you prompts use the PBX's installed core sounds.

Menu, confirmation and wait-timeout slots accept recordings up to 60 seconds / 8 MB. Conversion happens outside call processing, with one conversion, one codec thread, a 20-second deadline and lower Linux CPU priority. Network protocols and playlist demuxers are refused. An uploaded confirmation replaces the entire default confirmation/thank-you sequence, so record both sentences in that file. Up to 30 converted recordings are retained. Organization uploads stay private and survive upgrades.

## Callback evidence report

The bottom of Telephone modules shows the latest 100 requests: request, requester answer, verified target bridge, end and observed talk duration. Persian uses the Persian calendar; English uses Gregorian. This report uses Asia/Tehran.

AMI acceptance is not destination answer. A verified connection requires the requester and the expected target channel in the same observed bridge. Duration requires both connection and requester hangup. Unknown outcomes remain unknown; older rows are not assigned invented timestamps. Reconnection gaps or forwarding can leave the destination unverified. This is an event report, not billing CDR or call recording. Finished request history has no automatic deletion. Pending expiry stops dialing without deleting the request history.

## Caller-number formatting

Preview and live call processing share one typed normalization function. +98, 0098, 98 and mobile/area prefixes can be normalized to the national form. Standard mode preserves internal numbers, anonymous callers and other countries' international numbers. Optional Iranian provider rules additionally handle 0000, 002198, 210, 21098, 098 and legacy short forms; test real trunk samples before enabling. Local area-code expansion is independent. Modified numbers retain `SQ_ORIGINAL_CALLERID` on the channel.

Queue-scoped directory names are applied independently from number formatting. Both web matching and telephone export normalize stored numbers under the same policy. Telephone export refreshes within 30 seconds; web name caching is up to 15 seconds. Names from one queue are not applied to another queue.

## Installation and recovery

A persistent loopback FastAGI service performs bounded lookups; no Python/PHP process is launched per call. Monitoring retains one collector AMI connection. Control sends use a separate restricted, short-lived connection; web requests do not add AMI polling.

This release migrates the supported existing busy-menu and number-formatter adapters. Unknown dialplans are refused, not overwritten. A fresh PBX lacking those adapters requires adapter integration and acceptance; a saved setting alone does not prove that a hook is active. Inbound trunk contexts are not silently changed.

Original files and ownership/modes are backed up privately for root. Structural dialplan changes are deferred while calls are active. External changes are detected before overwrite or restore.

Use `sudo sanequeuectl status`, `disable`, `enable`, or `uninstall --yes`. Disable bypasses added menus and stops module services without hanging up existing PBX calls. Final dialplan removal requires an idle PBX; private configuration/data/backups are retained. Asterisk is not restarted. Pilot each actual server, channel driver and endpoint combination before deployment.
