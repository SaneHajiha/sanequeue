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

> One call can contain multiple SIP/PJSIP/Local channel legs; channel counts are not conversation counts.

<a id="waiting"></a>

## Waiting calls

Waiting callers are listed with queue position and elapsed wait.

1. Full caller numbers require a separate caller-details permission.
2. Priority changes queue ordering; it does not add answering capacity.
3. Review the selected caller before hanging up.

<a id="agents"></a>

## Agents

Ready, ringing, talking, paused and wrap-up states are distinct.

1. Choose a pause reason before pausing.
2. Resume when ready to receive calls again.
3. Agents can change only their own status; supervisors need queue and action grants.

> A Local interface is a queue membership path, not necessarily the actual SIP/PJSIP device.

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

A large-screen view for supervisors and managers.

1. Choose queues and enter fullscreen.
2. Press Escape to exit fullscreen.
3. Public display masks caller numbers; private supervisor detail requires permission and explicit selection.

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

Each queue has its own independent rules.

1. Example: set a waiting-count threshold of 5 for a crowded queue.
2. Enter 300 seconds for a five-minute wait threshold.
3. Select Telegram and Bale independently; cooldown limits repeated active alerts.
4. Agent departure limits depend on configured roster and minimum on-duty staff.

<a id="shifts"></a>

## Shift planning

Plan team presence; saving a shift does not automatically change phone state.

1. Choose queue, agent, start and end time.
2. Review overlaps before saving.
3. Use agent and queue controls to change actual pause or membership.

<a id="directory"></a>

## Contact directory

A shared directory scoped to authorized queues, storing contact names, numbers and work notes.

1. Assign the contact to a queue so its access scope applies.
2. Record a name and number for lookup and recognition.
3. The directory does not automatically place calls and is not a full CRM or CDR system.

<a id="features"></a>

## Capabilities and limits

Actual feature availability and implementation limits.

1. Available means implemented; your environment must still meet prerequisites.
2. Beta features need acceptance testing on your PBX.
3. Planned means the feature is not available yet.

## Profile and password

Use the top-bar avatar button to manage your display name, assigned phone and picture. Password or phone changes require the current password and revoke existing account sessions. PNG/JPEG/WebP images up to 512 KB and 4 megapixels are decoded, resized and stripped of metadata.

![Profile](images/profile-en-beta22.png)

## Messaging references

- [Telegram Bot API](https://core.telegram.org/bots/api#sendmessage)
- [Bale Bot API](https://docs.bale.ai/)
