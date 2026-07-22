from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import pytest


def test_sq303_sq304_external_golden_cases() -> None:
    sq303 = os.environ.get("ODSS_GOLDEN_SQ303_CFP")
    sq304 = os.environ.get("ODSS_GOLDEN_SQ304_CFP")
    if not sq303 or not sq304:
        pytest.skip("Set ODSS_GOLDEN_SQ303_CFP and ODSS_GOLDEN_SQ304_CFP to run proprietary golden cases")

    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [
            sys.executable,
            str(root / "scripts" / "run_v06_golden_regressions.py"),
            "--sq303",
            sq303,
            "--sq304",
            sq304,
        ],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert '"status": "passed"' in result.stdout
