"""Explicitly scoped, short-lived authorization gate for Asterisk TEST PBX actions.

This is a secondary allowlist, not a replacement for AMI permission limits.
"""
from dataclasses import dataclass, field
import re
import time

ALLOWED_ACTIONS = frozenset({'pause_member','priority','first','hangup','spy','whisper','barge','add','remove','penalty','transfer','attended_transfer','cancel_transfer','park','retrieve','pickup','dial','hangup_active'})

@dataclass
class TestControlGate:
    __test__ = False  # Runtime authorization object, not a pytest test class.
    queue: str = '8001'
    agents: frozenset = frozenset({'Local/100@from-queue/n', 'PJSIP/100'})
    supervisor: str = ''  # chosen from the authenticated account, not a shared default
    ttl_seconds: int = 1800
    expires_at: float = 0.0
    enabled: bool = False
    owner_user: str = ''
    owner_session: str = ''
    allowed_actions: frozenset = field(default_factory=frozenset)

    def arm(self, phrase: str, live: bool, password_ready: bool,
            *, queue=None, agents=None, owner_user=None, owner_session=None,
            allowed_actions=None) -> bool:
        requested = str(queue or self.queue)
        if not owner_user or not owner_session:
            return False
        if not re.fullmatch(r'[a-zA-Z0-9_-]{1,128}', str(owner_user)):
            return False
        if not re.fullmatch(r'[0-9a-f]{32}', str(owner_session)):
            return False
        actions = frozenset(str(a) for a in (allowed_actions or ()))
        if not actions or not actions.issubset(ALLOWED_ACTIONS):
            return False
        # The user explicitly chooses ONE live queue for this short-lived grant.
        # Never interpret * as a write-scope and never infer a write-scope from
        # the read-only "all queues" selection.
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,32}', requested):
            return False
        if phrase != 'ENABLE ' + requested or not live or not password_ready:
            return False
        if agents is not None:
            clean = frozenset(str(a) for a in agents if a and '\r' not in str(a) and '\n' not in str(a))
            if not clean or len(clean) > 100:
                return False
            self.agents = clean
        self.queue = requested
        self.owner_user = str(owner_user)
        self.owner_session = str(owner_session)
        self.allowed_actions = actions
        self.enabled = True
        self.expires_at = time.monotonic() + self.ttl_seconds
        return True

    def disarm(self) -> None:
        self.enabled = False
        self.expires_at = 0.0
        self.owner_user = ''
        self.owner_session = ''
        self.allowed_actions = frozenset()

    def active(self, *, owner_user=None, owner_session=None) -> bool:
        if self.enabled and time.monotonic() >= self.expires_at:
            self.disarm()
        return (self.enabled and bool(owner_user) and bool(owner_session)
                and self.owner_user == owner_user and self.owner_session == owner_session)

    def remaining_seconds(self, *, owner_user=None, owner_session=None) -> int:
        return max(0, int(self.expires_at - time.monotonic())) if self.active(owner_user=owner_user, owner_session=owner_session) else 0

    def authorize(self, endpoint: str, args: dict, live: bool, password_ready: bool,
                  *, owner_user=None, owner_session=None) -> bool:
        if not self.active(owner_user=owner_user, owner_session=owner_session) or not live or not password_ready:
            return False
        if args.get('queue') != self.queue:
            return False
        if endpoint == 'pause_member':
            return 'pause_member' in self.allowed_actions and args.get('agent') in self.agents and args.get('paused') in ('true','false')
        if endpoint != 'ops_control':
            return False
        action = args.get('action', '')
        if action not in self.allowed_actions:
            return False
        if action=='dial':return bool(args.get('extension'))
        if action in ('priority', 'first', 'hangup','transfer','attended_transfer','cancel_transfer','park','retrieve','pickup','hangup_active'):
            # Application independently checks channel is *currently* in this queue.
            return bool(args.get('channel'))
        if args.get('agent') not in self.agents:
            return False
        if action in ('spy', 'whisper', 'barge'):
            # operations.py independently resolves and verifies caller's own phone.
            return not args.get('destination')
        return True
