"""Bounded failed-attempt budgets without locking out successful NAT users."""
from collections import OrderedDict
import threading
import time


class LoginLimiter:
    def __init__(self,clock=time.monotonic):
        self.clock=clock;self.lock=threading.Lock();self.attempts=OrderedDict()

    def reserve(self,address,username):
        keys=((('ip',str(address)[:64]),100),(('user',str(address)[:64],str(username)[:65].casefold()),20))
        with self.lock:
            now=self.clock();ticket=[]
            for key,limit in keys:
                count,since=self.attempts.get(key,(0,now))
                if now-since>=300:count,since=0,now
                if count>=limit:return None
                ticket.append((key,since,count))
            for key,since,count in ticket:
                self.attempts[key]=(count+1,since);self.attempts.move_to_end(key)
            while len(self.attempts)>4096:self.attempts.popitem(last=False)
            return ticket

    def success(self,ticket):
        with self.lock:
            for key,since,_ in ticket:
                current=self.attempts.get(key)
                if current is None or current[1]!=since:continue
                if key[0]=='user' or current[0]<=1:self.attempts.pop(key,None)
                else:self.attempts[key]=(current[0]-1,since)
