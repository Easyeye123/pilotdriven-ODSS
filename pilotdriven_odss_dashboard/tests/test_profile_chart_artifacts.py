"""Governed chart artifact loading and schematic extraction.

Chart bodies never enter the repository; these tests use synthetic artifacts
and synthetic page text in the published chart layout.
"""

from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path

import pytest

from app.odss.controlled_library import (
    ProfileChartUnavailableError,
    load_profile_chart_bytes,
)


_SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "build_depress_profile_index.py"
)
_SPEC = importlib.util.spec_from_file_location("depress_index_builder", _SCRIPT)
assert _SPEC and _SPEC.loader
_BUILDER = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_BUILDER)


def _artifact_profile(tmp_path: Path, payload: bytes) -> dict:
    path = tmp_path / "profile-9-9.pdf"
    path.write_bytes(payload)
    return {
        "chart": "9-9",
        "chart_artifact_key": "charts/profile-9-9.pdf",
        "chart_sha256": hashlib.sha256(payload).hexdigest(),
    }


def test_local_chart_artifact_round_trip(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ODSS_DEPRESS_CHART_DIR", str(tmp_path))
    profile = _artifact_profile(tmp_path, b"%PDF-1.7 synthetic")
    assert load_profile_chart_bytes(profile) == b"%PDF-1.7 synthetic"


def test_chart_artifact_hash_mismatch_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ODSS_DEPRESS_CHART_DIR", str(tmp_path))
    profile = _artifact_profile(tmp_path, b"%PDF-1.7 synthetic")
    (tmp_path / "profile-9-9.pdf").write_bytes(b"%PDF-1.7 TAMPERED")
    with pytest.raises(ProfileChartUnavailableError, match="hash"):
        load_profile_chart_bytes(profile)


def test_chart_artifact_requires_pinned_index_entry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ODSS_DEPRESS_CHART_DIR", str(tmp_path))
    with pytest.raises(ProfileChartUnavailableError, match="pinned"):
        load_profile_chart_bytes({"chart": "9-9"})


def test_chart_artifact_rejects_unsafe_keys(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ODSS_DEPRESS_CHART_DIR", str(tmp_path))
    with pytest.raises(ProfileChartUnavailableError, match="safe relative"):
        load_profile_chart_bytes(
            {
                "chart": "9-9",
                "chart_artifact_key": "../../etc/passwd",
                "chart_sha256": "00",
            }
        )


def test_chart_artifact_without_any_source_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ODSS_DEPRESS_CHART_DIR", raising=False)
    monkeypatch.delenv("ODSS_DEPRESS_PROFILE_INDEX_S3_URI", raising=False)
    with pytest.raises(ProfileChartUnavailableError, match="No chart artifact source"):
        load_profile_chart_bytes(
            {
                "chart": "9-9",
                "chart_artifact_key": "charts/profile-9-9.pdf",
                "chart_sha256": "00",
            }
        )


_SYNTHETIC_PAGE = """
   A350
   Depressurization Profiles                                    CPFIX
    DEPRESSURIZATION ALONG AIRWAYS Q1, Q2 BETWEEN ALPHA TO OMEGA / OMEGA TO ALPHA

                                        Q1                  Q2

                                                                CP - CPFIX

                                                                                         18,000 ft
                                                                                                                  OMEGA
                                                                                   115 nm                 42 nm
                                           16,000 ft                                             MIDDL
                  ALPHA
                              30 nm       177 nm
                                  BRAVO

                   IF DEPRESSURIZATION OCCURS BEFORE THE CRITICAL POINT, THE 180 TURN SHOULD BE
                           MADE INTO WIND AND KEEP WITHIN 20NM OF THE AIRWAY CENTERLINE.
"""


def test_parse_chart_page_extracts_schematic_facts() -> None:
    profile = {"chart": "9-9", "from": "ALPHA", "to": "OMEGA", "critical": "CPFIX"}
    schematic = _BUILDER.parse_chart_page(_SYNTHETIC_PAGE, profile)
    assert schematic is not None
    assert "ALPHA TO OMEGA" in schematic["header"]
    assert set(("ALPHA", "OMEGA", "CPFIX")) <= set(schematic["points"])
    assert "16,000 ft" in schematic["level_off_altitudes"]
    assert 177 in schematic["segment_distances_nm"]
    assert schematic["turn_note"].startswith("IF DEPRESSURIZATION OCCURS")


def test_parse_chart_page_fails_closed_on_mismatched_endpoints() -> None:
    profile = {"chart": "9-9", "from": "NOPE1", "to": "OMEGA", "critical": "CPFIX"}
    assert _BUILDER.parse_chart_page(_SYNTHETIC_PAGE, profile) is None
