from __future__ import annotations

import hashlib

import pytest

from scripts.run_private_cfp_corpus import build_analysis_receipt_binding


def test_analysis_receipt_binds_relative_path_and_exact_bytes(tmp_path) -> None:
    output_root = tmp_path / "corpus"
    analysis_path = output_root / "CASE-ONE" / "analysis" / "case_analysis.json"
    analysis_path.parent.mkdir(parents=True)
    analysis_bytes = b'{"analysis_id":"case-one"}\n'
    analysis_path.write_bytes(analysis_bytes)

    binding = build_analysis_receipt_binding(analysis_path, output_root)

    assert binding == {
        "analysis_json": "CASE-ONE/analysis/case_analysis.json",
        "analysis_sha256": hashlib.sha256(analysis_bytes).hexdigest(),
    }


def test_analysis_receipt_rejects_an_artifact_outside_corpus_output(tmp_path) -> None:
    output_root = tmp_path / "corpus"
    output_root.mkdir()
    analysis_path = tmp_path / "outside_analysis.json"
    analysis_path.write_text("{}\n", encoding="utf-8")

    with pytest.raises(
        AssertionError,
        match="must be contained by the private corpus output",
    ):
        build_analysis_receipt_binding(analysis_path, output_root)
