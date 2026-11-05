"""Open item #9 (VWS ties): a maximum reached at several waypoints is reached at each of them.

David, 30 Sep 2026 23:38 (SIA297 WSSS-NZCH): "check the VWS points pick up.. it seems only Sapda was flagged
out but actually other waypoints also had 4 units as VWS". Jabe, 00:48: "it only listed first waypoint with
highest vws and dropped others that also had 004".

Root cause: every surface reduced the held VWS samples to one maximum with ``max()``, which returns the first
maximal element in route order, and published that single waypoint as "the" maximum. The repair is one shared
selection (``app.odss.vws_maxima.vws_maximum_points``) that returns every waypoint at the maximum, in route order,
and every surface reads it: the governed review (dashboard card, map, coverage row, nine-page panel), the six-page
page-6 card, the corroboration condition, the VWS event findings and the timing events.

Invariant: for any route, the waypoints a surface names at the maximum VWS value are exactly the held waypoints
whose VWS equals that value, in route order. A printed surface with a fixed slot names the first
``VWS_MAXIMUM_PRINT_LIMIT`` and says how many more are held at that value; it never drops one silently.

The genuine ties come from the private corpus (13 of 28 OFPs tie at the route maximum; 7 tie inside an event).
The 30 Sep SIA297 OFP itself is not on this machine; SQ297 16 Aug (same city pair) ties four waypoints at 004.
"""
from __future__ import annotations

import json
from pathlib import Path
import random

import fitz
import pytest

from app.odss.briefing import build_briefing_view
from app.odss.constants import format_actm
from app.odss.engines import analyse, detect_vws_events
from app.odss.parser import extract_pages, parse_lido
from app.odss.timing import build_timing_view
from app.odss.vws_maxima import (
    VWS_MAXIMUM_PRINT_LIMIT,
    held_vws,
    vws_maximum_points,
)


CORPUS = Path(__file__).resolve().parents[2] / "private_cfp_corpus"
MANIFEST = Path(__file__).resolve().parent / "private_cfp_corpus_manifest.json"


def _wp(name: str, vws, actm: int, page: int = 7, **extra) -> dict:
    return {"name": name, "vws": vws, "actm_minutes": actm, "source_page": page, "msa_hundreds_ft": 30, **extra}


def _review(waypoints: list[dict]) -> dict:
    from app.odss.briefing import _vws_review

    return _vws_review(waypoints)


# --------------------------------------------------------------- selection


def test_single_maximum_is_one_point() -> None:
    route = [_wp("A", 1, 10), _wp("B", 3, 20), _wp("C", 2, 30)]
    assert [w["name"] for w in vws_maximum_points(route)] == ["B"]


def test_two_way_tie_returns_both_in_route_order() -> None:
    route = [_wp("A", 1, 10), _wp("SAPDA", 4, 120), _wp("C", 2, 130), _wp("TOPIR", 4, 150)]
    assert [w["name"] for w in vws_maximum_points(route)] == ["SAPDA", "TOPIR"]


def test_many_way_tie_returns_every_point() -> None:
    route = [_wp(f"P{i:02d}", 4 if i % 3 == 0 else 2, i * 10) for i in range(30)]
    expected = [f"P{i:02d}" for i in range(30) if i % 3 == 0]
    assert [w["name"] for w in vws_maximum_points(route)] == expected


def test_tie_at_zero_is_a_held_maximum_not_a_missing_value() -> None:
    route = [_wp("A", 0, 10), _wp("B", None, 20), _wp("C", 0, 30)]
    assert [w["name"] for w in vws_maximum_points(route)] == ["A", "C"]


def test_missing_and_malformed_values_are_never_a_maximum() -> None:
    route = [_wp("NONE", None, 10), _wp("BOOL", True, 20), _wp("NEG", -1, 30), _wp("TEXT", "009", 40),
             _wp("FLOAT", 9.0, 50), _wp("HELD", 2, 60)]
    assert [held_vws(w) for w in route] == [None, None, None, None, None, 2]
    assert [w["name"] for w in vws_maximum_points(route)] == ["HELD"]
    assert vws_maximum_points([_wp("NONE", None, 10)]) == []
    assert vws_maximum_points([]) == []


def test_selection_is_the_complete_argmax_set_for_random_routes() -> None:
    """Compositional proof: the selection equals the brute-force set on 2,000 random routes."""
    rng = random.Random(9)
    for _ in range(2000):
        route = [
            _wp(f"W{i}", rng.choice([None, 0, 1, 2, 3, 4, 4, 5, 5, 6, True, -1]), i)
            for i in range(rng.randint(0, 25))
        ]
        values = [held_vws(w) for w in route]
        top = max((v for v in values if v is not None), default=None)
        expected = [w for w, v in zip(route, values) if v is not None and v == top]
        assert vws_maximum_points(route) == expected


# ------------------------------------------------------------------ events


def test_a_tie_inside_one_event_names_every_maximum() -> None:
    route = [_wp("A", 2, 10), _wp("PUGGY", 5, 20), _wp("POETT", 5, 30), _wp("X", 4, 35), _wp("SELDM", 5, 40),
             _wp("D", 3, 50)]
    route[3]["vws"] = 5
    route[3]["name"] = "MID"
    events = detect_vws_events(route)
    assert len(events) == 1
    assert [w["name"] for w in events[0]["maxima"]] == ["PUGGY", "POETT", "MID", "SELDM"]
    assert events[0]["maximum"] is events[0]["maxima"][0]


def test_ties_across_separate_events_stay_per_event_and_route_wide() -> None:
    route = [_wp("A", 2, 10), _wp("OGANA", 5, 32), _wp("B", 3, 40), _wp("VATLA", 5, 151, page=8), _wp("C", 1, 160)]
    events = detect_vws_events(route)
    assert [[w["name"] for w in e["maxima"]] for e in events] == [["OGANA"], ["VATLA"]]
    review = _review(route)
    assert [p["waypoint"] for p in review["maximum_points"]] == ["OGANA", "VATLA"]
    assert review["maximum_point_count"] == 2


def test_event_finding_detail_names_every_tied_maximum_and_single_stays_byte_identical() -> None:
    flight = {"route_waypoints": [_wp("A", 2, 10), _wp("PUGGY", 5, 628), _wp("POETT", 5, 641), _wp("D", 3, 650)]}
    tied = _vws_findings(flight)
    assert len(tied) == 1
    assert "Maximum at PUGGY, ACTM 10.28; POETT, ACTM 10.41." in tied[0]["details"]
    assert tied[0]["summary"] == "ACTM 10.28-10.50, maximum 005."

    flight["route_waypoints"][2]["vws"] = 4
    single = _vws_findings(flight)
    assert "Maximum at PUGGY, ACTM 10.28." in single[0]["details"]


def _vws_findings(flight: dict) -> list[dict]:
    from app.odss import engines

    findings: list[dict] = []
    for index, event in enumerate(detect_vws_events(flight["route_waypoints"]), start=1):
        findings.append(engines.vws_event_finding(flight, index, event))
    return findings


def test_timing_publishes_a_maximum_event_at_every_tied_point() -> None:
    from app.odss.timing import _vws_timing_events
    from datetime import datetime, timezone

    anchor = datetime(2026, 9, 30, 11, 50, tzinfo=timezone.utc)
    route = [_wp("A", 2, 10), _wp("PUGGY", 5, 628), _wp("POETT", 5, 641), _wp("D", 3, 650)]
    labels = [e["label"] for e in _vws_timing_events(anchor, route)]
    assert "VWS event 1 maximum at PUGGY" in labels
    assert "VWS event 1 maximum at POETT" in labels


# ------------------------------------------------------------------ review


def test_review_publishes_every_tied_point_with_actm_and_page() -> None:
    route = [_wp("A", 1, 10, page=9), _wp("SAPDA", 4, 120, page=10), _wp("C", 2, 125, page=10),
             _wp("TOPIR", 4, 150, page=10)]
    review = _review(route)
    assert review["status"] == "reviewed_no_trigger"
    assert review["maximum"] == 4
    assert review["maximum_point_count"] == 2
    assert review["maximum_points"] == [
        {"waypoint": "SAPDA", "actm_minutes": 120, "actm_display": "02.00", "source_page": 10},
        {"waypoint": "TOPIR", "actm_minutes": 150, "actm_display": "02.30", "source_page": 10},
    ]
    # The legacy single fields carry the first point in route order for older readers.
    assert review["maximum_waypoint"] == "SAPDA"
    assert review["summary"] == (
        "VWS review: no planned >004 trigger in the source-held route values; "
        "maximum 004 at 2 waypoints: SAPDA (ACTM 02.00, OFP p10), TOPIR (ACTM 02.30, OFP p10)."
    )


def test_review_bounds_a_many_way_tie_and_says_how_many_more() -> None:
    route = [_wp(f"P{i}", 4, 10 * i) for i in range(1, 9)]
    review = _review(route)
    assert review["maximum_point_count"] == 8
    assert [p["waypoint"] for p in review["maximum_points"]] == [f"P{i}" for i in range(1, 9)]
    listed = ", ".join(f"P{i} (ACTM {format_actm(10 * i)}, OFP p7)" for i in range(1, VWS_MAXIMUM_PRINT_LIMIT + 1))
    more = 8 - VWS_MAXIMUM_PRINT_LIMIT
    assert review["summary"] == (
        "VWS review: no planned >004 trigger in the source-held route values; "
        f"maximum 004 at 8 waypoints: {listed}; +{more} more at 004 (see dashboard)."
    )


def test_review_tie_at_zero_and_missing_values() -> None:
    review = _review([_wp("A", 0, 10), _wp("B", None, 20), _wp("C", 0, 30)])
    assert review["maximum_display"] == "000"
    assert [p["waypoint"] for p in review["maximum_points"]] == ["A", "C"]
    missing = _review([_wp("A", None, 10)])
    assert missing["status"] == "unavailable"
    assert missing["maximum_points"] == []
    assert missing["maximum_point_count"] == 0


def test_single_maximum_summary_is_byte_identical() -> None:
    review = _review([_wp("CRUISE", 1, 90), _wp("ARRIVAL", 4, 180, page=8)])
    assert review["summary"] == (
        "VWS review: no planned >004 trigger in the source-held route values; "
        "maximum 004 at ARRIVAL (ACTM 03.00, OFP p8)."
    )
    assert review["maximum_points"] == [
        {"waypoint": "ARRIVAL", "actm_minutes": 180, "actm_display": "03.00", "source_page": 8}
    ]


def test_corroboration_condition_names_every_tied_maximum() -> None:
    from app.odss.analysed_briefing_content import vws_corroboration_subject

    review = _review([_wp("SAPDA", 4, 120), _wp("TOPIR", 4, 150)])
    assert vws_corroboration_subject(review) == "VWS 004 at SAPDA and TOPIR"
    single = _review([_wp("SAPDA", 4, 120), _wp("TOPIR", 3, 150)])
    assert vws_corroboration_subject(single) == "VWS 004 at SAPDA"
    many = _review([_wp(f"P{i}", 4, 10 * i) for i in range(1, 9)])
    names = ", ".join(f"P{i}" for i in range(1, VWS_MAXIMUM_PRINT_LIMIT + 1))
    assert vws_corroboration_subject(many) == (
        f"VWS 004 at {names} (+{8 - VWS_MAXIMUM_PRINT_LIMIT} more at 004, see dashboard)"
    )


def test_page_six_sentence_names_every_tied_maximum() -> None:
    from app.odss.operational_format import vws_threshold_sentence

    single = _review([_wp("A", 1, 10), _wp("RAMPY", 4, 99)])
    assert vws_threshold_sentence(single) == (
        "0 event(s) at the analysed >004 threshold. Maximum 004 at RAMPY, ACTM 01.39."
    )
    tied = _review([_wp("RAMPY", 4, 99), _wp("UDONO", 4, 106)])
    assert vws_threshold_sentence(tied) == (
        "0 event(s) at the analysed >004 threshold. Maximum 004 at 2 waypoints: RAMPY, ACTM 01.39; UDONO, ACTM 01.46."
    )
    many = _review([_wp(f"P{i}", 4, 10 * i) for i in range(1, 9)])
    listed = "; ".join(f"P{i}, ACTM {format_actm(10 * i)}" for i in range(1, VWS_MAXIMUM_PRINT_LIMIT + 1))
    assert vws_threshold_sentence(many) == (
        f"0 event(s) at the analysed >004 threshold. Maximum 004 at 8 waypoints: {listed}; "
        f"+{8 - VWS_MAXIMUM_PRINT_LIMIT} more at 004 (see dashboard)."
    )


# ------------------------------------------------------------ genuine corpus


def _corpus_flight(case_id: str) -> dict:
    case = next(c for c in json.loads(MANIFEST.read_text())["cases"] if c["case_id"] == case_id)
    source = CORPUS / case["filename"]
    if not source.is_file():
        pytest.skip(f"private CFP corpus file {case['filename']} is not available")
    return parse_lido(extract_pages(source), source.name)


GENUINE_TIES = {
    # case: (value, [waypoint, actm minutes, OFP page] in route order)
    "SQ297-SIN-CHC": (4, [("RAMPY", 99, 8), ("UDONO", 106, 8), ("BLI", 122, 8), ("AS", 290, 8)]),
    "SQ314-SIN-LGW": (4, [("RINBA", 48, 7), ("ISTEL", 55, 7), ("VPL", 57, 7), ("GIVAL", 70, 7), ("IGREX", 102, 7),
                          ("PPB", 119, 7), ("VATLA", 150, 7), ("URKOK", 170, 7)]),
    "SQ366-SIN-FCO": (6, [("VIH", 42, 8), ("RINBA", 48, 8)]),
    "SQ326-SIN-FRA": (5, [("OGANA", 32, 6), ("BIKDU", 36, 6), ("VIH", 42, 6), ("VATLA", 151, 7)]),
    "SQ482-SIN-JNB": (5, [("TAPIN", 40, 6), ("PIBED", 109, 6)]),
    "SQ910-SIN-MNL": (3, [("UXEDA", 28, 7), ("LAGOT", 87, 7), ("LAXOR", 119, 8), ("LEGED", 161, 8), ("LUBAN", 172, 8)]),
    "SQ194-SIN-HAN": (5, [("ANHOA", 82, 6), ("ANBOV", 87, 6)]),
    "SQ279-SIN-ADL": (3, [("04S07", 52, 6), ("UPTAM", 152, 6), ("CDU", 318, 7)]),
    "SQ214-PER-SIN": (3, [("WOLGO", 35, 6), ("IMABA", 199, 6), ("HLM", 207, 6), ("CKG", 209, 6), ("DOLTA", 218, 6)]),
    "SQ352-SIN-CPH": (5, [("PASVA", 47, 7), ("TAXEB", 56, 7), ("MUDMA", 83, 7)]),
    "SQ365-FCO-SIN": (4, [("SUPIN", 617, 13), ("IKOGA", 625, 13), ("BEKSO", 655, 13)]),
    "SQ606-SIN-ICN-06SEP": (3, [("ALDAS", 112, 11), ("TNN", 225, 11)]),
    "SQ882-SIN-HKG-10SEP": (3, [("DUBSA", 28, 11), ("DAMOG", 32, 11)]),
}


@pytest.mark.parametrize("case_id", sorted(GENUINE_TIES))
def test_genuine_corpus_ties_publish_every_point(case_id: str) -> None:
    value, points = GENUINE_TIES[case_id]
    flight = _corpus_flight(case_id)
    review = build_briefing_view(flight, [], [])["terrain"]["vws_review"]
    assert review["maximum"] == value
    assert [(p["waypoint"], p["actm_minutes"], p["source_page"]) for p in review["maximum_points"]] == points
    assert review["maximum_point_count"] == len(points)
    for name, _, _ in points[:VWS_MAXIMUM_PRINT_LIMIT]:
        assert f" {name} (ACTM" in review["summary"]
    if len(points) > VWS_MAXIMUM_PRINT_LIMIT:
        assert f"+{len(points) - VWS_MAXIMUM_PRINT_LIMIT} more at {value:03d} (see dashboard)" in review["summary"]


GENUINE_EVENT_TIES = {
    "SQ366-SIN-FCO": [["VIH", "RINBA"], ["MINAT"], ["IGREX"], ["VATLA"]],
    "SQ24-SIN-JFK": [["PUGGY", "POETT", "SELDM"], ["GKN"]],
    "SQ326-SIN-FRA": [["OGANA", "BIKDU", "VIH"], ["VATLA"]],
    "SQ194-SIN-HAN": [["ANHOA", "ANBOV"]],
    "SQ352-SIN-CPH": [["PASVA", "TAXEB"], ["MUDMA"]],
    "SQ322-SIN-LHR": [["VATLA", "URKOK"], ["KEGIT"], ["INLOD"]],
    "SQ481-JNB-SIN-25AUG": [["SOBAT"], ["PEDPI", "PANDU"]],
}


@pytest.mark.parametrize("case_id", sorted(GENUINE_EVENT_TIES))
def test_genuine_corpus_event_ties_name_every_maximum(case_id: str) -> None:
    flight = _corpus_flight(case_id)
    events = detect_vws_events(flight["route_waypoints"])
    expected = GENUINE_EVENT_TIES[case_id]
    assert len(events) == len(expected)
    for event, names in zip(events, expected, strict=True):
        assert [str(w["name"]).lstrip("-") for w in event["maxima"]] == names
        top = max(w["vws"] for w in event["maxima"])
        assert all(w["vws"] == top for w in event["maxima"])
    findings = [f for f in analyse(flight)[0] if f.get("engine") == "vws"]
    for finding, event in zip(findings, events):
        for waypoint in event["maxima"]:
            assert f"{waypoint['name']}, ACTM {format_actm(waypoint['actm_minutes'])}" in " ".join(finding["details"])


def test_genuine_sq297_six_page_pdf_prints_every_tied_maximum(tmp_path) -> None:
    """The same city pair David flagged: four waypoints at 004 on the six-page download."""
    from app.analysis import run_odss_analysis
    from app.odss.combined_brief import render_combined_briefing
    from app.odss.concise_pdf_gate import normalized

    case = next(c for c in json.loads(MANIFEST.read_text())["cases"] if c["case_id"] == "SQ297-SIN-CHC")
    source = CORPUS / case["filename"]
    if not source.is_file():
        pytest.skip("private CFP corpus file is not available")
    result = run_odss_analysis(source, tmp_path / "analysis", tmp_path / "reports", 1)
    payload = json.loads(Path(result["analysis_path"]).read_text(encoding="utf-8"))
    path = tmp_path / "SQ297.pdf"
    render_combined_briefing(payload["flight"], payload["findings"], payload.get("view", {}).get("warnings") or [],
                             path, weather_charts=payload.get("weather_charts") or {})
    with fitz.open(path) as document:
        page_six = normalized(document[5].get_text())
    assert normalized(
        "Maximum 004 at 4 waypoints: RAMPY, ACTM 01.39; UDONO, ACTM 01.46; BLI, ACTM 02.02; AS, ACTM 04.50."
    ) in page_six


def test_the_app_parity_oracle_prints_the_same_number_of_tied_points() -> None:
    """The dashboard/PDF parity oracle predicts page 6 with its own copy of the bound; the two must agree."""
    import os
    import re

    from tests.cross_runtime import sibling_app_root

    configured = os.environ.get("PILOTDRIVEN_APP_ROOT")
    app_root = Path(configured) if configured else sibling_app_root(Path(__file__))
    oracle = (app_root / "scripts/lib/briefing-surface-parity.mjs") if app_root else None
    if oracle is None or not oracle.is_file():
        pytest.skip("the PilotDriven app worktree is not available")
    declared = re.search(r"export const VWS_MAXIMUM_PRINT_LIMIT = (\d+)", oracle.read_text(encoding="utf-8"))
    assert declared, "the parity oracle must declare the printed tie bound"
    assert int(declared.group(1)) == VWS_MAXIMUM_PRINT_LIMIT


def test_a_fixed_panel_names_fewer_tied_points_but_always_counts_the_rest() -> None:
    """The audit composition's TERRAIN / VWS panel has a line budget: it takes the published sentence when it
    fits, otherwise the same sentence naming fewer points with '+K more' - never a silent cut."""
    from app.odss.combined_brief import _operational_terrain_status_lines
    from app.odss.vws_maxima import vws_review_summary_variants

    review = _review([_wp("ENITA", 3, 41), _wp("LOVV", 3, 53), _wp("UTAV", 3, 307), _wp("VOMF", 3, 580)])
    variants = vws_review_summary_variants(review)
    assert variants[0] == review["summary"]
    assert [v.count("(ACTM") for v in variants] == [4, 3, 2, 1]
    assert "more at" not in variants[0]
    assert [v.endswith(f"+{4 - n} more at 003 (see dashboard).") for n, v in zip([3, 2, 1], variants[1:])] == [True] * 3
    # Single maximum: one variant, the published sentence.
    assert vws_review_summary_variants(_review([_wp("A", 3, 41), _wp("B", 2, 53)])) == [
        "VWS review: no planned >004 trigger in the source-held route values; maximum 003 at A (ACTM 00.41, OFP p7)."
    ]
    assert len(_operational_terrain_status_lines("", variants, text_width=2000.0, max_lines=3)[0]) == len(variants[0])
    lines = _operational_terrain_status_lines("", variants, text_width=260.0, max_lines=3)
    printed = " ".join(lines)
    assert "ENITA" in printed and "more at 003 (see dashboard)" in printed and "VOMF" not in printed
    with pytest.raises(ValueError):
        _operational_terrain_status_lines("", variants, text_width=60.0, max_lines=1)


def test_genuine_sq314_audit_composition_never_cuts_the_tied_listing(tmp_path) -> None:
    """SQ314 SIN-LGW ties eight waypoints at 004. The audit composition's one-line VWS review printed
    '... +4 more a…' (an ellipsis cut); it now takes a variant that fits and still counts every point."""
    from app.analysis import run_odss_analysis
    from app.odss.combined_brief import render_combined_briefing

    case = next(c for c in json.loads(MANIFEST.read_text())["cases"] if c["case_id"] == "SQ314-SIN-LGW")
    source = CORPUS / case["filename"]
    if not source.is_file():
        pytest.skip("private CFP corpus file is not available")
    result = run_odss_analysis(source, tmp_path / "analysis", tmp_path / "reports", 1)
    payload = json.loads(Path(result["analysis_path"]).read_text(encoding="utf-8"))
    path = tmp_path / "SQ314-audit.pdf"
    render_combined_briefing(payload["flight"], payload["findings"], payload.get("view", {}).get("warnings") or [],
                             path, weather_charts=payload.get("weather_charts") or {}, include_audit_appendix=True)
    with fitz.open(path) as document:
        lines = [line for page in document for line in page.get_text().splitlines() if "VWS review:" in line]
    assert lines, "the audit composition prints the VWS review"
    for line in lines:
        assert not line.rstrip().endswith("…"), line
    assert any("more at 004 (see dashboard)" in line and "8 waypoints" in line for line in lines)
