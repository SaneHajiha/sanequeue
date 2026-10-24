"""Supported single-process server entrypoint (separate from Windows preview)."""
import os
os.environ['SANEQUEUE_RUNTIME'] = 'server'
from demo_monitor import module
app = module.app
