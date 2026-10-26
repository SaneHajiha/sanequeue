# Temporary inbound status notices

A notice plays at an explicitly approved inbound point and then returns to the original route. It is separate from paging, outbound emergency calls and queue rerouting.

Current status: versioned administrator API/UI, bounded audio conversion, validity checks and an optional PBX subroutine are implemented. The inbound hook has **not** passed live acceptance. Saving a setting neither installs a route nor proves playback. Per-playback reporting events are not implemented yet.

Administrators use Telephony → Telephone module settings → Inbound status & incident notice. Select an approved binding, title, audio and validity dates. Input files are limited to 8 MB and converted audio to 60 seconds; validity is at most seven days. Input times use the browser timezone; the table displays Asia/Tehran. Concurrent edits require reloading the current revision. Disabling or expiry prevents subsequent selection; it does not interrupt an existing playback or delete history.

The technical operator supplies a root-owned, non-group/world-writable `/etc/sanequeue/incident-bindings.json`, for example:

```json
{"support":{"context":"from-test","queue":"8001","label":"Support"}}
```

This registry does not create an inbound route. A reviewed hook in the matching context and queue may call:

```asterisk
Gosub(sanequeue-inbound-notice,s,1(support,from-test,8001))
```

Place it after the route's existing Answer, or in a separately validated early-media path. `Playback(...,noanswer)` does not answer a call. No automatic trunk, DID or generated-route rewriting is performed. Snapshot/audio publication uses the existing restricted adapter, with its idle and managed-file hash checks. Only verified content-addressed WAV/8 kHz/mono/16-bit audio is published.

Acceptance must cover actual playback and continuation, missing/invalid audio, wrong binding/context/queue, expiry, module disable, FastAGI unavailability, permission revocation and invalid CSRF. Measure call-path delay during failure: the service session timeout is three seconds, while operating-system stalls still require actual testing. Unknown routes must remain unchanged. Deploy a production hook only after acceptance on that server's dialplan/version.
