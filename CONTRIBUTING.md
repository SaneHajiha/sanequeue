# Contributing

Open an issue describing the observed behavior, expected behavior, Python/Asterisk versions and reproduction steps using fictional callers. Do not attach private configurations or recordings.

```bash
python3.11 -m venv .venv
. .venv/bin/activate
pip install -r requirements/modern.txt pytest
pybabel compile -d qpanel/translations
python -m pytest tests --ignore=tests/historical -q
node --check qpanel/themes/qpanel/static/js/operations.js
```

Preserve Persian RTL and English LTR, keyboard access, local assets, server-side scope checks and upstream MIT notices. Add tests for authorization boundaries and changed PBX commands. Test call-control behavior against a disposable PBX, never an unsuspecting live caller.

Versions follow Semantic Versioning. `2.1.0-beta.N` identifies monitoring pilots; tag stable `2.1.0` only after controlled live-call acceptance. Document added/changed/fixed behavior and migration steps in CHANGELOG.md.
