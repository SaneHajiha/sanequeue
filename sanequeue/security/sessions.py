"""Store only random-token hashes; logout revokes existing push connections."""
import hashlib
import re
import secrets
from sanequeue.actions.ledger import ActionLedger


class SessionRegistry(ActionLedger):
    def __init__(self,path,*,ttl=43200,**kwargs):
        super().__init__(path,**kwargs)
        self.ttl=max(300,min(31*86400,int(ttl)))
        with self.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS sessions(hash TEXT PRIMARY KEY,user TEXT,version TEXT,expires REAL)')

    @staticmethod
    def key(token):
        return hashlib.sha256(token.encode()).hexdigest() if isinstance(token,str) and re.fullmatch(r'[A-Za-z0-9_-]{43}',token) else None

    def issue(self,user,version):
        token=secrets.token_urlsafe(32)
        with self.db() as db:
            db.execute('DELETE FROM sessions WHERE expires<?',(self.clock(),))
            db.execute('INSERT INTO sessions VALUES (?,?,?,?)',(self.key(token),user,version,self.clock()+self.ttl))
            db.execute('DELETE FROM sessions WHERE hash IN (SELECT hash FROM sessions ORDER BY expires DESC LIMIT -1 OFFSET 5000)')
        return token

    def active(self,token,user,version):
        key=self.key(token)
        if not key:return False
        try:
            with self.db() as db:row=db.execute('SELECT 1 FROM sessions WHERE hash=? AND user=? AND version=? AND expires>?',(key,user,version,self.clock())).fetchone()
            return row is not None
        except Exception:
            return False

    def revoke(self,token):
        key=self.key(token)
        if key:
            with self.db() as db:db.execute('DELETE FROM sessions WHERE hash=?',(key,))

    def revoke_user(self,user):
        with self.db() as db:db.execute('DELETE FROM sessions WHERE user=?',(user,))
