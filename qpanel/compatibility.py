"""Driver-aware targets; never guess that an Issabel hint means PJSIP."""
import re


def spy_target(member, agent, channels=(), overrides=None):
    state = str(member.get('StateInterface') or agent)
    if state.startswith('hint:'):
        match = re.fullmatch(r'hint:([A-Za-z0-9_.-]{1,48})@[A-Za-z0-9_.-]{1,80}', state)
        if not match:
            raise ValueError('unsupported_state_interface')
        extension = match.group(1)
        configured = (overrides or {}).get(extension)
        if configured:
            state = configured
        else:
            found = {str(row.get('Channel', '')) for row in channels
                     if re.match(r'^(SIP|PJSIP)/' + re.escape(extension) + r'-[A-Za-z0-9]+$', str(row.get('Channel', '')))}
            if len(found) != 1:
                raise ValueError('ambiguous_or_missing_device_channel')
            state = found.pop()
    state = re.sub(r'/n$', '', state)
    if not re.fullmatch(r'(SIP|PJSIP|Local)/[A-Za-z0-9_.@/+;-]{1,120}', state):
        raise ValueError('unsupported_state_interface')
    return state


def device_channel(member, agent, channels, overrides=None):
    """Resolve exactly one observed leg; never supervise an ambiguous prefix."""
    target = spy_target(member, agent, channels, overrides)
    found = {str(row.get('Channel','')) for row in channels
             if row.get('Channel') == target or str(row.get('Channel','')).startswith(target+'-')}
    if len(found) != 1:
        raise ValueError('ambiguous_or_missing_device_channel')
    return found.pop()
