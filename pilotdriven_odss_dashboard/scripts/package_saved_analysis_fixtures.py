"""Add only manifest-pinned private regression inputs to a private build archive.

The bundle is excluded from Docker COPY and supplied to the test stage through
a read-only named build context. It must never enter git or the runtime image.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import shutil
import tarfile
import tempfile
import zipfile


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "tests/fixtures/saved-analysis-v74-manifest.json"
BUNDLE_MEMBER = ".private-build-inputs/saved-analysis-v74.tar"


def build_bundle(corpus: Path, manifest: dict) -> bytes:
    cases = manifest["cases"]
    names = [case["file"] for case in cases]
    if not names or len(set(names)) != len(names):
        raise ValueError("Historical fixture names must be nonempty and unique")
    if any(Path(name).name != name or not name.endswith(".json.gz") for name in names):
        raise ValueError("Historical fixtures must be plain gzip JSON filenames")
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w", format=tarfile.USTAR_FORMAT) as archive:
        for case in cases:
            compressed = (corpus / "saved-analysis-v74" / case["file"]).read_bytes()
            raw = gzip.decompress(compressed)
            if (hashlib.sha256(compressed).hexdigest() != case["compressed_sha256"]
                    or hashlib.sha256(raw).hexdigest() != case["sha256"]):
                raise ValueError(f"Historical fixture changed: {case['file']}")
            json.loads(raw)
            member = tarfile.TarInfo(case["file"])
            member.size = len(compressed)
            member.mode = 0o444
            member.mtime = 0
            archive.addfile(member, io.BytesIO(compressed))
    return output.getvalue()


def add_to_source_archive(source_archive: Path, bundle: bytes) -> None:
    with zipfile.ZipFile(source_archive) as archive:
        if any(name.startswith(".private-build-inputs/") for name in archive.namelist()):
            raise ValueError("Source archive already contains private build inputs")
    # Leave the original source archive intact if packaging fails.
    with tempfile.TemporaryDirectory(dir=source_archive.parent) as temporary:
        candidate = Path(temporary) / "source.zip"
        shutil.copyfile(source_archive, candidate)
        with zipfile.ZipFile(candidate, "a", compression=zipfile.ZIP_DEFLATED) as archive:
            member = zipfile.ZipInfo(BUNDLE_MEMBER, date_time=(1980, 1, 1, 0, 0, 0))
            member.external_attr = 0o100600 << 16
            member.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(member, bundle)
        candidate.replace(source_archive)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus-dir", type=Path, required=True)
    parser.add_argument("--source-archive", type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads(MANIFEST.read_text())
    bundle = build_bundle(args.corpus_dir, manifest)
    add_to_source_archive(args.source_archive, bundle)
    print(json.dumps({"private_test_bundle": BUNDLE_MEMBER,
                      "case_count": len(manifest["cases"]),
                      "sha256": hashlib.sha256(bundle).hexdigest()}))


if __name__ == "__main__":
    main()
