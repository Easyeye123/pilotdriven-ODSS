"""Page 1's PERTINENT field: one statement, decided once, printed by both surfaces.

Independent signed-in QA of release 394: the dashboard station cards and page 1
of the downloaded PDF put different numbers under the same words. SQ303
EBBR/WSSS read 10/9 "analysed surface/approach consequence(s)" on the
dashboard and 2/2 on page 1; SQ352 WSSS/EKCH read 11/6 against 2/1. The count
is now decided once by the analysis and both surfaces print it.

The first statement named the analysis's full consequence sentences while they
fitted four lines, and three of the four reviewed stations named nothing: SQ352
EKCH lost its planned-runway "RWY 22L CAT II/III operations" restriction, which
the release-394 card had named (independent candidate review, 22 Sep 2026).
Page 1 now names restrictions in their short form, most relevant first - the
airport, the planned runway (including a held notice on it that could not be
reduced), other runways, other approach aids, taxiways - the first two always.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import fitz
import pytest

from app.analysis import run_odss_analysis
from app.odss.combined_brief import COMBINED_BRIEFING_SCHEMA_VERSION, render_combined_briefing
from app.odss.flight_briefing_publication import current_rules_briefing
from app.odss.operational_format import page_one_pertinent, page_one_pertinent_lines

CORPUS = Path("/Users/jabe/Documents/ezzo/pilotdriven-ODSS/private_cfp_corpus")
POINTER = "Full analysis: AIRPORTS page."

# SQ352 15 Aug 2026 destination EKCH, planned RWY 22L: the analysis's own lines
# and unreduced notices, as it publishes them for the real OFP.
EKCH_CLOSURE = {"text": "RWY 12/30 closed for take-off and landing at arrival 16 AUG 0510Z; this does not close "
                        "planned RWY 22L; other notices still apply. (A1380/26)",
                "brief": "RWY 12/30 closed for take-off and landing (not planned RWY 22L).",
                "relevance": 2, "notam_ids": ["A1380/26"]}
EKCH_CATEGORY = {"text": "RWY 22L CAT II/III operations not available at arrival 16 AUG 0510Z; this concerns "
                         "planned RWY 22L. (A1312/26)",
                 "brief": "RWY 22L CAT II/III operations not available (planned runway).",
                 "relevance": 1, "notam_ids": ["A1312/26"]}
EKCH_UNRESOLVED = ["SX1/26", "A1353/26", "A1410/26", "A1383/26"]
EKCH_ON_PLANNED = [{"notam_id": "A1353/26", "runways": ["04R/22L"], "reason": "effect", "names_planned": True}]


def analysed(lines, unresolved=(), detail=(), role="destination", icao="EKCH", planned="22L"):
    return {"role": role, "icao": icao, "planned_runway": planned, "lines": list(lines),
            "unresolved_ids": list(unresolved), "unresolved_detail": list(detail)}


def test_the_planned_runway_is_named_first_and_always():
    field = page_one_pertinent(analysed([EKCH_CLOSURE, EKCH_CATEGORY], EKCH_UNRESOLVED, EKCH_ON_PLANNED))
    assert field["named_lines"] == [
        "RWY 22L CAT II/III operations not available (planned runway).",
        "Planned RWY 22L: 1 held notice unresolved (effect).",
        "RWY 12/30 closed for take-off and landing (not planned RWY 22L).",
    ]
    assert (field["analysed_count"], field["unresolved_count"]) == (2, 4)
    assert [item["notam_ids"] for item in field["items"]] == [["A1312/26"], ["A1353/26"], ["A1380/26"]]
    assert all(item["named"] for item in field["items"])


def test_a_lesser_restriction_is_never_named_in_place_of_one_that_did_not_fit():
    long_runway = {"text": "x (A1/26)", "brief": "RWY 12/30 " + "closed for works on every part of it " * 6 + ".",
                   "relevance": 2, "notam_ids": ["A1/26"]}
    taxi = {"text": "y (A2/26)", "brief": "Taxi access constrained: W1.", "relevance": 4, "notam_ids": ["A2/26"]}
    field = page_one_pertinent(analysed([taxi, long_runway]))
    assert field["named_lines"] == []
    assert [item["named"] for item in field["items"]] == [False, False]


def test_what_was_and_was_not_reduced_is_stated_beside_the_names():
    field = page_one_pertinent(analysed([EKCH_CLOSURE, EKCH_CATEGORY], EKCH_UNRESOLVED, EKCH_ON_PLANNED))
    assert page_one_pertinent_lines(field, POINTER)[-1] == (
        "2 analysed surface/approach consequence(s); 4 pertinent held notice(s) not reduced. "
        "Full analysis: AIRPORTS page.")
    only_held = page_one_pertinent(analysed([], ["A1312/26"], [
        {"notam_id": "A1312/26", "runways": ["22L"], "reason": "timing", "names_planned": True}]))
    assert page_one_pertinent_lines(only_held, POINTER) == [
        "Planned RWY 22L: 1 held notice unresolved (timing at arrival).",
        "0 analysed surface/approach consequence(s); 1 pertinent held notice(s) not reduced. Full analysis: AIRPORTS page.",
    ]


def test_nothing_reduced_and_nothing_held_are_still_different_statements():
    unresolved_only = page_one_pertinent(analysed([], ["SX1/26", "A1410/26"]))
    assert page_one_pertinent_lines(unresolved_only, POINTER) == [
        "0 analysed surface/approach consequence(s); 2 pertinent held notice(s) not reduced. Full analysis: AIRPORTS page.",
    ]
    quiet = page_one_pertinent(analysed([]))
    assert page_one_pertinent_lines(quiet, POINTER) == [
        "No analysed constraint is held for the planned movement.",
        "0 analysed surface/approach consequence(s). Full analysis: AIRPORTS page.",
    ]


# Real flights through the real download path: the view publishes the field,
# and page 1 prints exactly it. The expected numbers for SQ303 and SQ352 are the
# ones independent QA read off the live dashboards' count of consequences and
# held notices, now stated on both surfaces.
REAL = {
    "SQ303": ("SQ30316072026BRU 81.pdf", {
        "departure": ((2, 5), ["RWY 25R ILS; RWY 07L VOR unavailable (not planned RWY 07R).",
                               "Taxi access constrained: W1; Y."]),
        "destination": ((2, 1), ["Planned RWY 20R: 1 held notice unresolved (timing at arrival).",
                                 "RWY 02R/20L not available for civil use (not planned RWY 20R).",
                                 "Taxi access constrained by 7 notice(s)."]),
    }),
    "SQ352": ("lido-briefing_SQ_352_15Aug2026_SIN_CPH.pdf", {
        "departure": ((2, 3), ["Planned RWY 20C: 2 held notices unresolved (timing at departure, effect).",
                               "RWY 02R/20L not available for civil use (not planned RWY 20C)."]),
        "destination": ((2, 4), ["RWY 22L CAT II/III operations not available (planned runway).",
                                 "Planned RWY 22L: 1 held notice unresolved (effect).",
                                 "RWY 12/30 closed for take-off and landing (not planned RWY 22L)."]),
    }),
    "SQ606": ("SQ60606092026SIN.pdf", None),
    "SQ605": ("SQ60508092026ICN.pdf", None),
}
_RENDERED: dict[str, dict] = {}


def _rendered(key, tmp_path_factory):
    if key in _RENDERED:
        return _RENDERED[key]
    source = CORPUS / REAL[key][0]
    if not source.is_file():
        pytest.skip(f"private CFP corpus file {source.name} is not available")
    root = tmp_path_factory.mktemp(f"page-one-{key}")
    result = run_odss_analysis(source, root / "analysis", root / "reports", 1)
    payload = json.loads(Path(result["analysis_path"]).read_text(encoding="utf-8"))
    path = root / f"{key}.pdf"
    render_combined_briefing(payload["flight"], payload["findings"], payload.get("view", {}).get("warnings") or [],
                             path, weather_charts=payload.get("weather_charts") or {})
    with fitz.open(path) as document:
        page_one = " ".join(document[0].get_text().split())
    _RENDERED[key] = {"analysis": payload, "source": source, "view": payload["view"]["briefing"], "page_one": page_one}
    return _RENDERED[key]


@pytest.mark.parametrize("key", sorted(REAL))
def test_the_view_publishes_exactly_what_page_one_prints(key, tmp_path_factory):
    rendered = _rendered(key, tmp_path_factory)
    published = rendered["view"]["page_one_pertinent"]
    for role in ("departure", "destination"):
        field = published[role]
        analysis = next(item for item in rendered["view"]["airport_pdf_analysis"] if item["role"] == role)
        assert field == page_one_pertinent(analysis), role
        for line in page_one_pertinent_lines(field, POINTER):
            assert " ".join(line.split()) in rendered["page_one"], (role, line)
        if field["analysed_count"]:
            assert field["named_lines"], (role, "a station with analysed consequences names one")
        assert all(item["named"] for item in field["items"] if item["tier"] <= 1), role
        expected = REAL[key][1]
        if expected:
            counts, named = expected[role]
            assert (field["analysed_count"], field["unresolved_count"]) == counts, role
            assert field["named_lines"] == named, role


# The rules before the statement named restrictions in their short form. A pack
# saved under them holds a statement that named nothing where page 1 now names
# the planned runway; reopening it must bring both surfaces under the new one.
RULES_BEFORE_THE_STATEMENT = "2026-09-23-page-one-pertinent-statement-v64"


def test_a_pack_saved_before_the_statement_is_served_it_on_reopen(tmp_path_factory):
    rendered = _rendered("SQ303", tmp_path_factory)
    assert COMBINED_BRIEFING_SCHEMA_VERSION != RULES_BEFORE_THE_STATEMENT
    saved = copy.deepcopy(rendered["analysis"])
    saved["view"]["briefing"].pop("page_one_pertinent")
    saved["view"]["briefing"]["publication_rules"] = RULES_BEFORE_THE_STATEMENT
    result = current_rules_briefing(saved, rendered["source"])
    assert result["rebuilt_from_held_analysis"] is True
    assert result["briefing"]["page_one_pertinent"] == rendered["view"]["page_one_pertinent"]
