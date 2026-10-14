"""The OCR build stage installs exactly the versions the component lock pins.

15 Oct 2026: Ubuntu published libcurl 8.5.0-2ubuntu10.16 to noble-security while the build stage pinned only
libcurl4-openssl-dev=...10.15. apt chose the newer runtime libcurl4t64 as the dependency candidate and the image
build failed after every release gate had passed. A -dev pin must travel with its exact runtime library pin, and
the Dockerfile must install every version the lock (checked again inside build_component.py) names.
"""
from pathlib import Path
import json
import re

ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = (ROOT / "Dockerfile").read_text()
LOCK = json.loads((ROOT / "ocr/component.lock.json").read_text())


def _ocr_build_pins() -> dict[str, str]:
    stage = DOCKERFILE.split(" AS ocr-build\n", 1)[1].split("\nFROM ", 1)[0]
    return dict(re.findall(r"^\s+([a-z0-9.+-]+)=(\S+) \\$", stage, re.M))


def test_dockerfile_build_stage_pins_equal_the_component_lock() -> None:
    assert _ocr_build_pins() == LOCK["buildPackages"]


def test_every_pinned_dev_library_also_pins_its_runtime_library_at_the_same_version() -> None:
    pins = _ocr_build_pins()
    assert pins["libcurl4-openssl-dev"] == pins["libcurl4t64"]
