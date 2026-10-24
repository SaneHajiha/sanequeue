"""SaneQueue queue filters; !default monitors any Asterisk queue but hides the dummy default.

AMI QueueStatus returns all Asterisk queues, including queues not present in
Issabel's GUI. AMI does not identify configuration provenance. Use !default to hide the system default, or an explicit allowlist. Never delete PBX queues.
"""
import re

_ALLOWED = re.compile(r'^[A-Za-z0-9_-]{1,32}$')
MAX_QUEUES = 100


def parse_visible_queues(raw):
    """Return selected queue names, or None for explicit raw Asterisk-all mode."""
    text = str(raw or '').strip()
    if text in ('*', '!default'):
        return None if text == '*' else ('!default',)
    names = [part.strip() for part in re.split(r'[,;،؛\s]+', text) if part.strip()]
    if not names or len(names) > MAX_QUEUES or any(not _ALLOWED.fullmatch(name) for name in names):
        raise ValueError('visible_queues must be 1-100 IDs, !default or * for all Asterisk queues')
    return tuple(dict.fromkeys(names))


def normalize_visible_queues(raw):
    names = parse_visible_queues(raw)
    return '*' if names is None else ','.join(names)


def filter_queue_data(queues, visible):
    """Filter Asterisk QueueStatus data to Issabel-managed IDs only."""
    allowed = parse_visible_queues(visible)
    if allowed is None:
        return dict(queues)
    if allowed == ('!default',):
        return {name: data for name,data in queues.items() if name.lower() != 'default'}
    names = set(allowed)
    return {name: data for name, data in queues.items() if name in names}


def is_queue_visible(queue_name, visible):
    allowed = parse_visible_queues(visible)
    return allowed is None or (allowed == ('!default',) and queue_name.lower() != 'default') or queue_name in allowed
