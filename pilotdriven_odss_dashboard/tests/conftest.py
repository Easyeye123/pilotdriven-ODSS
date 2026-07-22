from __future__ import annotations

import os
from pathlib import Path
import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


# Unit and regression suites must not depend on the live aviation feed. Tests
# that exercise VAA pass an explicit, timestamped provider snapshot instead.
os.environ.setdefault("ODSS_VA_SIGMET_SOURCE", "disabled")
