"""Validate explicit AMI targets without allowing Internet/metadata SSRF.

The server is only bound to loopback for local testing. Plaintext AMI on
remote private hosts requires a restricted LAN and is NOT recommended;
prefer forwarding through SSH to the PBX loopback interface.
"""
import ipaddress
import re

_QUEUE = re.compile(r'^[A-Za-z0-9_-]{1,32}$')
_RFC1918 = tuple(ipaddress.ip_network(v) for v in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16'))


def validate_target(host, port, queue):
    host = str(host or '').strip()
    if host == 'localhost': host = '127.0.0.1'
    try: ip = ipaddress.ip_address(host)
    except ValueError as exc: raise ValueError('AMI host must be a private IPv4 address') from exc
    if ip.version != 4 or not (ip == ipaddress.ip_address('127.0.0.1') or any(ip in net for net in _RFC1918)):
        raise ValueError('Only local and RFC1918 LAN IPv4 targets are supported')
    try: port = int(port)
    except (ValueError, TypeError) as exc: raise ValueError('Invalid AMI port') from exc
    if not 1 <= port <= 65535: raise ValueError('Invalid AMI port')
    queue = str(queue or '').strip()
    if queue != '*' and not _QUEUE.fullmatch(queue): raise ValueError('Invalid queue identifier')
    return host, port, queue
