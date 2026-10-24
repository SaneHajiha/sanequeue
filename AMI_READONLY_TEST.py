#!/usr/bin/env python3
"""Safe AMI queue snapshot for SaneQueue. Read-only QueueStatus, no raw caller data output.

Usage: python AMI_READONLY_TEST.py --host 127.0.0.1 --port 15038 --user sq_readonly --queue 8001
Secret is collected via getpass on your computer, never saved or printed.
"""
import argparse
import getpass
import json
import os
from pathlib import Path
from datetime import datetime, timezone
import socket
import sys
import time
from collections import Counter

MAX_BUFFER = 2_000_000

def wire(fields):
    if any(('\\r' in str(v) or '\\n' in str(v) or '\r' in str(v) or '\n' in str(v)) for v in fields.values()):
        raise ValueError('Invalid newline in AMI field')
    return ''.join(f'{k}: {v}\r\n' for k, v in fields.items()).encode('utf-8') + b'\r\n'

class ReadOnlyAMI:
    def __init__(self, host, port, timeout=8):
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.sock.settimeout(timeout)
        self.buffer = b''
        self.max_read = MAX_BUFFER
        self.deadline = time.monotonic() + timeout
        try:
            self.greeting = self._readline()
            if not self.greeting.startswith('Asterisk Call Manager'):
                raise RuntimeError('Target is not an Asterisk Manager endpoint')
        except Exception:
            self.sock.close()
            raise
        self.deadline = None

    def _recv(self):
        if self.deadline is not None:
            remaining = self.deadline - time.monotonic()
            if remaining <= 0: raise TimeoutError('AMI absolute deadline exceeded')
            self.sock.settimeout(min(8, remaining))
        chunk = self.sock.recv(8192)
        if not chunk:
            raise EOFError('AMI connection closed')
        self.buffer += chunk
        if len(self.buffer) > self.max_read:
            raise RuntimeError('AMI response too large')

    def _readline(self):
        while b'\r\n' not in self.buffer:
            self._recv()
        raw, self.buffer = self.buffer.split(b'\r\n',1)
        return raw.decode('utf-8','replace')

    def read_packet(self):
        while b'\r\n\r\n' not in self.buffer:
            self._recv()
        raw, self.buffer = self.buffer.split(b'\r\n\r\n', 1)
        lines = raw.decode('utf-8','replace').split('\r\n')
        event = {}
        for line in lines:
            if ': ' in line:
                k, v = line.split(': ',1)
                event[k] = v
        return event

    def send(self, **fields):
        self.sock.sendall(wire(fields))

    def login(self, user, secret, events='off'):
        self.send(Action='Login', Username=user, Secret=secret, Events=events, ActionID='sq-login')
        until=time.monotonic()+8
        while time.monotonic()<until:
            packet=self.read_packet()
            if packet.get('ActionID')=='sq-login' or 'Response' in packet:
                if packet.get('Response')=='Success': return True
                raise PermissionError('AMI authentication rejected')
        raise TimeoutError('Login timed out')

    def queue_snapshot(self, name='8001', timeout=10):
        self.sock.settimeout(timeout)
        request={'Action':'QueueStatus','ActionID':'sq-queue-read'}
        if name != '*': request['Queue']=name
        self.send(**request)
        counts=Counter(); members=Counter(); queues=set(); waiting_by_queue={}; entries_by_queue=Counter(); complete=False
        end=time.monotonic()+timeout
        while time.monotonic()<end:
            try: packet=self.read_packet()
            except socket.timeout: break
            # ActionID present for QueueStatus list events in Asterisk 20
            if packet.get('ActionID') not in ('sq-queue-read', None): continue
            if packet.get('Response')=='Error':
                raise PermissionError('QueueStatus failed: '+ packet.get('Message','AMI denied'))
            if packet.get('Event')=='QueueParams':
                counts['queue_events']+=1
                queues.add(packet.get('Queue',name))
                try: waiting_by_queue[packet.get('Queue', name)]=int(packet.get('Calls','0'))
                except (ValueError,TypeError): waiting_by_queue[packet.get('Queue', name)]=0
            elif packet.get('Event')=='QueueMember':
                counts['queue_members']+=1
                status=packet.get('Status','unknown')
                members['status_'+status]+=1
                if packet.get('Paused')=='1': members['paused']+=1
            elif packet.get('Event')=='QueueEntry':
                counts['waiting_entries']+=1
                entries_by_queue[packet.get('Queue',name)]+=1
            elif packet.get('Event')=='QueueStatusComplete':
                complete=True; break
        return {'connected':True,'queue_requested':name,
                'queue_count':len(queues),'members':counts['queue_members'],
                'member_states':dict(members),'waiting_calls':sum(max(waiting_by_queue.get(q,0),entries_by_queue.get(q,0)) for q in queues),
                'snapshot_complete':complete,'caller_data':'never exported'}

    def close(self):
        try: self.send(Action='Logoff',ActionID='sq-logout')
        except Exception: pass
        self.sock.close()

def main():
    ap=argparse.ArgumentParser(description='SaneQueue Asterisk AMI safe queue diagnostics')
    ap.add_argument('--host',default='127.0.0.1',help='SSH tunnel endpoint (prefer loopback)')
    ap.add_argument('--port',type=int,default=15038)
    ap.add_argument('--user',default='sq_readonly')
    ap.add_argument('--queue',default='8001')
    ap.add_argument('--save-snapshot',action='store_true',help='Save sanitized counters for local browser viewing (no credentials)')
    args=ap.parse_args()
    if not (1<=args.port<=65535):ap.error('Invalid port')
    if args.queue != '*' and not args.queue.replace('_','').replace('-','').isalnum():ap.error('Queue must be alphanumeric or *')
    print('SaneQueue AMI test: read-only queue snapshot; no changes to Asterisk.')
    secret=getpass.getpass('Temporary AMI password (hidden; stays on your device): ')
    c=None
    try:
        c=ReadOnlyAMI(args.host,args.port)
        c.login(args.user,secret)
        report=c.queue_snapshot(args.queue)
        print(json.dumps(report,ensure_ascii=False,indent=2))
        if args.save_snapshot and report['snapshot_complete']:
            snapshot={'checked_at_utc':datetime.now(timezone.utc).isoformat(), **report}
            target=Path(__file__).resolve().parent/'ami_snapshot.json'
            target.write_text(json.dumps(snapshot,ensure_ascii=False,indent=2),encoding='utf-8')
            try: os.chmod(target,0o600)
            except OSError: pass
            print('Sanitized local snapshot saved for http://127.0.0.1:18877/__sanequeue__/ami-snapshot')
        if not report['snapshot_complete']:
            print('WARNING: snapshot incomplete; check AMI permissions or connection.',file=sys.stderr)
            return 2
        return 0
    except (OSError,RuntimeError,EOFError,PermissionError,TimeoutError) as e:
        print('Connection/test error:',e,file=sys.stderr)
        return 1
    finally:
        if c is not None: c.close()

if __name__=='__main__':raise SystemExit(main())
