"""Private test data must reach the test stage intact, without bulk corpus copying."""
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tarfile
import zipfile

import pytest

from scripts.package_saved_analysis_fixtures import BUNDLE_MEMBER, add_to_source_archive, build_bundle


def fixture(tmp_path):
    raw = b'{"label":"SYNTHETIC packaging input; no operational answer"}'
    compressed = gzip.compress(raw, mtime=0)
    directory = tmp_path / "saved-analysis-v74"
    directory.mkdir()
    path = directory / "example.json.gz"
    path.write_bytes(compressed)
    (directory / "unlisted-private-file.txt").write_text("must not be packaged")
    case = {"file": path.name, "sha256": hashlib.sha256(raw).hexdigest(),
            "compressed_sha256": hashlib.sha256(compressed).hexdigest()}
    return {"cases": [case]}, path


def test_archive_preserves_sources_and_contains_only_pinned_fixture_bytes(tmp_path):
    manifest, path = fixture(tmp_path)
    bundle = build_bundle(tmp_path, manifest)
    assert bundle == build_bundle(tmp_path, manifest), "bundle identity must be deterministic"
    with tarfile.open(fileobj=io.BytesIO(bundle), mode="r:") as archive:
        assert archive.getnames() == [path.name]
        assert archive.extractfile(path.name).read() == path.read_bytes()
    source = tmp_path / "source.zip"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("Dockerfile", b"unchanged source bytes")
    add_to_source_archive(source, bundle)
    with zipfile.ZipFile(source) as archive:
        assert set(archive.namelist()) == {"Dockerfile", BUNDLE_MEMBER}
        assert archive.read("Dockerfile") == b"unchanged source bytes"
        assert archive.read(BUNDLE_MEMBER) == bundle
    before = source.read_bytes()
    with pytest.raises(ValueError, match="already contains"):
        add_to_source_archive(source, bundle)
    assert source.read_bytes() == before, "duplicate input must not partly mutate the archive"


@pytest.mark.parametrize("damage", ["missing", "modified", "corrupt", "raw_hash", "compressed_hash"])
def test_invalid_private_inputs_refuse_packaging(tmp_path, damage):
    manifest, path = fixture(tmp_path)
    if damage == "missing":
        path.unlink()
    elif damage == "modified":
        path.write_bytes(gzip.compress(b'{}', mtime=0))
    elif damage == "corrupt":
        path.write_bytes(b"not gzip")
    else:
        manifest["cases"][0]["sha256" if damage == "raw_hash" else "compressed_sha256"] = "0" * 64
    with pytest.raises((FileNotFoundError, ValueError, gzip.BadGzipFile)):
        build_bundle(tmp_path, manifest)


@pytest.mark.parametrize("names", [["../outside.json.gz"], ["/outside.json.gz"], ["a.json.gz", "a.json.gz"], []])
def test_manifest_cannot_copy_unbounded_or_ambiguous_private_paths(tmp_path, names):
    with pytest.raises(ValueError):
        build_bundle(tmp_path, {"cases": [{"file": name} for name in names]})


@pytest.mark.parametrize("missing", [False, True])
def test_build_command_delivers_large_readable_input_or_stops_before_docker(tmp_path, missing):
    """Exercise the actual build command with a strict transport boundary double.

    A real CodeBuild probe additionally tests mount and runtime-layer behavior.
    The synthetic payload exceeds BuildKit's 500 KiB per-secret limit.
    """
    root = Path(__file__).resolve().parents[1]
    buildspec = (root / "buildspec.aws.yml").read_text()
    block = buildspec.split("  build:\n    commands:\n      - |\n", 1)[1].split("\n      - ", 1)[0]
    command = "\n".join(line[8:] for line in block.splitlines())
    bundle = tmp_path / BUNDLE_MEMBER
    bundle.parent.mkdir()
    if not missing:
        bundle.write_bytes(b"SYNTHETIC transport bytes; no flight content\n" * 20_000)
        bundle.chmod(0o600)
    binary = tmp_path / "bin"
    binary.mkdir()
    docker = binary / "docker"
    docker.write_text('''#!/usr/bin/env python3
import hashlib, pathlib, sys
args = sys.argv[1:]
assert "--secret" not in args
context = args[args.index("--build-context") + 1]
assert context.startswith("saved_analyses=")
bundle = pathlib.Path(context.split("=", 1)[1]) / "saved-analysis-v74.tar"
assert bundle.stat().st_size > 500 * 1024
assert bundle.stat().st_mode & 0o444 == 0o444
assert args[args.index("--build-arg") + 1] == "SAVED_ANALYSIS_BUNDLE_SHA256=" + hashlib.sha256(bundle.read_bytes()).hexdigest()
pathlib.Path("docker-reached.json").write_text("true")
''')
    docker.chmod(0o755)
    env = {**os.environ, "PATH": str(binary) + os.pathsep + os.environ["PATH"],
           "ECR_REPOSITORY_URI": "synthetic-transport-test", "IMAGE_TAG": "not-pushed"}
    result = subprocess.run(["bash", "-c", command], cwd=tmp_path, env=env, capture_output=True, text=True)
    assert (result.returncode != 0) if missing else (result.returncode == 0), result.stderr
    assert (tmp_path / "docker-reached.json").exists() is not missing
