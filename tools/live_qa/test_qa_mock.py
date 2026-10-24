import importlib.util
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import socket
import threading
import unittest
from unittest.mock import patch
from pathlib import Path

spec = importlib.util.spec_from_file_location('sq_live_qa',Path(__file__).with_name('sanequeue_live_qa.py'))
qa = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qa)

class FakeAMI(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.listener=socket.socket()
        self.listener.bind(('127.0.0.1',0))
        self.listener.listen(1)
        self.port=self.listener.getsockname()[1]
        self.actions=[]
    def run(self):
        conn, _=self.listener.accept()
        with conn:
            conn.sendall(b'Asterisk Call Manager/6.0.0\r\n')
            buffer=b''
            while True:
                chunk=conn.recv(4096)
                if not chunk: break
                buffer+=chunk
                while b'\r\n\r\n' in buffer:
                    raw,buffer=buffer.split(b'\r\n\r\n',1)
                    lines=raw.decode().split('\r\n')
                    vals=dict(line.split(': ',1) for line in lines if ': ' in line)
                    action=vals.get('Action','')
                    self.actions.append(action)
                    if action=='Login':
                        conn.sendall(b'Response: Success\r\nActionID: sqaudit-login\r\n\r\n')
                    elif action=='QueueStatus':
                        conn.sendall(
                            b'Response: Success\r\nActionID: sqaudit-queue\r\nMessage: Queue status will follow\r\n\r\n'
                            b'Event: QueueParams\r\nActionID: sqaudit-queue\r\nQueue: 8001\r\nCalls: 1\r\nCompleted: 7\r\nAbandoned: 2\r\n\r\n'
                            b'Event: QueueMember\r\nActionID: sqaudit-queue\r\nQueue: 8001\r\nStatus: 5\r\nPaused: 0\r\nName: test\r\n\r\n'
                            b'Event: QueueEntry\r\nActionID: sqaudit-queue\r\nQueue: 8001\r\nCallerIDNum: 0987654321\r\n\r\n'
                            b'Event: QueueStatusComplete\r\nActionID: sqaudit-queue\r\n\r\n')
                    elif action=='Logoff':
                        self.listener.close()
                        return

class FakeHttp(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path=='/api/operations':
            obj={'data_source':'ami-live','queues':{'8001':{'Calls':'1','Completed':'7','Abandoned':'2','members':{'Local/100@from-queue/n':{'Status':'5','Paused':'0'}},'entries':{'x':{'CallerIDNum':'secret'}}}}}
        elif self.path=='/api/ami/control-status':
            obj={'enabled':False,'remaining_seconds':0}
        else:
            obj={'version':'2.1.0-beta.3','mode':'test-stage'}
        body=json.dumps(obj).encode()
        self.send_response(200)
        self.send_header('Content-Type','application/json')
        self.send_header('Content-Length',str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def log_message(self,*args):pass

class QA(unittest.TestCase):
    def test_local_comparison_and_secret_redaction(self):
        ami=FakeAMI(); ami.start()
        http=HTTPServer(('127.0.0.1',0),FakeHttp)
        t=threading.Thread(target=http.serve_forever,daemon=True);t.start()
        with patch.object(qa,'APP_ORIGIN',f'http://127.0.0.1:{http.server_port}'):
            panel=qa.panel_summary('8001')
        state=qa.query_ami('127.0.0.1',ami.port,'sq','example-local-password','8001')
        report=qa.compare(state,panel)
        self.assertTrue(all(report.values()))
        self.assertEqual(state['state_labels'],{'unavailable':1})
        ami.join(timeout=2)
        self.assertEqual(ami.actions,['Login','QueueStatus','Logoff'])
        self.assertNotIn('0987654321',json.dumps({'panel':panel,'ami':state}))
        self.assertNotIn('example-local-password',json.dumps({'panel':panel,'ami':state}))
        http.shutdown();http.server_close();ami.join(timeout=2)
    def test_target_restrictions(self):
        qa.safe_target('192.168.2.2',5038,'8001')
        qa.safe_target('127.0.0.1',15038,'8001')
        for host in ['8.8.8.8','169.254.1.2']:
            with self.assertRaises(ValueError):qa.safe_target(host,5038,'8001')
    def test_mismatch_detected(self):
        ami={'queue_found':True,'queue_members':1,'state_codes':{'5':1},'waiting_from_params':1,'waiting_entries':1,'completed_since_reset':1,'abandoned_since_reset':0}
        panel={'queue_found':True,'queue_members':1,'state_codes':{'1':1},'waiting':0,'waiting_entries':0,'completed_since_reset':1,'abandoned_since_reset':0,'source':'ami-live'}
        result=qa.compare(ami,panel)
        self.assertFalse(result['device_status_codes_match'])
        self.assertFalse(result['waiting_count_match'])
        self.assertTrue(result['members_match'])

if __name__=='__main__':unittest.main()
