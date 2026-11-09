import os
from pathlib import Path
import re
import stat
import subprocess
import sys

import pytest


@pytest.mark.skipif(sys.platform != "linux", reason="RC7 provisioning uses a Linux PTY")
def test_first_login_is_created_without_echoing_credentials(tmp_path):
    launcher = Path(__file__).resolve().parents[1] / "scripts/install-lan-rc7.sh"
    terminal_code = launcher.read_text().split('  "$PYTHON" -I - "$installer" <<\'PY\'\n', 1)[1]
    terminal_code = terminal_code.split("\nPY\n", 1)[0]
    credentials = tmp_path / "first-login"
    terminal_code = terminal_code.replace('"/root/.sanequeue-rc7-first-login"', repr(str(credentials)))
    terminal_code = terminal_code.replace("info.st_uid != 0", "info.st_uid != os.geteuid()")

    prompts = tmp_path / "prompts.py"
    prompts.write_text(
        "import getpass, re, sys\n"
        "assert sys.stdin.isatty()\n"
        "assert input('Administrator username [admin]: ') == ''\n"
        "password = getpass.getpass('Choose administrator password (12-200 characters): ')\n"
        "assert re.fullmatch(r'[A-Za-z0-9_-]{43}', password)\n"
        "assert password == getpass.getpass('Repeat administrator password: ')\n"
        "assert input('Administrator supervisor phone [none; can change in profile]: ') == ''\n"
        "print('Provisioned')\n"
    )
    installer = tmp_path / "install.sh"
    installer.write_text('exec "$FIXTURE_PYTHON" "$(dirname "$0")/prompts.py"\n')

    saved = None
    for _ in range(2):
        result = subprocess.run(
            [sys.executable, "-I", "-", str(installer)],
            input=terminal_code,
            env=dict(os.environ, FIXTURE_PYTHON=sys.executable),
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert result.returncode == 0, result.stderr
        assert "Provisioned" in result.stdout
        password = credentials.read_text().strip()
        assert re.fullmatch(r"[A-Za-z0-9_-]{43}", password)
        assert stat.S_IMODE(credentials.stat().st_mode) == 0o600
        assert password not in result.stdout + result.stderr
        assert saved is None or saved == password
        saved = password
