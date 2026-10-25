# SaneQueue user guide

This manual and in-panel help share one source. Screenshots illustrate the interface; your live values will differ.

![In-panel help](images/help-en-dark-beta22.png)

## Sections

- [Overview](#live)
- [Queues](#queues)
- [Active calls](#calls)
- [Waiting calls](#waiting)
- [Agents](#agents)
- [Presence](#presence)
- [PBX and trunk health](#pbx)
- [Supervisor call control](#control)
- [Wallboard](#wallboard)
- [Alerts](#alerts)
- [Audit trail](#audit)
- [Settings and messaging](#settings)
- [Users and permissions](#users)
- [Queue policies](#policies)
- [Shift planning](#shifts)
- [Contact directory](#directory)
- [Capabilities and limits](#features)

<a id="live"></a>

## Overview

A quick view of queue pressure and staffing. Counters start at the last Asterisk queue reset.

1. Filter the queue or agent at the top.
2. Compare waiting callers and longest wait with agent availability.
3. Trend charts use samples collected by this browser only.

> A stale-data warning means the live state cannot be trusted; wait for reconnection before controlling calls.

<a id="queues"></a>

## Queues

Each card combines queue metrics, members and queue-specific alerts.

1. Open queue details for metrics and their definitions.
2. SLA is the percentage answered within the Asterisk service-level target.
3. Average wait and talk refer to answered calls.

<a id="calls"></a>

## Active calls

Follow conversations by agent, queue and talk duration.

1. Select a queue and check data freshness.
2. Select the current agent or active call before acting.
3. Blind transfer rings the destination; attended transfer permits consultation first.

> One call can contain multiple channel legs. IVR entry/selection is observed only in ivr-* menus after collector connection; in-call DTMF is not stored. Queue-leg hangup party requires explicit evidence; after transfer or without evidence it remains unknown.

<a id="waiting"></a>

## Waiting calls

Waiting callers are listed with queue position and elapsed wait.

1. Full caller numbers require a separate caller-details permission.
2. Priority changes queue ordering; it does not add answering capacity.
3. Review the selected caller before hanging up.

<a id="agents"></a>

## Agents

State and observed daily activity are tracked separately for each queue membership.

1. Open My profile & status to change your own membership; select a reason card when pausing.
2. A supervisor with membership permission can add a discovered extension or remove a dynamic member.
3. Open Daily activity & pause reasons to select a date and inspect on-duty, paused-by-reason and removed intervals.

> Concurrent memberships are not summed as work hours. History starts when observation recording is enabled; collector gaps are not credited. Pause static members for temporary departures.

<a id="presence"></a>

## Presence

Inspect telephony states and memberships within your authorized queues.

1. An extension can belong to several queues.
2. A pause in one queue does not necessarily pause every membership.
3. Wrap-up is after-call preparation time, not an offline state.

<a id="pbx"></a>

## PBX and trunk health

Inspect extensions, trunks and AMI capabilities without changing the PBX.

1. Extensions and trunks are separate even when a trunk name is numeric.
2. The local adapter refreshes inventory every 30 seconds.
3. Unavailable differs from Unknown: Unknown means insufficient observations.

> RTT and loss need valid RTCP. Missing data does not imply good quality. Jitter requires the codec clock rate before conversion to milliseconds.

<a id="control"></a>

## Supervisor call control

Call control requires an assigned supervisor phone, queue grants and a current call.

1. Listen: the supervisor hears the conversation silently.
2. Whisper should be audible only to the agent; barge joins all participants.
3. Park holds a call in a slot; retrieve connects it to the supervisor phone.
4. Pickup is for a ringing call, not an answered conversation.

> AMI acceptance does not verify audio quality. Do not blindly repeat a command whose outcome is unknown.

![Supervisor controls](images/control-en-beta21.png)

<a id="wallboard"></a>

## Wallboard

A supervisor display whose status summary remains inside the fullscreen stage.

1. Choose queues and enter fullscreen; use Exit or Escape to leave.
2. Compare totals, ready/talking/ringing/paused agents, queue identity, waiting callers and timers.
3. Enable private mode only when caller-details permission is available; public displays hide numbers.
4. More than 12 waiting callers rotate in pages every 15 seconds.

> Stable colors identify queues; red plus a warning symbol identifies a queue-rule breach. Connection loss is shown separately.

![Wallboard](images/wallboard-load-beta22.png)

<a id="alerts"></a>

## Alerts

Review current threshold alerts and notification delivery status.

1. Configure thresholds in queue policies.
2. Browser audio needs a user gesture to enable sound.
3. Delivery counts mean provider API acceptance; verify the destination conversation too.
4. The toolbar wait highlight is a personal display setting. In persistent mode, queue alarms and their sound follow server-side queue rules.

<a id="audit"></a>

## Audit trail

A supervisor action trail, separate from historical call performance reporting.

1. Review actor, queue, action and result together.
2. Pending commands have no final observed outcome yet.
3. For an unknown result, inspect the current call before retrying.

<a id="settings"></a>

## Settings and messaging

Manage connection diagnostics and alert messaging here.

1. Managed installation provisions the collector on the server.
2. Start your Telegram or Bale bot from the destination account.
3. Save the token and numeric chat ID, then send a test notification.
4. Enable each queue in queue policies for actual alerts.
5. Save your organization name, subtitle and logo; the sign-in page uses the same identity.
6. Disable monitoring to stop this module’s AMI reception and call controls while PBX calls continue.
7. Panel unavailable: sudo sanequeuectl disable. Restore: sudo sanequeuectl enable. Remove services while retaining data: sudo sanequeuectl uninstall --yes.

> A blank token keeps the previous secret. Do not include tokens in screenshots, tickets or public repositories.

![Settings and messaging](images/organization-fa-beta22.png)

<a id="users"></a>

## Users and permissions

Access has three layers: role, panel sections, and queue/action grants.

1. Admin manages users/settings; supervisors control granted queues; agents pause/resume themselves; viewers are read-only.
2. Choose the actual extension; one phone cannot belong to two accounts.
3. Select sections, queues and actions, then save once.
4. A new password is optional when editing and must contain at least 12 characters.

![Users and permissions](images/users-beta22.png)

<a id="policies"></a>

## Queue policies

Configure alerts, staffing limits, pause reasons and outbound directory dialing independently per queue.

1. Choose a queue from live inventory; the form applies only to that queue.
2. Enable count and wait-time conditions independently; combine them with OR or AND when needed.
3. The low-ready threshold operates independently of count/time matching.
4. Staffing limits are optional. Enable them and define a fixed roster before enforcing departure limits.
5. Add a pause-reason label; its technical identifier is generated automatically.
6. Select Telegram and Bale delivery for each queue; configure bot connections under Settings.

> Saving alert rules does not enable staffing restrictions. External directory dialing is off by default and requires a user Dial grant and a PBX outbound route.

<a id="shifts"></a>

## Shift planning

Plan team presence; saving a shift does not automatically change phone state.

1. Choose queue, agent, start and end time.
2. Review overlaps before saving.
3. Use agent and queue controls to change actual pause or membership.

<a id="directory"></a>

## Contact directory

A shared per-queue directory identifies waiting callers and supports permissioned callback dialing.

1. Save the contact with a queue, name and phone; match the incoming Caller ID number format.
2. A matching caller in that queue displays the saved name; name updates may take up to 15 seconds.
3. Call requires a Dial grant and your assigned phone. Your phone rings first; answer it to dial the contact.
4. Internal destinations are allowed by default; an administrator can authorize outbound saved contacts per queue.

> Saving a contact never starts a call. Names remain within the authorized queue. This directory is not a full CRM.

<a id="features"></a>

## Capabilities and limits

Actual feature availability and implementation limits.

1. Available means implemented; your environment must still meet prerequisites.
2. Beta features need acceptance testing on your PBX.
3. Planned means the feature is not available yet.

## Profile and password

Use My profile & status to manage first/last name, assigned phone and picture, change your queue status, and view daily activity. Personal history is clipped to the current phone assignment. Click-to-call rings your own phone first and requires a queue Dial grant. Password or phone changes require the current password and revoke existing account sessions. PNG/JPEG/WebP images up to 512 KB and 4 megapixels are decoded, resized and stripped of metadata.

![Profile](images/profile-en-beta22.png)

## Messaging references

- [Telegram Bot API](https://core.telegram.org/bots/api#sendmessage)
- [Bale Bot API](https://docs.bale.ai/)
