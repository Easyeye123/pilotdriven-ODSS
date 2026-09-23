"""David, 23 Sep 2026 - the ODSS side of T1, T2 and T3.

output/pd-boss-feedback-review-20260923/FIX-LIST.md, authorised for
implementation on 24 Sep ("then tell claude to fix it duhhh"):

  08:15  "Can you increase the number of pages limit for upload?" - the
         upload clip ends on the 180-page rejection of
         lido-briefing_SQ_312_22Sep2026_SIN_LGW.pdf.                    (T1)
  20:22  "You need to give the full METAR / TAF for WSSS and EGKK."     (T2)
  20:23  "What's this for? Do NOT decipher. Your user is a pilot. Not a
         lay person." - the decoded DEST TAF sentence.                  (T3)

The boss's 22 Sep SQ312 file is not held in this checkout. The corpus flight
on his route, SQ314 SIN-LGW of 15 Aug 2026, is the control for the page-1
fields and the WEATHER page; the long-input controls are labelled synthetic
composites of its genuine pages, measured in the round's evidence folder.
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone
import json
import os
from pathlib import Path

import fitz
import pytest

from app.analysis import run_odss_analysis
from app.odss import reference_conformance as conformance
from app.odss.briefing import _overview_forecast_at_reference
from app.odss.combined_brief import render_combined_briefing
from app.odss.concise_pdf_gate import WEATHER_PAGE, normalized
from app.odss.page_one_weather import (
    PAGE1_WEATHER_FIELD_RULE,
    TAF_CONTINUATION,
    page_one_metar_field,
    page_one_taf_change_groups,
    page_one_taf_field,
    page_one_taf_field_continued,
    page_one_weather_record,
)
from app.odss.parser import MAX_PDF_PAGES, extract_pages, validate_pdf
from app.odss.weather_timing import summarize_metar_for_window, summarize_taf_for_window
from app.odss.analysed_briefing_map import MAP_FOOTER_LADDER, MAP_PLOT_MIN_HEIGHT, map_footer_layout, map_footer_line_limit


ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT.parent / "private_cfp_corpus"
MANIFEST_PATH = ROOT / "tests" / "boss_reference_format_manifest.json"
SQ314 = "lido-briefing_SQ_314_15Aug2026_SIN_LGW.pdf"

EGKK_METAR = "SA  161120 19003KT 120V290 9999 SCT038 24/14 Q1018="
EGKK_TAF = (
    "FT  160700 1607/1712 VRB03KT 9999 BKN008 BECMG 1607/1609 BKN030 "
    "BECMG 1612/1615 23010KT BECMG 1617/1620 VRB03KT="
)
WSSS_METAR = "SA  161130 19005KT 9999 FEW015 FEW017CB SCT018TCU 29/24 Q1011 TEMPO FM1145 TL1245 2500 +TSRA="
WSSS_TAF = "FT  151700 1518/1700 16008KT 9999 FEW015 SCT020 TEMPO 1606/1609 3000 TSRA FEW012CB BKN015="


# ---------------------------------------------------------------- T1


def _blank_pdf(path: Path, pages: int) -> Path:
    document = fitz.open()
    for _ in range(pages):
        document.new_page()
    document.save(path)
    document.close()
    return path


def test_t1_the_page_ceiling_is_400_and_both_parser_entry_points_enforce_it(tmp_path):
    """12 MB at the thinnest held LIDO density (38.5 KB/page) is ~327 pages;
    400 leaves the byte cap as the binding limit for every genuine OFP while
    still bounding a pathological low-density file. Measured cost at 400
    pages: output/pd-boss-fixes-20260922/residual3-20260923/r13-page-limit/."""
    assert MAX_PDF_PAGES == 400
    accepted = _blank_pdf(tmp_path / "400.pdf", 400)
    validate_pdf(accepted)
    assert len(extract_pages(accepted)) == 400
    rejected = _blank_pdf(tmp_path / "401.pdf", 401)
    with pytest.raises(ValueError, match="exceeds the 400-page OFP limit"):
        validate_pdf(rejected)
    with pytest.raises(ValueError, match="exceeds the 400-page OFP limit"):
        extract_pages(rejected)


def test_t1_the_app_states_the_same_ceiling():
    """One number on both sides of the upload path, or the pilot sees two."""
    app_root = os.environ.get("PILOTDRIVEN_APP_ROOT")
    if not app_root or not (Path(app_root) / "cfp-limits.mjs").is_file():
        pytest.skip("PILOTDRIVEN_APP_ROOT does not point at the app checkout")
    contract = (Path(app_root) / "cfp-limits.mjs").read_text(encoding="utf-8")
    assert f"MAX_CFP_PAGES = {MAX_PDF_PAGES};" in contract


# ---------------------------------------------------------------- T2


def test_t2_the_page_one_field_is_the_full_original_coded_record():
    assert PAGE1_WEATHER_FIELD_RULE == "page1-weather-record-v3"
    assert page_one_weather_record(EGKK_METAR) == "SA 161120 19003KT 120V290 9999 SCT038 24/14 Q1018="
    assert page_one_metar_field(EGKK_METAR, "WEATHER page") == "SA 161120 19003KT 120V290 9999 SCT038 24/14 Q1018="
    assert page_one_taf_field(EGKK_TAF, "WEATHER page") == (
        "FT 160700 1607/1712 VRB03KT 9999 BKN008 BECMG 1607/1609 BKN030 "
        "BECMG 1612/1615 23010KT BECMG 1617/1620 VRB03KT="
    )
    # Nothing is rewritten: no cloud-layer joining, no envelope stripping.
    assert page_one_metar_field(WSSS_METAR, "WEATHER page") == (
        "SA 161130 19005KT 9999 FEW015 FEW017CB SCT018TCU 29/24 Q1011 TEMPO FM1145 TL1245 2500 +TSRA="
    )
    assert page_one_taf_field(WSSS_TAF, "WEATHER page") == (
        "FT 151700 1518/1700 16008KT 9999 FEW015 SCT020 TEMPO 1606/1609 3000 TSRA FEW012CB BKN015="
    )
    assert page_one_metar_field({"text": EGKK_METAR}, "WEATHER page") == "SA 161120 19003KT 120V290 9999 SCT038 24/14 Q1018="
    assert page_one_metar_field("", "WEATHER page") == "Not held"
    assert page_one_taf_field(None, "WEATHER page") == "Not held"


_RENDERED: dict[str, dict] = {}


def rendered_sq314(tmp_path_factory) -> dict:
    """The real analysis of the corpus flight on his route, published through
    the exact Download PDF call."""
    if "SQ314" in _RENDERED:
        return _RENDERED["SQ314"]
    source = CORPUS / SQ314
    if not source.is_file():
        pytest.skip(f"private CFP corpus file {SQ314} is not available")
    root = tmp_path_factory.mktemp("boss-round-20260923-sq314")
    result = run_odss_analysis(source, root / "analysis", root / "reports", 1)
    payload = json.loads(Path(result["analysis_path"]).read_text(encoding="utf-8"))
    path = root / "SQ314_Flight_Briefing.pdf"
    render_combined_briefing(
        payload["flight"], payload["findings"], payload.get("view", {}).get("warnings") or [], path,
        source_pdf_path=str(source), weather_charts=payload.get("weather_charts") or {},
    )
    with fitz.open(path) as document:
        pages = [page.get_text() for page in document]
        spans = conformance.page_spans(document[0])
    _RENDERED["SQ314"] = {"payload": payload, "path": path, "pages": pages, "folded": [normalized(p) for p in pages], "spans": spans}
    return _RENDERED["SQ314"]


@pytest.fixture(scope="session")
def sq314(tmp_path_factory):
    return rendered_sq314(tmp_path_factory)


def test_t2_page_one_prints_the_full_metar_and_taf_for_wsss_and_egkk_under_a_taf_label(sq314):
    page = sq314["folded"][0]
    view = sq314["payload"]["view"]["briefing"]
    assert view["departure"]["icao"] == "WSSS" and view["destination"]["icao"] == "EGKK"
    for role in ("departure", "destination"):
        weather = view[role]["weather"]
        assert normalized(page_one_weather_record(weather["metar"])) in page, f"{role} METAR in full"
        assert normalized(page_one_weather_record(weather["taf"])) in page, f"{role} TAF in full"
    assert normalized(EGKK_TAF) in page
    assert normalized(WSSS_TAF) in page
    assert normalized("TAF TEMPO") not in page
    assert normalized("No TEMPO group") not in page
    assert normalized("WEATHER page") not in page.replace(normalized("WEATHER PAGE"), "", 0)
    labels = sorted(span.x0 for span in sq314["spans"] if span.folded == "TAF" and span.bold)
    assert len(labels) == 2, "one TAF label per station column"
    assert labels[0] < labels[1]


def test_t2_the_taf_label_is_a_declared_deviation_from_his_reference_not_a_silent_one(sq314):
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    overrides = manifest["contract_extensions"]["overview_column_field_overrides"]
    assert overrides == {"destination": {"TAF TEMPO": "TAF"}}
    why = manifest["contract_extensions"]["_why"]["overview_column_field_overrides"]
    assert "23 Sep 2026" in why and "full" in why.lower()
    # His reference still reads TAF TEMPO: the manifest is his file, unedited.
    assert manifest["reference_structure"]["overview"]["column_fields"]["destination"] == [
        "PLAN", "EET / SCHED", "METAR", "TAF TEMPO", "PERTINENT"]
    declared = conformance.check_reference_conformance(
        sq314["path"], structure=manifest["reference_structure"],
        contract_extensions=manifest["contract_extensions"])
    assert declared["valid"], declared["violations"]
    undeclared = copy.deepcopy(manifest)
    del undeclared["contract_extensions"]["overview_column_field_overrides"]
    silent = conformance.check_reference_conformance(
        sq314["path"], structure=undeclared["reference_structure"],
        contract_extensions=undeclared["contract_extensions"])
    assert not silent["valid"]
    assert "OVERVIEW_COLUMN_FIELDS" in [v["code"] for v in silent["violations"]]


# ---------------------------------------------------------------- T3


def test_t3_the_taf_window_summary_carries_the_coded_groups_it_decoded():
    start = datetime(2026, 8, 16, 8, 0, tzinfo=timezone.utc)
    end = datetime(2026, 8, 16, 10, 0, tzinfo=timezone.utc)
    summary = summarize_taf_for_window(EGKK_TAF, start, end)
    assert summary["status"] == "pertinent"
    assert summary["applicable_groups"] == ["VRB03KT 9999 BKN008", "BECMG 1607/1609 BKN030"]
    # A window the TAF does not cover still names the groups it did overlap.
    incomplete = summarize_taf_for_window("FT 241700 2418/2518 16009KT 9999 FEW015 SCT020=",
                                          datetime(2026, 7, 25, 20, 30, tzinfo=timezone.utc),
                                          datetime(2026, 7, 25, 22, 30, tzinfo=timezone.utc))
    assert incomplete["status"] == "review_required"
    assert incomplete["applicable_groups"] == []
    observation = summarize_metar_for_window(EGKK_METAR, datetime(2026, 8, 16, 10, 0, tzinfo=timezone.utc),
                                             datetime(2026, 8, 16, 12, 0, tzinfo=timezone.utc),
                                             observed_at=datetime(2026, 8, 16, 11, 20, tzinfo=timezone.utc))
    assert observation["applicable_groups"] == ["SA 161120 19003KT 120V290 9999 SCT038 24/14 Q1018="]


def test_t3_the_overview_forecast_publishes_the_coded_groups_beside_the_decoding():
    findings = [{
        "engine": "weather",
        "data": {
            "location": "EGKK", "phase": "Destination", "record_types": ["TAF"],
            "applicable_conditions": "wind variable 3 kt; visibility 10 km or more; broken 800 ft",
            "applicable_groups": ["VRB03KT 9999 BKN008", "BECMG 1607/1609 BKN030"],
            "utc_window": "16 AUG 0800Z-1000Z", "timing": "t", "window_status": "pertinent",
        },
    }]
    forecast = _overview_forecast_at_reference(findings, location="EGKK", phase="Destination")
    assert forecast["applicable_groups"] == ["VRB03KT 9999 BKN008", "BECMG 1607/1609 BKN030"]


def test_t3_the_weather_page_prints_the_coded_groups_not_their_decoding(sq314):
    weather = " ".join(sq314["pages"][WEATHER_PAGE].split())
    forecast = sq314["payload"]["view"]["briefing"]["overview"]["destination"]["forecast_at_reference"]
    assert forecast["applicable_groups"] == ["VRB03KT 9999 BKN008", "BECMG 1607/1609 BKN030"]
    assert "EGKK forecast 16 AUG 0800Z-1000Z: VRB03KT 9999 BKN008 BECMG 1607/1609 BKN030" in weather
    for decoded in ("wind variable", "visibility 10 km", "broken 800 ft", "low cloud / ceiling", "wind 160°"):
        assert decoded not in weather, decoded
    # The full records are still on the page, as they were.
    assert "EGKK METAR: SA 161120 19003KT 120V290 9999 SCT038 24/14 Q1018=" in weather


# ---------------------------------------------------------------- R2 (B)


def reference_dir() -> Path | None:
    override = os.environ.get("PILOTDRIVEN_BOSS_REFERENCE_DIR")
    candidates = [Path(override)] if override else []
    candidates.extend(parent / "output" / "pd-boss-09sep-review" / "reference" for parent in ROOT.parents[1:4])
    for candidate in candidates:
        if (candidate / "SQ910_21AUG2026_Flight_Briefing.pdf").is_file():
            return candidate
    return None


def _string_leaves(node):
    if isinstance(node, dict):
        for value in node.values():
            yield from _string_leaves(value)
    elif isinstance(node, list):
        for value in node:
            yield from _string_leaves(value)
    elif isinstance(node, str):
        yield node


def test_r2_every_retained_david_format_label_with_a_review_word_is_in_his_own_reference_pdf():
    """The R2 audit excuses David's format labels (SEVERITY REVIEW, WEATHER
    SOURCE REVIEW, TWO-PASS REVIEW TARGET). That exception is only as good as
    the claim that they are his: verified here against his file, not ours."""
    directory = reference_dir()
    if directory is None:
        pytest.skip("David's reference briefings are not available in this checkout")
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    labels = {leaf for leaf in _string_leaves(manifest["reference_structure"])
              if any(word in leaf.upper() for word in ("REVIEW", "CONFIRM", "VERIF", "CHECK"))}
    assert labels, "the manifest pins at least one such label"
    with fitz.open(directory / "SQ910_21AUG2026_Flight_Briefing.pdf") as document:
        reference = normalized(" ".join(page.get_text() for page in document))
    for label in sorted(labels):
        assert normalized(label) in reference, f"{label!r} is not in David's reference briefing"


# ---------------------------------------------------------------- page-1 fit


def test_t2_a_taller_page_one_row_lets_the_route_map_footer_wrap_below_the_plot():
    """SQ214 PER-SIN (19 Aug): with the full 244-character departure TAF on
    page 1 the station cards take the widest grid, the map narrows and its
    footer wraps to a fifth line. The old flat four-line limit failed the
    render closed; the limit now follows the map's own height, keeping at
    least MAP_PLOT_MIN_HEIGHT for the route itself."""
    assert MAP_PLOT_MIN_HEIGHT == 140.0
    assert map_footer_line_limit(180) == 4      # never below the old limit
    assert map_footer_line_limit(212) == 6      # (212 - 140 - 4) // 11
    assert map_footer_line_limit(300) == 14
    # The SQ214 geometry itself: 198 pt wide, 212 pt tall, a seven-waypoint
    # level profile. Six lines at 9 pt fit above a 140 pt plot.
    route = {"level_profile": "PER FL370 / ESDEG FL380 / WOLGO FL400 / PADRY FL380 / SOPAT FL400 / SAPDA FL380 / IPKON FL400"}
    size, leading, lines = map_footer_layout(route, 197.9, 212.1)
    assert (size, leading) == (9.0, 11.0) and len(lines) == 6
    assert " ".join(lines).endswith("IPKON FL400"), "the profile is printed whole, never cut"
    # A map with room keeps its published 9 pt footer.
    size, leading, lines = map_footer_layout({"level_profile": "SIN FL340 / DUKUN FL380"}, 320.0, 212.1)
    assert (size, leading) == (9.0, 11.0) and len(lines) <= 4
    assert MAP_FOOTER_LADDER[0] == (9.0, 11.0) and MAP_FOOTER_LADDER[-1] == (8.0, 10.0)
    # Beyond the ladder the render still fails closed rather than cutting text.
    with pytest.raises(ValueError, match="Route map footer exceeds readable capacity"):
        map_footer_layout({"level_profile": " / ".join(f"WPT{i:02d} FL{300 + i}" for i in range(40))}, 150.0, 190.0)


# ---------------------------------------------------------------- page-1 continuation


KJFK_TAF = ("FT 212321 2200/2306 18012G18KT 6SM -TSRA BKN025 OVC050CB FM220100 19013G19KT P6SM VCSH BKN025 OVC040 "
            "FM220400 20013KT P6SM BKN025 BKN250 FM221200 24012KT P6SM SCT250=")


def test_t2_a_taf_page_one_cannot_hold_is_deferred_by_whole_groups_behind_an_explicit_marker():
    base, groups = page_one_taf_change_groups(KJFK_TAF)
    assert base == "FT 212321 2200/2306 18012G18KT 6SM -TSRA BKN025 OVC050CB"
    assert groups == ["FM220100 19013G19KT P6SM VCSH BKN025 OVC040", "FM220400 20013KT P6SM BKN025 BKN250", "FM221200 24012KT P6SM SCT250="]
    assert page_one_taf_field_continued(KJFK_TAF, 0) == page_one_taf_field(KJFK_TAF)
    assert page_one_taf_field_continued(KJFK_TAF, 1) == (
        "FT 212321 2200/2306 18012G18KT 6SM -TSRA BKN025 OVC050CB FM220100 19013G19KT P6SM VCSH BKN025 OVC040 "
        "FM220400 20013KT P6SM BKN025 BKN250 (cont. WEATHER page)")
    assert page_one_taf_field_continued(KJFK_TAF, 3) == "FT 212321 2200/2306 18012G18KT 6SM -TSRA BKN025 OVC050CB (cont. WEATHER page)"
    # Never into the base period: more than the record holds is clamped.
    assert page_one_taf_field_continued(KJFK_TAF, 9) == page_one_taf_field_continued(KJFK_TAF, 3)
    # A record with no change group has nothing to defer and prints whole.
    assert page_one_taf_field_continued("FT 160501 1606/1712 03008KT CAVOK=", 2) == "FT 160501 1606/1712 03008KT CAVOK="
    assert page_one_taf_field_continued("", 1) == "Not held"
    assert TAF_CONTINUATION == "(cont. WEATHER page)"
    # PROB30 TEMPO is one group; INTER (Australian) is a group marker.
    base, groups = page_one_taf_change_groups("FT 010500 0106/0212 12008KT 9999 SCT020 BECMG 0110/0112 18010KT PROB30 TEMPO 0114/0118 4000 TSRA BKN012CB INTER 0200/0204 3000 SHRA=")
    assert groups == ["BECMG 0110/0112 18010KT", "PROB30 TEMPO 0114/0118 4000 TSRA BKN012CB", "INTER 0200/0204 3000 SHRA="]


def rendered_case(key: str, filename: str, tmp_path_factory) -> dict:
    if key in _RENDERED:
        return _RENDERED[key]
    source = CORPUS / filename
    if not source.is_file():
        pytest.skip(f"private CFP corpus file {filename} is not available")
    root = tmp_path_factory.mktemp(f"boss-round-20260923-{key}")
    result = run_odss_analysis(source, root / "analysis", root / "reports", 1)
    payload = json.loads(Path(result["analysis_path"]).read_text(encoding="utf-8"))
    path = root / f"{key}_Flight_Briefing.pdf"
    render_combined_briefing(
        payload["flight"], payload["findings"], payload.get("view", {}).get("warnings") or [], path,
        source_pdf_path=str(source), weather_charts=payload.get("weather_charts") or {},
    )
    with fitz.open(path) as document:
        pages = [page.get_text() for page in document]
    _RENDERED[key] = {"payload": payload, "path": path, "pages": pages, "folded": [normalized(p) for p in pages]}
    return _RENDERED[key]


def test_t2_sq24_the_longest_corpus_taf_is_whole_on_page_one_or_explicitly_deferred(tmp_path_factory):
    """SQ24 SIN-JFK (15 Aug corpus) holds the longest destination TAF in the
    corpus (326 characters). Page 1 prints it whole when a grid and type size
    can hold it; otherwise the largest whole-group prefix with the marker.
    Either way nothing is cut inside a group and the WEATHER page prints both
    records whole."""
    case = rendered_case("SQ24", "lido-briefing_SQ_24_15Aug2026_SIN_JFK.pdf", tmp_path_factory)
    view = case["payload"]["view"]["briefing"]
    taf = view["destination"]["weather"]["taf"]
    page_one, weather = case["folded"][0], case["folded"][WEATHER_PAGE]
    whole = normalized(page_one_weather_record(taf)) in page_one
    _, groups = page_one_taf_change_groups(taf)
    deferred = [drop for drop in range(1, len(groups) + 1) if normalized(page_one_taf_field_continued(taf, drop)) in page_one]
    assert whole or deferred, "the whole TAF, or a whole-group prefix carrying the marker"
    assert whole == (normalized(TAF_CONTINUATION) not in page_one), "the marker appears exactly when the record was deferred"
    assert normalized(f"KJFK TAF: {page_one_weather_record(taf)}") in weather, "the WEATHER page holds the whole TAF"
    assert normalized(f"KJFK METAR: {page_one_weather_record(view['destination']['weather']['metar'])}") in weather
    assert normalized(page_one_weather_record(view["departure"]["weather"]["taf"])) in page_one, "the departure TAF fits whole"


def test_t2_a_taf_no_page_one_layout_can_hold_is_deferred_by_whole_groups_never_cut(tmp_path_factory):
    """LABELLED SYNTHETIC OVERFLOW CONTROL: the SQ24 analysis with its KJFK TAF
    extended to fourteen FM groups (~700 characters), which no page-1 grid or
    type size can hold. The render still succeeds; page 1 prints the largest
    whole-group prefix and the marker; the WEATHER page prints the whole
    record; the dashboard analysis is untouched (this is a render-time rule)."""
    import copy
    case = rendered_case("SQ24", "lido-briefing_SQ_24_15Aug2026_SIN_JFK.pdf", tmp_path_factory)
    payload = copy.deepcopy(case["payload"])
    records = [row for row in payload["flight"]["weather"] if row.get("location") == "KJFK" and row.get("record_type") == "TAF"]
    assert records, "the SQ24 analysis holds the KJFK TAF record"
    long_taf = ("FT 212321 2200/2306 18012G18KT 6SM -TSRA BKN025 OVC050CB "
                + " ".join(f"FM22{hour:02d}00 {180 + hour:03d}13G19KT P6SM VCSH BKN025 OVC040" for hour in range(1, 15)) + "=")
    for row in records:
        row["text"] = long_taf
    root = tmp_path_factory.mktemp("boss-round-20260923-sq24-overflow")
    path = root / "SQ24_overflow_Flight_Briefing.pdf"
    render_combined_briefing(payload["flight"], payload["findings"], payload.get("view", {}).get("warnings") or [], path,
                             weather_charts=payload.get("weather_charts") or {})
    with fitz.open(path) as document:
        pages = [normalized(page.get_text()) for page in document]
    page_one, weather = pages[0], pages[WEATHER_PAGE]
    assert normalized(TAF_CONTINUATION) in page_one
    _, groups = page_one_taf_change_groups(long_taf)
    deferred = [drop for drop in range(1, len(groups) + 1) if normalized(page_one_taf_field_continued(long_taf, drop)) in page_one]
    assert deferred, "the printed prefix ends at a group boundary and carries the marker"
    assert min(deferred) >= 1 and normalized(page_one_weather_record(long_taf)) not in page_one
    assert normalized(f"KJFK TAF: {page_one_weather_record(long_taf)}") in weather, "the whole record is on the WEATHER page"


def test_t2_sq214_prints_both_tafs_whole_on_page_one(tmp_path_factory):
    """SQ214 PER-SIN (19 Aug): the 244-character departure TAF fits whole once
    the route-map footer may take its lines above a 140 pt plot."""
    case = rendered_case("SQ214", "SQ21419082026PER.pdf", tmp_path_factory)
    view = case["payload"]["view"]["briefing"]
    page_one = case["folded"][0]
    for role in ("departure", "destination"):
        assert normalized(page_one_weather_record(view[role]["weather"]["taf"])) in page_one, role
    assert normalized(TAF_CONTINUATION) not in page_one
