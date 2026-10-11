"""Verify the packaged OCR evidence and runtime bytes; fail on any mismatch."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import platform
import subprocess
import xml.etree.ElementTree as ET


DOC = Path("/usr/share/pilotdriven-tesseract")


def verify() -> dict:
    lock = json.loads((DOC / "component.lock.json").read_text())
    inventory = json.loads((DOC / "component.json").read_text())
    if platform.machine() != "x86_64" or inventory["architecture"] != "amd64":
        raise ValueError("OCR architecture mismatch")
    for key in ("sourceCommit", "source", "upstreamVersion", "baseImage"):
        if inventory[key] != lock[key]:
            raise ValueError(f"OCR provenance mismatch: {key}")
    for relative, expected in inventory["files"].items():
        if hashlib.sha256((Path("/") / relative).read_bytes()).hexdigest() != expected:
            raise ValueError(f"OCR installed file mismatch: {relative}")
    output = subprocess.check_output(["dpkg-query", "-W", "-f=${Version}", lock["package"]], text=True)
    if output != lock["packageVersion"]:
        raise ValueError("OCR package version mismatch")
    version = subprocess.check_output(["/usr/bin/tesseract", "--version"], text=True)
    if version.splitlines()[0] != "tesseract " + lock["binaryVersion"]:
        raise ValueError("OCR binary version mismatch")
    for variant in ("release", "sanitized"):
        for target, expected in lock["regressions"].items():
            prefix = DOC / "proof" / f"{variant}-{target}"
            receipt = json.loads(prefix.with_suffix(".json").read_text())
            if receipt["exitCode"] != 0 or hashlib.sha256(prefix.with_suffix(".log").read_bytes()).hexdigest() != receipt["logSha256"]:
                raise ValueError(f"OCR native regression failure: {prefix.name}")
            root = ET.parse(prefix.with_suffix(".xml")).getroot()
            cases = root.findall(".//testcase")
            if len(cases) != expected or any(c.get("result") != "completed" or c.find("failure") is not None or c.find("skipped") is not None for c in cases):
                raise ValueError(f"OCR regression coverage mismatch: {prefix.name}")
    model = Path(lock["englishModel"]["path"])
    if hashlib.sha256(model.read_bytes()).hexdigest() != lock["englishModel"]["sha256"]:
        raise ValueError("OCR English model mismatch")
    linked = subprocess.check_output(["ldd", "/usr/bin/tesseract"], text=True)
    if "not found" in linked or "libtesseract.so" in linked:
        raise ValueError("OCR linkage differs from the static component contract")
    return {"status": "PASS", "sourceCommit": lock["sourceCommit"], "binaryVersion": lock["binaryVersion"],
            "binarySha256": inventory["files"]["usr/bin/tesseract"], "englishModelSha256": lock["englishModel"]["sha256"],
            "releaseTests": sum(lock["regressions"].values()), "sanitizedTests": sum(lock["regressions"].values())}


if __name__ == "__main__":
    print(json.dumps(verify(), indent=2))
