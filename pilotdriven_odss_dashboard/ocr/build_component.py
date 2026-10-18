"""Build the pinned upstream OCR source; package it only after its tests pass.

This is a build tool, never application code. Source and test archives are
content-addressed. The release executable and a separate ASan/UBSan build run
the same eight upstream regression targets. No source patch is applied here.
"""
from __future__ import annotations

import base64
import gzip
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import tarfile
import urllib.request
import xml.etree.ElementTree as ET


HERE = Path(__file__).resolve().parent
LOCK = json.loads((HERE / "component.lock.json").read_text())
WORK = Path("/ocr-work")
OUT = Path("/ocr-out")
PROOF = OUT / "proof"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(name: str, command: list[str], *, env: dict | None = None) -> str:
    print(f"OCR_BUILD {name}: {command}", flush=True)
    result = subprocess.run(command, capture_output=True, text=True, env=env)
    log = PROOF / f"{name}.log"
    log.write_text(result.stdout + result.stderr)
    (PROOF / f"{name}.json").write_text(json.dumps({
        "command": command, "exitCode": result.returncode, "logSha256": sha(log),
    }, indent=2) + "\n")
    print(result.stdout[-4000:] + result.stderr[-4000:], flush=True)
    if result.returncode:
        encoded = base64.b64encode(gzip.compress(log.read_bytes())).decode()
        for index in range(0, len(encoded), 20000):
            print(f"OCR_FAILED_LOG {name} {index // 20000} {encoded[index:index + 20000]}", flush=True)
        raise RuntimeError(f"{name} exited {result.returncode}; see {log}")
    return result.stdout


def unpack(item: dict, destination: Path) -> None:
    archive = WORK / (destination.name + ".tar.gz")
    request = urllib.request.Request(item["url"], headers={"User-Agent": "PilotDriven-build"})
    with urllib.request.urlopen(request, timeout=90) as response, archive.open("wb") as output:
        shutil.copyfileobj(response, output)
    if sha(archive) != item["sha256"]:
        raise ValueError(f"Archive digest mismatch: {item['url']}")
    destination.mkdir(parents=True)
    with tarfile.open(archive) as source:
        roots = {m.name.split("/")[0] for m in source.getmembers()}
        if len(roots) != 1:
            raise ValueError("Expected one archive root")
        scratch = WORK / (destination.name + "-unpack")
        source.extractall(scratch, filter="data")
        for child in (scratch / roots.pop()).iterdir():
            shutil.move(str(child), destination / child.name)


def compile_and_test(source: Path, name: str, sanitized: bool) -> Path:
    # Keep small local builds conservative; CI can budget more workers without
    # changing compiler flags, regression targets, or the sanitizer checks.
    jobs = os.environ.get("CMAKE_BUILD_PARALLEL_LEVEL", "2")
    if jobs not in tuple(str(value) for value in range(1, 9)):
        raise ValueError("CMAKE_BUILD_PARALLEL_LEVEL must be an integer from 1 to 8")
    build = WORK / name
    flags = [
        "-DBUILD_SHARED_LIBS=OFF", "-DBUILD_TRAINING_TOOLS=OFF", "-DBUILD_TESTS=ON",
        "-DDISABLED_LEGACY_ENGINE=OFF", "-DENABLE_NATIVE=OFF", "-DENABLE_LTO=OFF",
        "-DENABLE_CCACHE=OFF", "-DENABLE_PRECOMPILED_HEADERS=OFF", "-DOPENMP_BUILD=ON",
        "-DCMAKE_INSTALL_PREFIX=/usr", "-DCMAKE_INSTALL_DATAROOTDIR=share/tesseract-ocr/5",
        f"-DPACKAGE_VERSION={LOCK['binaryVersion']}",
    ]
    if sanitized:
        flags += ["-DCMAKE_BUILD_TYPE=Debug",
                  "-DCMAKE_CXX_FLAGS=-O1 -g -fsanitize=address,undefined -fno-omit-frame-pointer",
                  "-DCMAKE_C_FLAGS=-O1 -g -fsanitize=address,undefined -fno-omit-frame-pointer",
                  "-DCMAKE_EXE_LINKER_FLAGS=-fsanitize=address,undefined"]
    else:
        flags += ["-DCMAKE_BUILD_TYPE=Release"]
    run(name + "-configure", ["cmake", "-S", str(source), "-B", str(build), "-G", "Ninja", *flags])
    targets = list(LOCK["regressions"])
    run(name + "-compile", ["cmake", "--build", str(build), "--parallel", jobs, "--target", "tesseract", *targets])
    environment = {**os.environ, "OMP_THREAD_LIMIT": "1"}
    if sanitized:
        environment.update(ASAN_OPTIONS="detect_leaks=1:halt_on_error=1", UBSAN_OPTIONS="halt_on_error=1:print_stacktrace=1")
    for target, expected in LOCK["regressions"].items():
        candidates = [p for p in build.rglob(target) if p.is_file() and os.access(p, os.X_OK)]
        if len(candidates) != 1:
            raise ValueError(f"Expected exactly one {target} executable: {candidates}")
        report = PROOF / f"{name}-{target}.xml"
        run(name + "-" + target, [str(candidates[0]), "--gtest_output=xml:" + str(report)], env=environment)
        root = ET.parse(report).getroot()
        cases = root.findall(".//testcase")
        if (len(cases) != expected or int(root.get("failures", "0")) or int(root.get("errors", "0"))
                or int(root.get("disabled", "0")) or any(c.get("result") != "completed" or c.find("skipped") is not None for c in cases)):
            raise ValueError(f"Incomplete or failing regression report: {report}")
    return build


def main() -> None:
    if platform.machine() != "x86_64":
        raise RuntimeError("This lock targets Linux amd64 only")
    WORK.mkdir()
    PROOF.mkdir(parents=True)
    source = WORK / "tesseract"
    unpack(LOCK["source"], source)
    # The GitHub archive contains an empty submodule directory.
    google = source / "unittest/third_party/googletest"
    if google.exists():
        google.rmdir()
    unpack(LOCK["googletest"], google)
    for relative, digest in LOCK["sourceFiles"].items():
        if sha(source / relative) != digest:
            raise ValueError(f"Pinned source file mismatch: {relative}")
    if (source / "VERSION").read_text().strip() != LOCK["upstreamVersion"]:
        raise ValueError("Upstream version changed")
    packages = run("builder-packages", ["dpkg-query", "-W", "-f=${binary:Package}\t${Version}\t${Architecture}\n"])
    installed = {p.split("\t")[0].split(":")[0]: p.split("\t")[1] for p in packages.splitlines()}
    for package, version in LOCK["buildPackages"].items():
        if installed.get(package) != version:
            raise ValueError(f"Compiler/dependency drift: {package}")
    run("compiler", ["g++", "--version"])
    release = compile_and_test(source, "release", False)
    compile_and_test(source, "sanitized", True)
    # Do not ship development headers, training tools, test executables or the
    # sanitizer build. libtesseract is statically linked into this executable;
    # its Ubuntu runtime libraries retain their own normal dpkg inventory.
    package = OUT / "package"
    binary = package / "usr/bin/tesseract"
    binary.parent.mkdir(parents=True)
    shutil.copy2(release / "bin/tesseract", binary)
    run("binary-version", [str(binary), "--version"])
    run("binary-linkage", ["ldd", str(binary)])
    docs = package / "usr/share/pilotdriven-tesseract"
    shutil.copytree(PROOF, docs / "proof")
    license_dir = package / "usr/share/doc/pilotdriven-tesseract"
    license_dir.mkdir(parents=True)
    shutil.copy2(source / "LICENSE", license_dir / "copyright")
    shutil.copy2(HERE / "component.lock.json", docs / "component.lock.json")
    shutil.copy2(HERE / "verify_component.py", docs / "verify_component.py")
    data = package / "usr/share/tesseract-ocr/5/tessdata"
    for directory in ("configs", "tessconfigs"):
        shutil.copytree(source / "tessdata" / directory, data / directory)
    files = {str(p.relative_to(package)): sha(p) for p in sorted(package.rglob("*")) if p.is_file()}
    manifest = {"schemaVersion": 1, "package": LOCK["package"], "version": LOCK["packageVersion"],
                "architecture": "amd64", "source": LOCK["source"], "sourceCommit": LOCK["sourceCommit"],
                "baseImage": LOCK["baseImage"], "upstreamVersion": LOCK["upstreamVersion"],
                "buildScriptSha256": sha(Path(__file__)), "files": files,
                "testScope": f"{sum(LOCK["regressions"].values())} upstream tests, release and ASan/UBSan; not the entire upstream suite"}
    (docs / "component.json").write_text(json.dumps(manifest, indent=2) + "\n")
    control = package / "DEBIAN"
    control.mkdir()
    (control / "control").write_text(
        f"Package: {LOCK['package']}\nVersion: {LOCK['packageVersion']}\nArchitecture: amd64\n"
        "Maintainer: PilotDriven maintainers\nSection: graphics\nPriority: optional\n"
        "Provides: tesseract-ocr\nConflicts: tesseract-ocr, libtesseract5\nReplaces: tesseract-ocr\n"
        "Depends: liblept5, libarchive13t64, libcurl4t64, libgomp1, libstdc++6, libgcc-s1, libc6, tesseract-ocr-eng (= 1:4.1.0-2), tesseract-ocr-osd (= 1:4.1.0-2)\n"
        "Homepage: https://github.com/tesseract-ocr/tesseract\n"
        "Description: PilotDriven build of pinned upstream Tesseract security fixes\n"
        f" Upstream {LOCK['upstreamVersion']} plus commit {LOCK['sourceCommit']}.\n"
        " Includes static libtesseract, license, source inventory and regression receipts.\n")
    run("package", ["dpkg-deb", "--root-owner-group", "--build", str(package), str(OUT / "pilotdriven-tesseract.deb")])
    print("OCR_COMPONENT " + json.dumps({"sourceCommit": LOCK["sourceCommit"], "binarySha256": sha(binary),
                                        "packageSha256": sha(OUT / "pilotdriven-tesseract.deb"),
                                        "releaseTests": sum(LOCK["regressions"].values()), "sanitizedTests": sum(LOCK["regressions"].values())}), flush=True)


if __name__ == "__main__":
    main()
