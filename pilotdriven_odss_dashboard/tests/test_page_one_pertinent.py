"""Page 1's PERTINENT field: one statement, decided once, printed by both surfaces.

Independent signed-in QA of release 394 (22 Sep 2026): the dashboard station
cards and page 1 of the downloaded PDF put different numbers under the same
words. SQ303 EBBR/WSSS read 10/9 "analysed surface/approach consequence(s)"
on the dashboard and 2/2 on page 1; SQ352 WSSS/EKCH read 11/6 against 2/1, on
updated and fresh copies alike.

Both numbers were real; they counted different things. The dashboard counted
held notices in scope, one row per notice; page 1 counted the grouped
consequence sentences the analysis could phrase, and said nothing of the
notices it could not reduce whenever it had at least one line - SQ303
WSSS's unresolved RWY 02L/20R notice was on the dashboard and absent from page
1. The repair is not to make one surface imitate the other. The analysis
decides the page-1 statement once - the consequence lines that fit the column,
how many consequences there are, and how many held notices could not be
reduced - publishes it in the view, and both surfaces print it.
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

# Real SQ303 16 Jul 2026 EBBR consequence lines, as the release-394 analysis
# publishes them. The first wraps to six lines of the column; the second to three.
EBBR_APPROACH = ("Unavailable approach aids at departure 16 JUL 0945Z: RWY 25R ILS (SX14/26, A669/26); "
                 "RWY 07L VOR (D351/26). Planned RWY 07R differs from the named affected runway(s).")
EBBR_TAXI = "Taxi access is constrained at departure 16 JUL 0945Z: W1 (SX38/26); Y (A2469/26)."
EBBR_UNRESOLVED = ["SX44/26", "D360/26", "A1801/26", "A2471/26", "A2097/26"]


def analysed(lines, unresolved=(), role="departure", icao="EBBR"):
    return {"role": role, "icao": icao, "lines": [{"text": text} for text in lines], "unresolved_ids": list(unresolved)}


def test_the_field_names_whole_lines_while_they_fit_and_never_promotes_a_later_one():
    field = page_one_pertinent(analysed([EBBR_APPROACH, EBBR_TAXI], EBBR_UNRESOLVED))
    # Six lines do not fit four; the shorter taxi line is not named instead of
    # the approach line that outranks it.
    assert field["named_lines"] == []
    assert field["analysed_count"] == 2
    assert field["unresolved_ids"] == EBBR_UNRESOLVED
    assert field["unresolved_count"] == 5
    assert page_one_pertinent(analysed([EBBR_TAXI]))["named_lines"] == [EBBR_TAXI]


def test_notices_that_could_not_be_reduced_are_stated_beside_the_analysed_count():
    field = page_one_pertinent(analysed([EBBR_APPROACH, EBBR_TAXI], EBBR_UNRESOLVED))
    assert page_one_pertinent_lines(field, POINTER) == [
        "2 analysed surface/approach consequence(s). 5 held notice(s) of a pertinent kind could not be "
        "reduced to a published consequence. Full analysis: AIRPORTS page."
    ]


def test_a_fully_reduced_station_reads_as_it_did():
    field = page_one_pertinent(analysed([EBBR_TAXI]))
    assert page_one_pertinent_lines(field, POINTER) == [
        EBBR_TAXI, "1 analysed surface/approach consequence(s). Full analysis: AIRPORTS page.",
    ]


def test_nothing_reduced_and_nothing_held_are_still_different_statements():
    unresolved_only = page_one_pertinent(analysed([], ["A1312/26", "SX1/26"]))
    assert page_one_pertinent_lines(unresolved_only, POINTER) == [
        "2 held notice(s) of a pertinent kind could not be reduced to a published consequence.",
        "0 analysed surface/approach consequence(s). Full analysis: AIRPORTS page.",
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
    "SQ303": ("SQ30316072026BRU 81.pdf", {"departure": (2, 5), "destination": (2, 1)}),
    "SQ352": ("lido-briefing_SQ_352_15Aug2026_SIN_CPH.pdf", {"departure": (2, 3), "destination": (1, 5)}),
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
        expected = REAL[key][1]
        if expected:
            assert (field["analysed_count"], field["unresolved_count"]) == expected[role], role


# The rules the statement was introduced after. A pack saved under them holds
# a view without it and a PDF page 1 that did not state the notices it could
# not reduce; reopening it must bring both surfaces under the statement.
RULES_BEFORE_THE_STATEMENT = "2026-09-22-aircraft-size-check-conditions-v63"


def test_a_pack_saved_before_the_statement_is_served_it_on_reopen(tmp_path_factory):
    rendered = _rendered("SQ303", tmp_path_factory)
    assert COMBINED_BRIEFING_SCHEMA_VERSION != RULES_BEFORE_THE_STATEMENT
    saved = copy.deepcopy(rendered["analysis"])
    saved["view"]["briefing"].pop("page_one_pertinent")
    saved["view"]["briefing"]["publication_rules"] = RULES_BEFORE_THE_STATEMENT
    result = current_rules_briefing(saved, rendered["source"])
    assert result["rebuilt_from_held_analysis"] is True
    assert result["briefing"]["page_one_pertinent"] == rendered["view"]["page_one_pertinent"]
