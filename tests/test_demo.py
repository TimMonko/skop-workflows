"""The headless demo's checks, run as part of the suite.

`demo/headless.py` asserts the design's claims end to end, in one session
(docs/demo.md). It runs in its own process because it puts `demo/` on the
path and counts its checks in a module global.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

DEMO = Path(__file__).resolve().parents[1] / "demo" / "headless.py"


def test_every_demo_check_passes() -> None:
    done = subprocess.run(
        [sys.executable, str(DEMO)],
        capture_output=True,
        text=True,
        timeout=300,
    )
    failed = [line for line in done.stdout.splitlines() if "FAIL" in line]
    assert done.returncode == 0, "\n".join(failed) or done.stderr
