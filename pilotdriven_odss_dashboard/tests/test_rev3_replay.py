from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts import render_rev3_replay as replay


def inputs(tmp_path):
    analysis = tmp_path / "analysis.json"
    source = tmp_path / "source.pdf"
    analysis.write_text(json.dumps({"flight": {"test": True}, "findings": [],
                                   "view": {"warnings": ["original warning"]}}))
    source.write_bytes(b"source bytes")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({
        "schema_version": 1, "gate": "rev3-historical-input-replay",
        **{key: {"filename": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
           for key, path in [("analysis", analysis), ("source", source)]},
    }))
    return analysis, source, manifest


@pytest.mark.parametrize("target", ["analysis", "source"])
def test_changed_input_is_rejected_before_rendering(tmp_path, monkeypatch, target):
    analysis, source, manifest = inputs(tmp_path)
    (analysis if target == "analysis" else source).write_bytes(b"changed")
    monkeypatch.setattr(replay, "render_combined_briefing", lambda *a, **k: pytest.fail("rendered untrusted input"))
    with pytest.raises(ValueError, match="identity mismatch"):
        replay.render_replay(analysis, source, tmp_path / "candidate.pdf", manifest)


def test_missing_input_is_rejected(tmp_path):
    analysis, source, manifest = inputs(tmp_path)
    analysis.unlink()
    with pytest.raises(FileNotFoundError):
        replay.render_replay(analysis, source, tmp_path / "candidate.pdf", manifest)


def test_current_renderer_receives_verified_source_and_capture(tmp_path, monkeypatch):
    analysis, source, manifest = inputs(tmp_path)
    calls = []
    def render(flight, findings, warnings, candidate, **kwargs):
        calls.append((flight, warnings, kwargs))
        candidate.write_bytes(b"freshly rendered")
    monkeypatch.setattr(replay, "render_combined_briefing", render)
    receipt = replay.render_replay(analysis, source, tmp_path / "candidate.pdf", manifest)
    assert calls == [({"test": True}, ["original warning"], {
        "source_pdf_path": str(source), "weather_charts": {}, "include_audit_appendix": True})]
    assert receipt["candidate_sha256"] == hashlib.sha256(b"freshly rendered").hexdigest()
    assert receipt["status"] == "passed"


def test_pinned_replay_source_matches_mandatory_corpus():
    manifest = json.loads(replay.DEFAULT_MANIFEST.read_text())
    corpus = json.loads(Path(__file__).with_name("private_cfp_corpus_manifest.json").read_text())
    case = next(c for c in corpus["cases"] if c["case_id"] == manifest["case_id"])
    assert manifest["source"] == {"filename": case["filename"], "sha256": case["source_sha256"]}
