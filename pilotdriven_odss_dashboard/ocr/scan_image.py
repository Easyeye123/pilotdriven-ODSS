"""Scan the entire image and explicitly inventory the statically linked OCR.

Keep both raw scans. A generated OpenVEX 'fixed' statement is limited to the
exact source/binary identity verified in this image; it is not a risk waiver.
An unknown HIGH/CRITICAL, missing feed coverage, hidden match or failed command
blocks the build. ECR's independent image gate remains mandatory after push.
"""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tarfile
import urllib.parse
import urllib.request


HERE = Path(__file__).resolve().parent
LOCK = json.loads((HERE / "component.lock.json").read_text())
OUT = Path("security-evidence")
TOOLS = Path("/tmp/pilotdriven-security-tools")
ENV = {k: v for k, v in os.environ.items() if not k.startswith(("GRYPE_", "SYFT_"))}
ENV.update(GRYPE_DB_AUTO_UPDATE="false", GRYPE_DB_VALIDATE_AGE="true", GRYPE_DB_MAX_ALLOWED_BUILT_AGE="48h")
RELEASES = {
    "syft": ("1.54.1", "c069905b391cc4c20a5ba65ad5c10be2a7ba074f8ea6ad203e24d14e303dad47"),
    "grype": ("0.120.1", "0a9ee97ef5ae2ee953b0a80098105052e846cdbe319a57d808b519c33cd1343d"),
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(name: str, value: object) -> Path:
    path = OUT / name
    path.write_text(json.dumps(value, indent=2) + "\n")
    return path


def run(name: str, command: list[str], allowed: tuple[int, ...] = (0,)) -> subprocess.CompletedProcess:
    result = subprocess.run(command, capture_output=True, text=True, env=ENV)
    (OUT / (name + ".stdout")).write_text(result.stdout)
    (OUT / (name + ".stderr")).write_text(result.stderr)
    write(name + ".command.json", {"command": command, "exitCode": result.returncode})
    print(f"SECURITY_COMMAND {name} exit={result.returncode}", flush=True)
    if result.returncode not in allowed:
        raise RuntimeError(f"{name} exited {result.returncode}: {result.stderr[-2000:]}")
    return result


def install_tools() -> None:
    if platform.machine() != "x86_64":
        raise RuntimeError("Scanner lock targets Linux amd64")
    TOOLS.mkdir(exist_ok=True)
    records = {}
    for name, (version, digest) in RELEASES.items():
        url = f"https://github.com/anchore/{name}/releases/download/v{version}/{name}_{version}_linux_amd64.tar.gz"
        archive = TOOLS / (name + ".tar.gz")
        urllib.request.urlretrieve(url, archive)
        if sha(archive) != digest:
            raise ValueError(f"Scanner archive digest mismatch: {name}")
        with tarfile.open(archive) as source:
            source.extract(name, TOOLS, filter="data")
        records[name] = {"version": version, "url": url, "archiveSha256": digest, "binarySha256": sha(TOOLS / name)}
        run(name + "-version", [str(TOOLS / name), "version", "-o", "json"])
    write("scanner-lock.json", records)


def match_key(match: dict) -> tuple[str, str, str]:
    artifact = match["artifact"]
    return match["vulnerability"]["id"], artifact["name"], artifact["version"]


def validate_findings(image: dict, raw: dict, fixed: dict, fixes: set[str]) -> list[str]:
    """Pure fail-closed comparison, also exercised with tampered scan controls."""
    failures = []
    if image.get("ignoredMatches") or raw.get("ignoredMatches"):
        failures.append("Unexpected filtering in an unfiltered scan")
    for scan, label in ((image, "image"), (raw, "component raw"), (fixed, "component fixed")):
        if not isinstance(scan.get("matches"), list):
            failures.append(f"Missing match list: {label}")
    if failures:
        return failures
    raw_ids = {m["vulnerability"]["id"] for m in raw["matches"]}
    if not fixes <= raw_ids:
        failures.append("Vulnerability feed does not cover all pinned OCR advisories")
    ignored = fixed.get("ignoredMatches", [])
    if any(m["vulnerability"]["id"] not in fixes or m["artifact"]["name"] != "tesseract" for m in ignored):
        failures.append("VEX filtered a finding outside the proven OCR fixes")
    if {m["vulnerability"]["id"] for m in ignored} != fixes:
        failures.append("VEX did not resolve exactly the proven OCR advisories")
    if sorted(map(match_key, raw["matches"])) != sorted(map(match_key, fixed["matches"] + ignored)):
        failures.append("A raw component finding was lost or invented")
    for scan, label in ((image, "image"), (fixed, "component")):
        for match in scan["matches"]:
            if match["vulnerability"]["severity"].lower() in {"high", "critical"}:
                failures.append(f"Unresolved {label}: {match_key(match)}")
    return failures


def main(image: str) -> None:
    OUT.mkdir(exist_ok=False)
    inspect = json.loads(run("image-inspect", ["docker", "image", "inspect", image]).stdout)[0]
    if inspect["Architecture"] != "amd64" or inspect["Os"] != "linux":
        raise ValueError("Unexpected image architecture")
    image_id = inspect["Id"]
    verified = json.loads(run("component-runtime", ["docker", "run", "--rm", "--network", "none", "--entrypoint", "python3",
                         image_id, "/usr/share/pilotdriven-tesseract/verify_component.py"]).stdout)
    if verified["status"] != "PASS" or verified["sourceCommit"] != LOCK["sourceCommit"]:
        raise ValueError("Image does not contain this candidate's verified component")
    container = run("evidence-container", ["docker", "create", image_id]).stdout.strip()
    try:
        run("component-evidence", ["docker", "cp", container + ":/usr/share/pilotdriven-tesseract", str(OUT / "component")])
    finally:
        run("evidence-container-remove", ["docker", "rm", container])
    component = json.loads((OUT / "component/component.json").read_text())
    if ((OUT / "component/component.lock.json").read_bytes() != (HERE / "component.lock.json").read_bytes()
            or sha(OUT / "component/verify_component.py") != sha(HERE / "verify_component.py")
            or component["buildScriptSha256"] != sha(HERE / "build_component.py")):
        raise ValueError("Component build inputs differ from the checked-out candidate")
    install_tools()
    config = write("grype.config.json", {"ignore": [], "vex-documents": []})
    syft_config = write("syft.config.json", {})
    grype = [str(TOOLS / "grype"), "--config", str(config)]
    run("db-update", [*grype, "db", "update"])
    run("db-status", [*grype, "db", "status", "-o", "json"])
    run("image-sbom", [str(TOOLS / "syft"), "--config", str(syft_config), "docker:" + image_id,
                       "-o", "syft-json=" + str(OUT / "image.syft.json"),
                       "-o", "cyclonedx-json=" + str(OUT / "image.cdx.json")])
    sbom = json.loads((OUT / "image.syft.json").read_text())
    packages = sbom["artifacts"]
    custom = [p for p in packages if p["name"] == LOCK["package"] and p["version"] == LOCK["packageVersion"]]
    if len(custom) != 1 or any(p["name"] in {"tesseract-ocr", "libtesseract5"} for p in packages):
        raise ValueError("Custom package missing/duplicated, or obsolete runtime package remains")
    # A static executable is not reliably detected by distro-only scanners.
    # Add an explicit upstream entry with its honest 5.5.3 version, exact source
    # commit and binary hash. Never pretend this is a released 5.5.4 or ESM .deb.
    purl = "pkg:generic/tesseract@" + urllib.parse.quote(LOCK["binaryVersion"], safe="") + "?checksum=sha256:" + verified["binarySha256"]
    entry = {"type": "application", "name": "tesseract", "version": LOCK["upstreamVersion"],
             "bom-ref": purl, "purl": purl, "cpe": LOCK["cpe"],
             "hashes": [{"alg": "SHA-256", "content": verified["binarySha256"]}],
             "properties": [{"name": "pilotdriven:sourceCommit", "value": LOCK["sourceCommit"]}],
             "externalReferences": [{"type": "vcs", "url": "https://github.com/tesseract-ocr/tesseract/tree/" + LOCK["sourceCommit"]}]}
    standalone = write("component.cdx.json", {"bomFormat": "CycloneDX", "specVersion": "1.5", "version": 1, "components": [entry]})
    full = json.loads((OUT / "image.cdx.json").read_text())
    full["components"].append(entry)
    write("complete-inventory.cdx.json", full)
    image_scan = run("image-scan", [*grype, "sbom:" + str(OUT / "image.syft.json"), "--by-cve", "--fail-on", "high", "-o", "json"], (0, 2))
    raw = run("component-raw-scan", [*grype, "sbom:" + str(standalone), "--by-cve", "--fail-on", "high", "-o", "json"], (0, 2))
    timestamp = dt.datetime.now(dt.timezone.utc).isoformat()
    vex = write("component.fixed.openvex.json", {
        "@context": "https://openvex.dev/ns/v0.2.0", "@id": "urn:sha256:" + sha(OUT / "component/component.json"),
        "author": "PilotDriven build pipeline", "timestamp": timestamp, "version": 1,
        "statements": [{"vulnerability": {"name": cve}, "products": [{"@id": purl}], "status": "fixed",
                        "timestamp": timestamp, "action_statement": f"Upstream fix {url}; built source {LOCK['sourceCommit']}; binary SHA256 {verified['binarySha256']}; validated release and ASan/UBSan regressions in component/proof."}
                       for cve, url in sorted(LOCK["fixes"].items())],
    })
    fixed = run("component-fixed-scan", [*grype, "sbom:" + str(standalone), "--by-cve", "--vex", str(vex), "--fail-on", "high", "-o", "json"], (0, 2))
    failures = validate_findings(json.loads(image_scan.stdout), json.loads(raw.stdout), json.loads(fixed.stdout), set(LOCK["fixes"]))
    if image_scan.returncode or fixed.returncode:
        failures.append("Image or fixed-component scanner returned a blocking native exit")
    receipt = {"status": "FAIL" if failures else "PASS", "imageId": image_id, "component": verified,
               "imageScanExit": image_scan.returncode, "componentRawScanExit": raw.returncode,
               "componentFixedScanExit": fixed.returncode, "failures": failures,
               "evidence": {str(p.relative_to(OUT)): sha(p) for p in sorted(OUT.rglob("*")) if p.is_file()}}
    write("gate-receipt.json", receipt)
    print("OCR_SECURITY_GATE " + json.dumps({k: v for k, v in receipt.items() if k != "evidence"}), flush=True)
    if failures:
        raise RuntimeError("OCR/image security gate failed; deployment is blocked")


def emit_evidence() -> None:
    if not OUT.is_dir():
        return
    archive = OUT.with_suffix(".tar.gz")
    with tarfile.open(archive, "w:gz") as output:
        output.add(OUT, arcname="security-evidence")
    encoded = base64.b64encode(archive.read_bytes()).decode()
    print("PD_SECURITY_EVIDENCE_SHA256 " + sha(archive))
    for index in range(0, len(encoded), 20000):
        print(f"PD_SECURITY_EVIDENCE {index // 20000} {encoded[index:index + 20000]}")


if __name__ == "__main__":
    try:
        main(sys.argv[1])
    finally:
        emit_evidence()
