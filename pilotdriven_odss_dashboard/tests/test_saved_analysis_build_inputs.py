"""Private test data must reach the test stage intact, without bulk corpus copying."""
import gzip
import hashlib
import io
import json
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
