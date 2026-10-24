"""One background read-only AMI event listener with reconnect/backoff.

Shares no public credentials. When AMI is disconnected the UI explicitly
indicates stale tracking. This is a local single-process beta collector, not
multi-worker HA or guaranteed historical recording.
"""
import json
import random
import socket
import threading

from qpanel.ami_targets import validate_target
from AMI_READONLY_TEST import ReadOnlyAMI
from qpanel.call_journey import JourneyEngine


class JourneyListener:
    def __init__(self, engine=None):
        self.engine = engine or JourneyEngine()
        self.lock = threading.RLock()
        self.thread = None
        self.stop = None
        self.signature = None

    def configure(self, settings, trunk_map=None):
        if not settings.get('enabled') or not settings.get('password'):
            self.shutdown()
            return
        host,port,_=validate_target(settings['host'], settings['port'], settings.get('queue','*'))
        new=(host,port,settings['user'],settings['password'])
        with self.lock:
            if self.thread and self.thread.is_alive() and self.signature==new:
                return
            if self.stop:self.stop.set()
            self.stop=threading.Event()
            self.signature=new
            self.engine=JourneyEngine(trunk_map=trunk_map)
            self.thread=threading.Thread(target=self._run,args=(new,self.stop,self.engine),name='sanequeue-call-journey',daemon=True)
            self.thread.start()

    def shutdown(self):
        with self.lock:
            if self.stop:self.stop.set()
            if self.engine:self.engine.mark_connection(False)
            self.signature=None

    @staticmethod
    def _run(connection, stop, engine):
        host,port,user,password=connection
        delay=1.0
        while not stop.is_set():
            client=None
            try:
                client=ReadOnlyAMI(host,port,timeout=6)
                client.login(user,password,events='call,agent')
                engine.mark_connection(True)
                delay=1.0
                client.sock.settimeout(3)
                while not stop.is_set():
                    try:
                        event=client.read_packet()
                    except socket.timeout:
                        continue
                    if event.get('Event'):
                        engine.ingest(event)
            except (OSError,EOFError,TimeoutError,PermissionError,RuntimeError,ValueError):
                pass
            finally:
                engine.mark_connection(False)
                if client:
                    try:client.close()
                    except (OSError,EOFError):pass
            if stop.is_set():return
            # Jitter prevents synchronized reconnection after PBX restart.
            if stop.wait(min(25.0,delay+random.random())):return
            delay=min(25.0,delay*2)

    def snapshot(self, queues, *, numbers=False):
        with self.lock:
            return self.engine.snapshot(queues,numbers=numbers)


def parse_trunk_map(value):
    """Optional JSON map e.g. {\"PJSIP/ims-\": \"IMS SIP trunk\"}."""
    if not value:return {}
    try:
        parsed=json.loads(value)
        if not isinstance(parsed,dict) or len(parsed)>100:return {}
        return {str(k):str(v) for k,v in parsed.items() if str(k).startswith(('PJSIP/','SIP/','IAX2/','DAHDI/')) and len(str(k))<90 and len(str(v))<90}
    except (ValueError,TypeError):
        return {}
