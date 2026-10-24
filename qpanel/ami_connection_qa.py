"""Multi-stage Asterisk QueueStatus diagnostic. No mutating AMI Actions.

Pure classification helpers are unit-testable without Flask, py-Asterisk or network.
"""
import socket

STAGE = ('target', 'tcp', 'login', 'queue_status', 'live_parser', 'visibility')

def classify_error(exc, stage):
    if isinstance(exc, ValueError):
        return 'invalid_ami_target' if stage == 'target' else 'no_visible_queues_match' if stage == 'visibility' else 'invalid_settings'
    if isinstance(exc, (socket.timeout, TimeoutError)):
        return 'ami_timeout'
    if isinstance(exc, ConnectionRefusedError):
        return 'tcp_connection_refused'
    if isinstance(exc, PermissionError):
        return 'ami_authentication_rejected' if stage == 'login' else 'queue_status_permission_denied'
    if isinstance(exc, EOFError):
        return 'ami_connection_closed'
    if isinstance(exc, OSError):
        return 'ami_network_unreachable'
    if stage == 'visibility':
        return 'no_visible_queues_match'
    return 'ami_unexpected_response'

def safe_stage(stage, ok, code=None):
    return {'stage':stage, 'ok':bool(ok), **({'code':code} if code else {})}
