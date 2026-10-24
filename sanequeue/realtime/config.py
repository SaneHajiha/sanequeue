"""Local administrator-owned configuration. Secrets never enter CLI output."""
import configparser
from dataclasses import dataclass, field
import re
import ssl


@dataclass
class Settings:
    host: str
    port: int
    user: str
    password: str = field(repr=False)
    redis_url: str = field(repr=False)
    pbx_id: str = 'primary'
    reconcile_seconds: float = 120
    heartbeat_seconds: float = 10
    publish_seconds: float = 1
    tls: object = field(default=None, repr=False)
    server_name: str = ''

    @classmethod
    def load(cls, path):
        cfg = configparser.ConfigParser(interpolation=None)
        if not cfg.read(path, encoding='utf-8'):
            raise ValueError('collector_config_missing')
        a, c = cfg['ami'], cfg['collector']
        obj = cls(host=a['host'], port=a.getint('port', 5038), user=a['user'],
                  password=a['password'], redis_url=c['redis_url'], pbx_id=c.get('pbx_id', 'primary'),
                  reconcile_seconds=c.getfloat('reconcile_seconds', 120),
                  heartbeat_seconds=c.getfloat('heartbeat_seconds', 10),
                  publish_seconds=c.getfloat('publish_seconds', 1))
        if (not obj.password or not obj.user or not obj.host or not 1 <= obj.port <= 65535 or
                not 30 <= obj.reconcile_seconds <= 3600 or not 2 <= obj.heartbeat_seconds <= 60 or
                not .5 <= obj.publish_seconds <= 10 or
                not re.fullmatch(r'[A-Za-z0-9_-]{1,48}', obj.pbx_id)):
            raise ValueError('invalid_collector_settings')
        if not obj.redis_url.startswith(('redis://', 'rediss://', 'unix://')):
            raise ValueError('invalid_redis_url')
        if a.getboolean('tls', False):
            obj.tls = ssl.create_default_context(cafile=a.get('ca_file') or None)
            obj.server_name = a.get('server_name', obj.host)
        return obj
