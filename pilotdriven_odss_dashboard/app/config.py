from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(
    os.environ.get("ODSS_DATA_DIR", str(BASE_DIR / "data"))
).expanduser().resolve()
VERSION_FILE = BASE_DIR / "VERSION"
APP_VERSION = VERSION_FILE.read_text(encoding="utf-8").strip() if VERSION_FILE.is_file() else "0.0.0"
