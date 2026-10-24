"""Mock AMI server validates read-only wire actions and sanitized output."""
import importlib.util
import socketserver
import threading
import unittest
from pathlib import Path

HERE=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('sq_ami_client',HERE/'AMI_READONLY_TEST.py')
mod=importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

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
                act=kv.get(b'Action',b'').decode()
                self.server.calls.append(act)
                if act=='Login':
                    self.request.sendall(b'Response: Success\r\nActionID: sq-login\r\nMessage: Authentication accepted\r\n\r\n')
                elif act=='QueueStatus':
                    response=(b'Response: Success\r\nActionID: sq-queue-read\r\nMessage: Queue status follows\r\n\r\n'
                              b'Event: QueueParams\r\nActionID: sq-queue-read\r\nQueue: 8001\r\nCalls: 2\r\n\r\n'
                              b'Event: QueueMember\r\nActionID: sq-queue-read\r\nName: sample sensitive agent\r\nStatus: 5\r\nPaused: 0\r\n\r\n'
                              b'Event: QueueEntry\r\nActionID: sq-queue-read\r\nCallerIDNum: 09129999999\r\n\r\n'
                              b'Event: QueueStatusComplete\r\nActionID: sq-queue-read\r\n\r\n')
                    self.request.sendall(response)
                elif act=='Logoff':
                    return
                else:
                    raise RuntimeError('Dangerous action received by mock AMI: '+act)

class Tests(unittest.TestCase):
    def test_queue_status_is_readonly_and_sanitized(self):
        with socketserver.ThreadingTCPServer(('127.0.0.1',0), Handler) as server:
            server.calls=[]
            t=threading.Thread(target=server.serve_forever,daemon=True);t.start()
            c=mod.ReadOnlyAMI('127.0.0.1',server.server_address[1])
            try:
                c.login('sq_readonly','LOCAL_FAKE_PASSWORD_DO_NOT_SHARE')
                data=c.queue_snapshot('8001')
                self.assertTrue(data['snapshot_complete'])
                self.assertEqual(data['waiting_calls'],2)
                self.assertEqual(data['members'],1)
                self.assertNotIn('09129999999',str(data))
                self.assertNotIn('LOCAL_FAKE_PASSWORD',str(data))
            finally:
                c.close();server.shutdown();t.join(timeout=2)
            self.assertEqual(server.calls,['Login','QueueStatus','Logoff'])

    def test_field_injection_rejected(self):
        with self.assertRaises(ValueError): mod.wire({'Secret':'bad\r\nAction: Hangup'})

if __name__=='__main__':unittest.main()
