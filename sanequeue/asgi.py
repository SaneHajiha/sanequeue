"""Server entrypoint; a single web process uses Redis, never a second collector."""
import os
os.environ['SANEQUEUE_RUNTIME'] = 'server'
from demo_monitor import module
from .gateway.app import create_app

app = create_app(module.app, os.environ.get('SANEQUEUE_PUBLIC_ORIGINS','').split(','))
