"""Offline Asterisk 20 AMI parser and socket tests. No real credentials or PBX."""
import socketserver
import threading
import unittest
from unittest.mock import patch
from qpanel.ami_live import parse_queue_events, read_queue_data

QUEUE_EVENTS = [
    {'Event': 'QueueParams', 'Queue': '8001', 'Strategy': 'ringall', 'Calls': '2', 'Completed': '12', 'Abandoned': '1', 'Holdtime': '17', 'ServicelevelPerf': '92.5'},
    {'Event': 'QueueMember', 'Queue': '8001', 'Name': 'test', 'Location': 'Local/100@from-queue/n', 'StateInterface': 'hint:100@ext-local', 'Status': '1', 'Paused': '0', 'CallsTaken': '10', 'LastCall': '0'},
    {'Event': 'QueueEntry', 'Queue': '8001', 'Channel': 'PJSIP/test-100', 'CallerIDNum': '02100000001', 'Position': '1', 'Wait': '42', 'Priority': '0'},
    {'Event': 'QueueEntry', 'Queue': '8001', 'Channel': 'PJSIP/test-101', 'CallerIDNum': '02100000002', 'Position': '2', 'Wait': '13', 'Priority': '0'},
]

class Handler(socketserver.BaseRequestHandler):
    def handle(self):
        self.request.sendall(b'Asterisk Call Manager/5.0.1\r\n')
        buffer=b''
        while True:
            chunk=self.request.recv(4096)
            if not chunk: break
            buffer+=chunk
            while b'\r\n\r\n' in buffer:
                raw,buffer=buffer.split(b'\r\n\r\n',1)
                kv=dict(line.split(b': ',1) for line in raw.split(b'\r\n') if b': ' in line)
                action=kv.get(b'Action',b'').decode()
                self.server.calls.append(action)
                if action=='Login':
                    self.request.sendall(b'Response: Success\r\nActionID: sq-login\r\nMessage: Authentication accepted\r\n\r\n')
                elif action=='QueueStatus':
                    self.request.sendall(b'Response: Success\r\nActionID: sq-live-queue\r\nMessage: Queue status follows\r\n\r\n')
                    for e in QUEUE_EVENTS:
                        b=('\r\n'.join(f'{k}: {v}' for k,v in e.items())+'\r\nActionID: sq-live-queue\r\n\r\n').encode('utf-8')
                        self.request.sendall(b)
                    self.request.sendall(b'Event: QueueStatusComplete\r\nActionID: sq-live-queue\r\n\r\n')
                elif action=='Logoff':
                    return
                else:
                    raise RuntimeError('Unexpected action: '+action)

class Tests(unittest.TestCase):
    def test_parse_asterisk20_queue(self):
        data=parse_queue_events(QUEUE_EVENTS)
        self.assertEqual(data['8001']['Calls'],'2')
        self.assertEqual(data['8001']['members']['Local/100@from-queue/n']['Status'],'1')
        self.assertEqual(len(data['8001']['entries']),2)
        self.assertEqual(data['8001']['ServicelevelPerf'],'92.5')
    def test_missing_queue_detected(self):
        with self.assertRaises(RuntimeError):
            parse_queue_events(QUEUE_EVENTS,'8002')
    def test_readonly_actions_only(self):
        with socketserver.ThreadingTCPServer(('127.0.0.1',0),Handler) as server:
            server.calls=[]
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            try:
                data=read_queue_data('127.0.0.1',server.server_address[1],'sq_test','FAKE_LOCAL_ONLY')
                self.assertEqual(data['8001']['members']['Local/100@from-queue/n']['Status'],'1')
            finally:
                server.shutdown();thread.join(timeout=2)
            self.assertEqual(server.calls,['Login','QueueStatus','Logoff'])

if __name__=='__main__':unittest.main()
