"""Visible diagnostics for SaneQueue's local Flask server, Python-stdlib only.
Logs startup and error messages and opens the verified *current* port once ready.
"""
from __future__ import annotations
import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PORT = int(os.environ.get('SANEQUEUE_DEMO_PORT', '18895'))
HOST = '127.0.0.1'
BASE = f'http://{HOST}:{PORT}'
LOGDIR = ROOT/'logs'
LOGDIR.mkdir(parents=True,exist_ok=True)
LOGFILE = LOGDIR/'startup_last.log'


def line(message, log):
    print(message,flush=True)
    log.write(message+'\n')
    log.flush()


def port_in_use():
    with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((HOST,PORT)) == 0


def readiness(stop,log):
    url=BASE+'/__sanequeue__/build'
    deadline=time.monotonic()+45
    while not stop.is_set() and time.monotonic()<deadline:
        try:
            with urllib.request.urlopen(url,timeout=1.5) as resp:
                info=json.loads(resp.read(8192))
                if resp.status==200 and info.get('application')=='SaneQueue' and info.get('version')=='2.1.0-beta.17':
                    line('[OK] Flask web server is responding and version is verified.',log)
                    line('[OPEN] '+BASE+'/operations',log)
                    try:
                        webbrowser.open(BASE+'/operations',new=2)
                    except Exception as e:
                        line('[WARN] Could not open browser automatically: '+str(e),log)
                    return
        except Exception:
            pass
        stop.wait(0.5)
    if not stop.is_set():
        line('[WARN] Flask did not respond to build check within 45 seconds; inspect error lines below.',log)


def main():
    with LOGFILE.open('w',encoding='utf-8',errors='replace') as log:
        line('[INFO] Local start: '+time.strftime('%Y-%m-%d %H:%M:%S'),log)
        line('[INFO] Python: '+sys.version.split()[0],log)
        line('[INFO] Folder: '+str(ROOT),log)
        line('[INFO] Port: '+str(PORT),log)
        line('[INFO] Correct URL: '+BASE+'/operations',log)
        if port_in_use():
            line('[ERROR] Port '+str(PORT)+' is occupied. Check the existing process:',log)
            line('  PowerShell: Get-NetTCPConnection -LocalPort '+str(PORT)+' -State Listen | Select-Object OwningProcess',log)
            return 3
        cmd=[sys.executable,'-u',str(ROOT/'demo_monitor.py')]
        stop=threading.Event()
        try:
            proc=subprocess.Popen(cmd,cwd=ROOT,env=os.environ.copy(),stdout=subprocess.PIPE,
                                  stderr=subprocess.STDOUT,text=True,encoding='utf-8',errors='replace',bufsize=1)
            watcher=threading.Thread(target=readiness,args=(stop,log),daemon=True)
            watcher.start()
            assert proc.stdout is not None
            for message in proc.stdout:
                print(message,end='',flush=True)
                # One-time bootstrap password must NOT be written to logs.
                log.write('[REDACTED ONE-TIME PASSWORD]\n' if message.startswith('Password: ') else message)
                log.flush()
            status=proc.wait()
            stop.set()
            watcher.join(timeout=2)
            line('[EXIT] Server process ended with code '+str(status),log)
            if status:
                line('[ERROR] Read the traceback above or upload logs/startup_last.log.',log)
            return status
        except KeyboardInterrupt:
            stop.set()
            line('[INFO] Shutdown requested by user.',log)
            if 'proc' in locals() and proc.poll() is None:
                proc.terminate()
                try: proc.wait(timeout=5)
                except subprocess.TimeoutExpired: proc.kill()
            return 0
        except Exception as exc:
            stop.set()
            import traceback
            line('[ERROR] Launcher exception: '+repr(exc),log)
            traceback.print_exc()
            log.write(traceback.format_exc())
            return 1


if __name__=='__main__':
    raise SystemExit(main())
