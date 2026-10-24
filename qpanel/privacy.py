"""Default-deny customer data exposure for SaneQueue read APIs.

This is a separate security boundary from visual masking in the browser.
"""
import copy
import re


def mask_phone(value):
    if value is None:
        return ''
    raw = str(value)
    digits = re.sub(r'\D', '', raw)
    return ('••••' + digits[-2:]) if digits else ('[hidden]' if raw else '')


def public_queue_snapshot(queues, *, privileged=False, reveal_numbers=False):
    """Return a deep copy. Nobody gets raw caller ID by default.

    Privileged roles retain opaque call channel IDs for scoped operations;
    viewers receive neither IDs nor raw phone numbers.
    """
    data = copy.deepcopy(queues)
    for queue in data.values():
        entries = queue.get('entries', {})
        # Viewer entries must not retain raw channel IDs as mapping KEYS.
        # Generate request-local non-identifying IDs; do not publish internal
        # channel names, Uniqueid or Linkedid even in nested object keys.
        if isinstance(entries, dict) and not privileged:
            queue['entries'] = {'entry_%d' % (i + 1): item for i, item in enumerate(entries.values())}
            entries = queue['entries']
        for item in entries.values():
            for key in list(item):
                field = key.lower()
                if 'callerid' in field or 'connectedline' in field:
                    item[key] = (item[key] if reveal_numbers else ('[hidden]' if 'name' in field else mask_phone(item[key])))
            if not privileged:
                item.pop('Channel', None)
                item.pop('Uniqueid', None)
                item.pop('Linkedid', None)
                item.pop('ActionID', None)
        for item in queue.get('members', {}).values():
            if 'LiveCaller' in item and not reveal_numbers:
                item['LiveCaller'] = mask_phone(item['LiveCaller'])
            if not privileged:
                item.pop('LiveChannel', None)
    return data
