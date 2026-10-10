"""F8 of Codex's QA of releases 468-474 (10 Oct 2026): a TAF too long for the WEATHER page no longer aborts the PDF.

LABELLED SYNTHETIC: the genuine SQ24 SIN-JFK analysis with its KJFK (and, in one case, WSSS) TAF extended to 11-32
FM groups, a mixed FM/TEMPO/PROB30/BECMG TAF, and two long TAFs at once. Until this repair every case of 12 or more
FM groups failed every WEATHER-page grid, readable size and deferral rung, and the whole six-page PDF aborted ("Concise
PDF capacity exceeded in WEATHER / ROUTE HAZARDS ... No source continuation is permitted"). David's format admits no
seventh page, so the page now keeps each TAF's largest whole-group prefix and states how many trailing groups the
dashboard holds - only after every earlier rung, never inside a group, never silently. A TAF the page can hold is
printed whole exactly as before.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import fitz
import pytest

from app.analysis import run_odss_analysis
from app.odss import reference_conformance as conformance
from app.odss.briefing import build_briefing_view
from app.odss.combined_brief import render_combined_briefing
from app.odss.concise_pdf_gate import WEATHER_PAGE, check_concise_pdf, normalized
from app.odss.page_one_weather import (
    TAF_CONTINUATION,
    page_one_taf_change_groups,
    page_one_weather_record,
    weather_page_taf_field,
)

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT.parent / "private_cfp_corpus"
SQ24 = CORPUS / "lido-briefing_SQ_24_15Aug2026_SIN_JFK.pdf"
MANIFEST = json.loads((ROOT / "tests" / "boss_reference_format_manifest.json").read_text(encoding="utf-8"))
BASE = "FT 212321 2200/2306 18012G18KT 6SM -TSRA BKN025 OVC050CB"


def fm_taf(groups: int, day_hour: str = "22") -> str:
    return f"{BASE} " + " ".join(f"FM{day_hour}{hour:02d}00 {180 + hour:03d}13G19KT P6SM VCSH BKN025 OVC040" for hour in range(1, groups + 1)) + "="


def mixed_taf(groups: int) -> str:
    kinds = ["TEMPO 2203/2206 4000 TSRA BKN012CB", "PROB30 2206/2209 2000 +TSRA BKN008CB", "BECMG 2209/2211 24012KT 9999 SCT030"]
    parts = [f"FM22{hour:02d}00 {180 + hour:03d}13G19KT P6SM VCSH BKN025 OVC040" if hour % 2 else kinds[hour % 3] for hour in range(1, groups + 1)]
    return f"{BASE} " + " ".join(parts) + "="


_ANALYSIS: dict[str, dict] = {}


def sq24(tmp_path_factory) -> dict:
    if "SQ24" not in _ANALYSIS:
        if not SQ24.is_file():
            pytest.skip("private CFP corpus file for SQ24 is not available")
        root = tmp_path_factory.mktemp("f8-sq24")
        result = run_odss_analysis(SQ24, root / "analysis", root / "reports", 1)
        _ANALYSIS["SQ24"] = json.loads(Path(result["analysis_path"]).read_text(encoding="utf-8"))
    return copy.deepcopy(_ANALYSIS["SQ24"])


def render(payload: dict, tafs: dict[str, str], path: Path) -> tuple[list[str], dict, Path]:
    for row in payload["flight"]["weather"]:
        if row.get("record_type") == "TAF" and row.get("location") in tafs:
            row["text"] = tafs[row["location"]]
    render_combined_briefing(payload["flight"], payload["findings"], payload.get("view", {}).get("warnings") or [], path,
                             weather_charts=payload.get("weather_charts") or {})
    view = build_briefing_view(payload["flight"], payload["findings"], payload.get("view", {}).get("warnings") or [],
                               payload.get("view", {}).get("timing"), payload.get("weather_charts"),
                               include_dashboard_only_panels=True)
    with fitz.open(path) as document:
        pages = [normalized(page.get_text()) for page in document]
    return pages, view, path


def stated_deferral(weather_page: str, icao: str, record: str) -> int:
    """How many trailing groups the page states it left to the dashboard (0: printed whole)."""
    _, groups = page_one_taf_change_groups(record)
    printed = [drop for drop in range(len(groups) + 1)
               if normalized(f"{icao} TAF: {weather_page_taf_field(record, drop)}") in weather_page]
    assert len(printed) == 1, f"{icao}: exactly one whole-group form of the TAF is on the WEATHER page"
    return printed[0]


def test_the_weather_page_taf_field_keeps_whole_groups_and_states_the_rest() -> None:
    record = fm_taf(3)
    assert weather_page_taf_field(record, 0) == page_one_weather_record(record)
    assert weather_page_taf_field(record, 2) == (
        f"{BASE} FM220100 18113G19KT P6SM VCSH BKN025 OVC040 (+2 further change group(s) on the dashboard)")
    assert weather_page_taf_field(record, 9) == f"{BASE} (+3 further change group(s) on the dashboard)", "the envelope is never cut"
    assert weather_page_taf_field("TAF WSSS 101100Z 1012/1118 VRB05KT 9999 FEW018=", 1) == "TAF WSSS 101100Z 1012/1118 VRB05KT 9999 FEW018="


@pytest.mark.parametrize("label,tafs,expect_whole", [
    ("KJFK 11 FM groups (control: whole, as before)", {"KJFK": fm_taf(11)}, True),
    ("KJFK 12 FM groups", {"KJFK": fm_taf(12)}, False),
    ("KJFK 14 FM groups", {"KJFK": fm_taf(14)}, False),
    ("KJFK 18 FM groups", {"KJFK": fm_taf(18)}, False),
    ("KJFK 32 FM groups", {"KJFK": fm_taf(32)}, False),
    ("KJFK 16 mixed FM/TEMPO/PROB30/BECMG groups", {"KJFK": mixed_taf(16)}, False),
    ("WSSS and KJFK 14 FM groups each", {"KJFK": fm_taf(14), "WSSS": fm_taf(14, "21")}, False),
])
def test_a_long_taf_renders_six_conforming_pages_with_whole_groups_and_a_stated_deferral(label, tafs, expect_whole, tmp_path_factory) -> None:
    payload = sq24(tmp_path_factory)
    path = tmp_path_factory.mktemp("f8-render") / "SQ24_SYNTHETIC.pdf"
    pages, view, path = render(payload, tafs, path)
    assert len(pages) == 6, label
    weather = pages[WEATHER_PAGE]
    deferred_total = 0
    for role in ("departure", "destination"):
        station = view[role]
        record = station["weather"]["taf"]
        drop = stated_deferral(weather, station["icao"], record)
        deferred_total += drop
        if station["icao"] in tafs:
            _, groups = page_one_taf_change_groups(record)
            assert drop < len(groups), "at least one change group is printed"
    assert (deferred_total == 0) is expect_whole, label
    if "KJFK" in tafs:
        assert normalized(TAF_CONTINUATION) in pages[0], "page 1 still points at the WEATHER page"
    assert conformance.check_reference_conformance(
        path, structure=MANIFEST["reference_structure"], contract_extensions=MANIFEST["contract_extensions"])["valid"]
    gate = check_concise_pdf(path, flight=payload["flight"], view=view)
    assert gate["valid"], gate["violations"]


def test_the_gate_refuses_a_page_five_taf_that_is_not_its_stated_prefix(tmp_path_factory) -> None:
    payload = sq24(tmp_path_factory)
    path = tmp_path_factory.mktemp("f8-gate") / "SQ24_SYNTHETIC_12.pdf"
    _, view, path = render(payload, {"KJFK": fm_taf(12)}, path)
    assert check_concise_pdf(path, flight=payload["flight"], view=view)["valid"]
    # The same page judged against a record with one more trailing group: what it prints is no stated form of it.
    tampered = copy.deepcopy(view)
    tampered["destination"]["weather"]["taf"] = fm_taf(13)
    violations = check_concise_pdf(path, flight=payload["flight"], view=tampered)["violations"]
    assert any(entry["code"] == "TERMINAL_TAF_PARITY" for entry in violations), violations
