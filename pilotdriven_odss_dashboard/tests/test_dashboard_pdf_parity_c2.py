"""Task C2: the dashboard and the downloaded PDF must publish one analysis.

Three faults, all found by running the release gate
``dashboard-downloaded-pdf-publication-parity`` early and diagnostically over
the 26 private-corpus flights that passed C1.

1. **Excess fuel.** The gate could not find ``analysed.fuel.excess_fuel`` in the
   PDF on any of the 26 flights. Page 1's FUEL tile prints it as a label/value
   pair in separate text objects, and page 3's fuel chain did not print it at
   all - only its ``TANKER:``/``MEL:`` allocation under RECONCILIATION.

   Underneath that was a real divergence, not an extraction quirk. David's own
   reference briefing (``SQ910_21AUG2026_Flight_Briefing.pdf``) prints
   ``TANKER +18,847 KG`` in the page-1 FUEL tile and a contiguous
   ``TANKER EXCESS 18,847 KG`` row in the page-3 FUEL PLAN / MASS CHAIN, and
   the app's own page-1 card model (``web/src/lib/overview-cards.ts``
   ``fuelCard``) prints ``TANKER`` for a tanker-only excess. Our PDF printed
   ``EXCESS``. Global constraint 7: his reference wins.

2. **Obstacle notices.** ``engines._notam_operational_summary`` published a
   fixed sentence for ``kind == "obstacle"`` that states nothing the notice
   says. The dashboard refuses that template and derives a line from the source
   instead, so the two surfaces disagreed on SQ606-SIN-ICN-06SEP's four RKSI
   records (SX1/26, SX88/25, SX102/25, SX66/26).

3. **The stored-summary fallback.** ``briefing._compact_notam_text`` honoured a
   stored summary only when it equalled the fresh derivation, and on any
   difference fell through to a terminal ``return str(item.get("summary") or
   raw or ...)`` that published the stored summary - or the raw Item E -
   verbatim, bypassing C1's copy guard. The publication gate then refuses the
   page as a whole-record copy, which in production means
   ``render_analysed_briefing`` deletes the PDF and Download PDF fails.

The copy rule restated here is the gate's own
(``concise_pdf_gate.check_concise_pdf``), not the derivation's, for the same
reason as in C1: a test that asked the derivation what it was allowed to say
could not catch the derivation saying something new.
"""
from __future__ import annotations

import gzip
import json
from pathlib import Path
import re

import fitz
import pytest

from app.analysis import run_odss_analysis
from app.odss.analysed_briefing_content import (
    excess_fuel_chain_label,
    excess_fuel_tile_label,
    tanker_only_excess,
)
from app.odss.briefing import (
    _compact_notam_family,
    _compact_notam_text,
    _republishable_finding,
    build_briefing_view,
)
from app.odss.combined_brief import render_combined_briefing
from app.odss.engines import _notam_operational_summary, notam_dashboard_line
from app.odss.notam_restriction_line import (
    FIXED_MARKER_SENTENCES,
    derive_notam_restriction_line,
)

CORPUS = Path(__file__).resolve().parents[2] / "private_cfp_corpus"
CORPUS_MANIFEST = Path(__file__).resolve().parent / "private_cfp_corpus_manifest.json"
SOURCE_CORPUS = Path(__file__).parent / "fixtures" / "notam_restriction_source_corpus.json.gz"
CORPUS_ROWS = json.loads(gzip.decompress(SOURCE_CORPUS.read_bytes()))["rows"]

# SQ910-21AUG is the flight David's own reference briefing was made from and its
# whole non-zero excess is TANKER (18,847 kg). SQ194 is the flight the C2 brief
# names (4,592 kg, TANKER-only). SQ366 carries a mixed INTAM/TMM excess, so it
# must still read EXCESS - the rule has to be able to say no.
TANKER_ONLY_CASES = ("SQ910-SIN-MNL-21AUG", "SQ194-SIN-HAN")
MIXED_EXCESS_CASE = "SQ366-SIN-FCO"
OBSTACLE_CASE = "SQ606-SIN-ICN-06SEP"


# --------------------------------------------------------------- copy rule

GATE_COPY_RUN = 18
GATE_COPY_MIN_WORDS = 3


def gate_words(value: object) -> list[str]:
    """``concise_pdf_gate.normalized``'s own word split, copied not imported."""
    return re.sub(r"[^A-Z0-9]+", " ", str(value).upper()).split()


def gate_calls_it_a_copy(source: str, published: str) -> bool:
    words = gate_words(source)
    body = " ".join(gate_words(published))
    if len(words) >= GATE_COPY_MIN_WORDS and " ".join(words) in body:
        return True
    runs = {
        " ".join(words[index:index + GATE_COPY_RUN])
        for index in range(len(words) - GATE_COPY_RUN + 1)
    }
    return body.count(" ") >= GATE_COPY_RUN - 1 and any(run in body for run in runs)


def without_markers(published: str) -> str:
    body = published
    trimmed = True
    while trimmed:
        trimmed = False
        for sentence in FIXED_MARKER_SENTENCES:
            if body.endswith(sentence):
                body = body[: -len(sentence)].rstrip()
                trimmed = True
    return body


def assert_not_a_copy(source: str, published: str) -> None:
    assert not gate_calls_it_a_copy(source, without_markers(published)), published
    assert not gate_calls_it_a_copy(source, published), published


def assert_ends_in_a_marker(published: str) -> None:
    assert any(published.endswith(sentence) for sentence in FIXED_MARKER_SENTENCES), published


# ------------------------------------------- the app's own refusal predicate

# scripts/lib/briefing-surface-parity.mjs rejectedAirportSummary, restated.
# Widening this here would be exactly the "weaken the oracle" move the brief
# forbids, so it is a copy of the app's rule, never an import of ODSS's.
OBSTACLE_FILLER_RE = re.compile(r"^Obstacle or crane affects\b", re.IGNORECASE)
GENERIC_RESTRICTION_RE = re.compile(
    r"^[\w /()-]+ restriction applies during the applicable [\w -]+ window\.$",
    re.IGNORECASE,
)


def dashboard_refuses(published: str, source: str) -> bool:
    candidate = " ".join(str(published or "").split())
    if not candidate:
        return True
    if OBSTACLE_FILLER_RE.search(candidate) or GENERIC_RESTRICTION_RE.match(candidate):
        return True
    letters = re.sub(r"[^a-zA-Z]", "", candidate)
    if len(letters) >= 24 and len(re.sub(r"[^A-Z]", "", letters)) / len(letters) > 0.9:
        return True
    excerpt = candidate.rstrip("…").strip()
    return len(excerpt) > 260 and excerpt.lower() in " ".join(str(source or "").split()).lower()


# ------------------------------------------------------------ corpus render

_RENDERED: dict[str, dict] = {}


def rendered(case_id: str, tmp_path_factory) -> dict:
    """Publish exactly what the Download PDF button publishes, once per case."""
    if case_id in _RENDERED:
        return _RENDERED[case_id]
    cases = json.loads(CORPUS_MANIFEST.read_text(encoding="utf-8"))["cases"]
    case = next((item for item in cases if item["case_id"] == case_id), None)
    assert case is not None, f"{case_id} is not in the private CFP corpus manifest"
    source = CORPUS / case["filename"]
    if not source.is_file():
        pytest.skip(f"private CFP corpus file {case['filename']} is not available")
    root = tmp_path_factory.mktemp(f"c2-{case_id}")
    result = run_odss_analysis(source, root / "analysis", root / "reports", 1)
    payload = json.loads(Path(result["analysis_path"]).read_text(encoding="utf-8"))
    path = root / f"{case_id}_Operational_Flight_Briefing.pdf"
    render_combined_briefing(
        payload["flight"],
        payload["findings"],
        payload.get("view", {}).get("warnings") or [],
        path,
        weather_charts=payload.get("weather_charts") or {},
    )
    with fitz.open(path) as document:
        pages = [page.get_text() for page in document]
    _RENDERED[case_id] = {"payload": payload, "path": path, "pages": pages}
    return _RENDERED[case_id]


def fuel_summary_of(payload: dict) -> dict:
    return ((payload.get("view") or {}).get("briefing") or {}).get("fuel_summary") or {}


def one_line(value: str) -> str:
    return " ".join(str(value).split())


# =========================================================== fault 1: fuel


@pytest.mark.parametrize(
    "breakdown,tanker",
    [
        pytest.param([], False, id="no itemised allocation"),
        pytest.param([{"label": "TANKER", "fuel_kg": 4592}], True, id="tanker only"),
        pytest.param([{"label": "tanker", "fuel_kg": 4592}], True, id="lowercase label"),
        pytest.param([{"label": " TANKER ", "fuel_kg": 4592}], True, id="padded label"),
        pytest.param(
            [{"label": "TANKER", "fuel_kg": 4592}, {"label": "MEL", "fuel_kg": 0}],
            True,
            id="tanker plus zero rows",
        ),
        pytest.param([{"label": "TANKER", "fuel_kg": 0}], False, id="tanker is zero"),
        pytest.param(
            [{"label": "TANKER", "fuel_kg": 3000}, {"label": "POLICY", "fuel_kg": 1500}],
            False,
            id="mixed allocation",
        ),
        pytest.param([{"label": "POLICY", "fuel_kg": 1500}], False, id="policy only"),
        pytest.param([{"label": "INTAM", "fuel_kg": 3000}], False, id="intam only"),
        pytest.param([{"label": "TANKER", "fuel_kg": -100}], False, id="negative allocation"),
    ],
)
def test_the_excess_label_rule_is_the_dashboards_tanker_only_rule(breakdown, tanker):
    """One rule, three surfaces.

    ``web/src/lib/overview-cards.ts`` ``tankerOnly`` is the dashboard's rule:
    at least one strictly positive allocation and every positive one labelled
    TANKER. The PDF must not have a second opinion about the same OFP line.
    """
    summary = {"excess_breakdown": breakdown}
    assert tanker_only_excess(summary) is tanker
    assert excess_fuel_tile_label(summary) == ("TANKER" if tanker else "EXCESS")
    assert excess_fuel_chain_label(summary) == ("TANKER EXCESS" if tanker else "EXCESS")


def test_the_excess_label_rule_tolerates_a_missing_or_malformed_summary():
    for summary in (None, {}, {"excess_breakdown": None}, {"excess_breakdown": ["TANKER"]}):
        assert tanker_only_excess(summary) is False
        assert excess_fuel_tile_label(summary) == "EXCESS"


@pytest.mark.parametrize("case_id", TANKER_ONLY_CASES)
def test_the_page1_fuel_tile_names_a_tanker_only_excess_in_his_reference_word(
    case_id, tmp_path_factory,
):
    """His reference page-1 FUEL tile reads ``TANKER +18,847 KG``, not EXCESS."""
    briefing = rendered(case_id, tmp_path_factory)
    fuel = fuel_summary_of(briefing["payload"])
    assert tanker_only_excess(fuel), f"{case_id} is not a tanker-only excess any more"
    excess = int((fuel.get("rows") or {}).get("excess_fuel", {}).get("fuel_kg"))
    page_one = one_line(briefing["pages"][0])
    assert f"FPL REQ {int((fuel.get('rows') or {}).get('flt_plan_reqmt', {}).get('fuel_kg')):,} kg " \
           f"TANKER {excess:,} kg" in page_one, page_one
    assert f"EXCESS {excess:,} kg" not in page_one


@pytest.mark.parametrize("case_id", TANKER_ONLY_CASES)
def test_the_page3_fuel_chain_prints_a_contiguous_tanker_excess_row(
    case_id, tmp_path_factory,
):
    """His reference page 3 prints ``TANKER EXCESS 18,847 KG`` in the chain.

    Contiguous matters: the parity gate reads the PDF with plain ``pdftotext``
    as well as ``-layout``, and a label/value pair split into two text objects
    is why the gate could not find this fact on any of the 26 flights.
    """
    briefing = rendered(case_id, tmp_path_factory)
    fuel = fuel_summary_of(briefing["payload"])
    excess = int((fuel.get("rows") or {}).get("excess_fuel", {}).get("fuel_kg"))
    page_three = one_line(briefing["pages"][2])
    tanks = int((fuel.get("rows") or {}).get("fuel_in_tanks", {}).get("fuel_kg"))
    requirement = int((fuel.get("rows") or {}).get("flt_plan_reqmt", {}).get("fuel_kg"))
    # His reference order: FPL REQUIREMENT, TANKER EXCESS, FUEL IN TANKS.
    assert (
        f"FLT PLAN REQMT {requirement:,} kg "
        f"TANKER EXCESS {excess:,} kg "
        f"FUEL IN TANKS {tanks:,} kg" in page_three
    ), page_three
    # The chain keeps its arithmetic: excess is tanks minus the plan requirement.
    assert tanks - requirement == excess


def test_a_mixed_excess_still_reads_excess_on_both_pages(tmp_path_factory):
    """The rule must be able to say no, or it is not a rule."""
    briefing = rendered(MIXED_EXCESS_CASE, tmp_path_factory)
    fuel = fuel_summary_of(briefing["payload"])
    assert not tanker_only_excess(fuel)
    excess = int((fuel.get("rows") or {}).get("excess_fuel", {}).get("fuel_kg"))
    page_one = one_line(briefing["pages"][0])
    page_three = one_line(briefing["pages"][2])
    assert f"EXCESS {excess:,} kg" in page_one, page_one
    assert f"EXCESS {excess:,} kg" in page_three, page_three
    assert f"TANKER {excess:,} kg" not in page_one
    assert f"TANKER EXCESS {excess:,} kg" not in page_three


# ======================================================= fault 2: obstacles

# RKSI AIP supplement notices from SQ606-SIN-ICN-06SEP, verbatim. These are the
# four records the parity gate reported as airportRecordPdfDivergences.
RKSI_OBSTACLE_SOURCES = {
    "SX1/26": (
        "AX0001/26 AIP SUPPLEMENT RKSI/SEOUL/INCHEON INTL TEMPORARY OBSTACLES ERECTED "
        "VALIDITY: 08JAN26 1500 - 30SEP26 1500 THE OBST WILL BE INSTL TO THE S BTN RWY "
        "15R/33L AND RWY 16L/34R OF INCHEON INTL AP. THE OBST ARE LOCATED ABT 1 700 M TO "
        "THE SW FM THE SOUTHERN END OF RWY 15R/33L. POSITION OF HIGHEST OBSTACLE: "
        "37DEG26'15.0000\"N 126DEG27'43.0000\"E - CRANE - HEIGHT 69.70M AGL/74.70M AMSL "
        "RMK (1) EACH CRANE TURNS ON ITS AXIS(RADIUS 70 M). (2) WORKS WILL BE CONDUCTED "
        "BY EQUIPMENTS AND VEHICLES IN THE AREA AS SHOWN IN THE DIAGRAMS. (3) THESE "
        "CRANES PENETRATE THE HORIZONTAL SFC OF RKSI."
    ),
    "SX88/25": (
        "SX0088/25 AIP SUPPLEMENT RKSI/SEOUL/INCHEON INTL TEMPO OBST ERECTED VALIDITY: "
        "16OCT25 1500UTC - 31OCT26 1500UTC TEMPO OBST ERECTED THE OBST WILL BE INSTL TO "
        "THE S BTN RWY 15R/33L AND RWY 16L/34R OFINCHEON INTL AP.  THE OBST ARE LOCATED "
        "ABT 1 700 M TO THE SW FM THE SOUTHERN ENDOF RWY 15R/33L. CRANE PSN AGL AMSL "
        "372617N 1262745E     48.80 M    53.80 M 372615N 1262747E     48.80 M    53.80 M"
    ),
    "SX102/25": (
        "SX0102/25 AIP SUPPLEMENT RKSI/SEOUL/INCHEON INTL VALIDITY: 24DEC25 1600UTC - "
        "12JAN27 1500UTC OPR RESTRICTION. ACFT STAND NR. 505 WILL BE CLSD AS FLW DUE TO "
        "OPR USE. SAFETY FENCE WILL BE INSTL TO INDICATE THE WORKING AREA. EQPT AND "
        "VEHICLES DO NOT PENETRATE OBST LIMITATION SURFACES."
    ),
    "SX66/26": (
        "SX0066/26 AIP SUPPLEMENT RKSI/SEOUL INCHEON VALIDITY:19AUG26 1600-31DEC26 1500 "
        "TEMPORARY OBSTACLES ERECTED THE OBSTACLES WILL BE INSTALLED TO THE NORTH BETWEEN "
        "RWY 16L/34R AND RWY 15R/33L OF INCHEON INTL AIRPORT. THE OBSTACLES ARE LOCATED "
        "ABOUT 721 M TO THE EAST FROM THE CENTERLINE OF RWY 16L/34R. POSITION "
        "37DEG28'50.8062\"N 126DEG25'07.5302\"E  52.80 M AGL 57.80 M AMSL"
    ),
}


RUNWAY_NOT_CLOSED_NOTE = "The runway is not reported closed by this notice."


def expected_obstacle_line(source: str) -> str:
    """The derived line, plus the boss's runway qualifier when one is named.

    The qualifier goes BEFORE the derivation's trailing marker sentence, so
    the line still ends by saying what it did not print.
    """
    derived = derive_notam_restriction_line(source)["text"]
    if not re.search(r"\b(?:RWY|RUNWAY)\s+\d{1,2}", one_line(source).upper()):
        return derived
    body, markers = derived, []
    trimmed = True
    while trimmed:
        trimmed = False
        for sentence in FIXED_MARKER_SENTENCES:
            if body.endswith(sentence):
                markers.insert(0, sentence)
                body = body[: -len(sentence)].rstrip()
                trimmed = True
    return " ".join(part for part in (body, RUNWAY_NOT_CLOSED_NOTE, *markers) if part)


@pytest.mark.parametrize("notam_id", sorted(RKSI_OBSTACLE_SOURCES))
@pytest.mark.parametrize("role", ["departure", "destination", "EDTO"])
def test_an_obstacle_notice_publishes_a_line_derived_from_its_own_source(notam_id, role):
    source = RKSI_OBSTACLE_SOURCES[notam_id]
    published = _notam_operational_summary(source, "obstacle", role)
    assert not dashboard_refuses(published, source), published
    assert published == expected_obstacle_line(source)
    assert_not_a_copy(source, published)


@pytest.mark.parametrize("notam_id", ["SX1/26", "SX88/25", "SX66/26"])
def test_an_obstacle_notice_naming_a_runway_still_denies_a_closure(notam_id):
    """The boss's 16 Aug 2026 rule survives the derivation change: an obstacle
    is never skim-read as a runway closure."""
    published = _notam_operational_summary(
        RKSI_OBSTACLE_SOURCES[notam_id], "obstacle", "destination",
    )
    assert RUNWAY_NOT_CLOSED_NOTE in published, published
    assert "restriction applies" not in published.lower()


def test_no_obstacle_notice_publishes_the_content_free_template():
    """The template the dashboard refuses must not reach either surface."""
    for notam_id, source in RKSI_OBSTACLE_SOURCES.items():
        published = _notam_operational_summary(source, "obstacle", "destination")
        assert not OBSTACLE_FILLER_RE.search(published), f"{notam_id}: {published}"


def test_an_obstacle_notice_with_no_source_text_abstains_explicitly():
    published = _notam_operational_summary("", "obstacle", "destination")
    assert published == derive_notam_restriction_line("")["text"]
    assert_ends_in_a_marker(published)


def test_no_obstacle_shaped_source_in_the_real_corpus_states_nothing():
    """Sweep the committed corpus: every obstacle notice must publish a line
    the dashboard accepts, and none of them may be a copy of its own source."""
    checked = 0
    for row in CORPUS_ROWS:
        source = one_line(row.get("text") or "")
        if not source or "OBST" not in source.upper():
            continue
        published = _notam_operational_summary(source, "obstacle", row.get("role") or "destination")
        assert not dashboard_refuses(published, source), f"{row.get('notam_id')}: {published}"
        assert_not_a_copy(source, published)
        checked += 1
    assert checked >= 50, f"only {checked} obstacle-shaped sources were checked"


def test_the_sq606_download_publishes_no_wording_the_dashboard_refuses(tmp_path_factory):
    """The real flight, the real Download PDF call, read back off the page."""
    briefing = rendered(OBSTACLE_CASE, tmp_path_factory)
    body = one_line(" ".join(briefing["pages"]))
    panels = (
        ((briefing["payload"].get("view") or {}).get("briefing") or {})
        .get("airport_operational_panels")
        or []
    )
    checked = 0
    for panel in panels:
        for notam in panel.get("selected_notams") or []:
            source = notam.get("item_e_text") or notam.get("raw") or ""
            for wording in {
                one_line(notam.get("compact_text") or ""),
                one_line(notam.get("summary") or ""),
            }:
                if not wording or not dashboard_refuses(wording, source):
                    continue
                checked += 1
                assert wording not in body, (
                    f"{panel.get('icao')} {notam.get('notam_id')}: the PDF publishes a "
                    f'wording the dashboard refuses - "{wording}"'
                )
    # The obstacle records are still in this pack; the assertion above is not
    # green because nothing reached it.
    assert len(panels) >= 1
    assert any(
        notam.get("notam_id") in RKSI_OBSTACLE_SOURCES
        for panel in panels
        for notam in panel.get("selected_notams") or []
    ), "SQ606 no longer carries the four RKSI records this test exists for"


# ============================================ fault 3: the stored-summary gap

STORED_SUMMARY_KINDS = ("runway_approach_restriction", "taxiway_restriction")

# The two records release 22 actually refused, verbatim.
RAW_ITEM_E = {
    "1A1353/26": (
        "RWY 04R/22L PAVEMENT STRUCTURE AND FRICTION MAY VARY ON AFFECTED RWY SURFACE "
        "PARTS DUE TO PARTIAL RESURFACING."
    ),
    "1A4143/26": (
        "OCA(H) VALUES RAISED: LPV APCH Z RWY 07C: A 652(324), B 652(324), C 652(324), "
        "D 652(324). LPV APCH Y RWY 07R: A 660(324), B 660(324), C 660(324), D 660(324). "
        "LNAV APCH Z RWY 25L: A 780(444), B 780(444), C 780(444), D 780(444)."
    ),
}


@pytest.mark.parametrize("notam_id", sorted(RAW_ITEM_E))
@pytest.mark.parametrize("kind", STORED_SUMMARY_KINDS)
@pytest.mark.parametrize("dashboard", [False, True])
def test_a_stored_summary_that_is_the_raw_source_is_never_published(notam_id, kind, dashboard):
    """The terminal fallback published the stored summary - or the raw Item E.

    ``briefing._compact_notam_text`` honoured a stored summary only when it
    EQUALLED the fresh derivation. On any difference it fell through to
    ``return str(item.get("summary") or raw or ...)``, which is how the raw
    record reached the page and how the publication gate came to refuse the
    whole PDF.
    """
    raw = RAW_ITEM_E[notam_id]
    item = {"item_e_text": raw, "summary": raw, "pertinence_kind": kind, "notam_id": notam_id}
    published = _compact_notam_text(
        item,
        _compact_notam_family(item),
        role="destination",
        planned_runways=set(),
        reference_time=None,
        dashboard=dashboard,
    )
    assert_not_a_copy(raw, published)
    assert published != raw


@pytest.mark.parametrize("kind", STORED_SUMMARY_KINDS)
@pytest.mark.parametrize("dashboard", [False, True])
def test_a_stored_summary_that_copies_a_long_run_of_its_source_is_refused(kind, dashboard):
    """Not only whole-record equality: the gate's 18-word run rule too."""
    raw = RAW_ITEM_E["1A4143/26"]
    stored = " ".join(raw.split()[:22])
    item = {"item_e_text": raw, "summary": stored, "pertinence_kind": kind, "notam_id": "X"}
    assert gate_calls_it_a_copy(raw, stored), "the fixture must be a copy to be a test"
    published = _compact_notam_text(
        item,
        _compact_notam_family(item),
        role="destination",
        planned_runways=set(),
        reference_time=None,
        dashboard=dashboard,
    )
    assert_not_a_copy(raw, published)


@pytest.mark.parametrize("kind", STORED_SUMMARY_KINDS)
@pytest.mark.parametrize("dashboard", [False, True])
def test_the_refused_stored_summary_abstains_to_an_explicit_gap(kind, dashboard):
    """Abstain, never invent: the gap has to say the analysis could not reduce
    the notice, and it has to be the derivation's own wording so the dashboard
    and the PDF abstain in the same words."""
    raw = RAW_ITEM_E["1A1353/26"]
    item = {"item_e_text": raw, "summary": raw, "pertinence_kind": kind, "notam_id": "Y"}
    published = _compact_notam_text(
        item,
        _compact_notam_family(item),
        role="destination",
        planned_runways=set(),
        reference_time=None,
        dashboard=dashboard,
    )
    assert published == derive_notam_restriction_line(raw)["text"]
    assert_ends_in_a_marker(published)


@pytest.mark.parametrize("kind", STORED_SUMMARY_KINDS)
@pytest.mark.parametrize("dashboard", [False, True])
def test_a_stored_summary_that_is_not_a_copy_is_still_honoured(kind, dashboard):
    """The fix is a copy guard, not a ban on stored analysis.

    A saved pack whose stored summary differs from today's derivation but says
    something of its own must keep saying it; only a copy is refused.
    """
    raw = RAW_ITEM_E["1A1353/26"]
    stored = "RWY 04R/22L friction may vary; review the resurfacing notice."
    assert not gate_calls_it_a_copy(raw, stored)
    item = {"item_e_text": raw, "summary": stored, "pertinence_kind": kind, "notam_id": "Z"}
    published = _compact_notam_text(
        item,
        _compact_notam_family(item),
        role="destination",
        planned_runways=set(),
        reference_time=None,
        dashboard=dashboard,
    )
    assert published == stored


def published_fallback(raw: str, kind: str, dashboard: bool, notam_id: str = "SWEEP") -> str:
    item = {
        "item_e_text": raw,
        "summary": raw,
        "pertinence_kind": kind,
        "notam_id": notam_id,
    }
    return _compact_notam_text(
        item,
        _compact_notam_family(item),
        role="destination",
        planned_runways=set(),
        reference_time=None,
        dashboard=dashboard,
    )


def test_the_stored_summary_fallback_holds_for_every_real_corpus_source():
    """Sweep: no source in the committed corpus publishes a copy through the
    fallback, for either kind and either ``dashboard`` value.

    The FAA approach-procedure branch above the fallback is excluded here and
    measured on its own in the next test - it is a different, pre-existing copy
    path that this task deliberately did not trade coverage to close.
    """
    checked = 0
    for row in CORPUS_ROWS:
        raw = one_line(row.get("text") or "")
        if not raw:
            continue
        for kind in STORED_SUMMARY_KINDS:
            for dashboard in (False, True):
                if dashboard and notam_dashboard_line(raw, kind):
                    continue
                assert_not_a_copy(raw, published_fallback(raw, kind, dashboard, row.get("notam_id") or "SWEEP"))
                checked += 1
    assert checked >= 5000, f"only {checked} vectors were checked"


# The FAA approach-procedure records whose dashboard line is an 18-word run of
# their own source. Found by the sweep above, confirmed at the function, and
# LEFT ALONE on purpose: the derivation that would replace them trades a usable
# minima or missed-approach line for "Instrument approach procedure notice:
# <procedure>. This NOTAM has further content", which is a coverage loss on a
# pilot-facing card. That trade is a coverage decision for David or Jabe, not a
# silent edit (C2 report, residual 1). The list is a ratchet: it may shrink,
# never grow, and a twelfth record fails this test rather than a release gate.
FAA_PROCEDURE_COPY_RECORDS = {
    "A4412/26", "A4413/26", "A4414/26", "A4415/26", "A6919/26",
    "A2666/26", "A3339/26", "A3338/26", "A1525/26", "A4351/26", "A2496/26",
}


def test_the_faa_approach_procedure_line_is_the_only_remaining_copy_path():
    """Measure the one copy path C2 did not close, so it cannot grow quietly.

    ``notam_dashboard_line`` publishes the FAA procedure and its note. For
    eleven committed corpus records that note is long enough that the line
    reproduces an 18-word run of item E - the rule ``check_concise_pdf`` uses
    to delete a published PDF. These lines reach the PDF through the stored
    ``compact_text``, so this is a latent release-gate exposure, not only a
    dashboard wording question.
    """
    found = set()
    for row in CORPUS_ROWS:
        raw = one_line(row.get("text") or "")
        if not raw:
            continue
        for kind in STORED_SUMMARY_KINDS:
            line = notam_dashboard_line(raw, kind)
            if line and gate_calls_it_a_copy(raw, line):
                found.add(str(row.get("notam_id") or "unknown"))
    assert found <= FAA_PROCEDURE_COPY_RECORDS, (
        f"new FAA procedure lines copy their own NOTAM: {sorted(found - FAA_PROCEDURE_COPY_RECORDS)}.\n"
        "Do not add them to the reviewed list to go green: either shorten the "
        "published note through the source-bound derivation, or get an explicit "
        "coverage decision from David or Jabe (C2 report, residual 1)."
    )
    assert found, "the measurement found nothing at all, so it is not measuring"


# ============ round 2: fault 2 on a pack that is ALREADY in production storage
#
# C2 round 1 fixed fault 2 at ANALYSIS time (``engines._notam_operational_
# summary``). The obstacle line is frozen from there into
# ``view.briefing.airport_operational_panels[].selected_notams[].summary`` and
# ``.compact_text``, and Download PDF renders from the stored analysis without
# re-analysing it (``main.get_service_combined_report``: "analyses stored
# before this release - including currently open flights - get the combined
# briefing without re-analysis").
#
# So a flight already in storage still carries the OLD template as its stored
# summary. The round-1 fallback, ``briefing._non_copying_notam_fallback``, was
# hardened against COPIES only - and the content-free template is not a copy of
# anything - so it republished the refused template verbatim, for both
# ``dashboard`` values. The dashboard refuses that same string
# (``web/src/lib/airport-critical-notams.mjs`` ``OBSTACLE_FILLER_RE``) and
# derives its own line, so the two surfaces diverged again for every flight
# already in storage: the parity gate passes on the corpus, which is freshly
# analysed, while David opening an existing flight sees the unfixed fault.
#
# The rule these tests pin is the parity invariant itself, not just this one
# template: **no publication path may republish a stored wording the dashboard
# refuses**. The refusal predicate is the app's, restated above in
# ``dashboard_refuses`` and never imported from ODSS.

# The exact wording prod ODSS 7da0542 stored, with and without the qualifier
# that release 22 appended to records naming a runway.
OLD_OBSTACLE_TEMPLATE_BODY = (
    "Obstacle or crane affects the destination airport environment; "
    "assess against expected runway and approach use."
)
OLD_OBSTACLE_TEMPLATE = f"{OLD_OBSTACLE_TEMPLATE_BODY} {RUNWAY_NOT_CLOSED_NOTE}"

# An older build's generic wording, the second shape the dashboard refuses.
OLD_GENERIC_RESTRICTION = "Runway restriction applies during the applicable arrival window."

STALE_TEMPLATES = (OLD_OBSTACLE_TEMPLATE, OLD_OBSTACLE_TEMPLATE_BODY, OLD_GENERIC_RESTRICTION)


def stale_pack_line(
    raw: str,
    stored_summary: str,
    *,
    kind: str = "obstacle",
    dashboard: bool = False,
    role: str = "destination",
    notam_id: str = "STALE",
) -> str:
    """What a pack analysed by an older build republishes when it is rendered.

    This is the Download PDF path: ``combined_brief._pdf_notam_operational_
    headline`` hands the STORED record straight to ``_compact_notam_text``.
    """
    item = {
        "item_e_text": raw,
        "summary": stored_summary,
        "pertinence_kind": kind,
        "notam_id": notam_id,
    }
    return _compact_notam_text(
        item,
        _compact_notam_family(item),
        role=role,
        planned_runways=set(),
        reference_time=None,
        dashboard=dashboard,
    )


@pytest.mark.parametrize("notam_id", sorted(RKSI_OBSTACLE_SOURCES))
@pytest.mark.parametrize("stored", STALE_TEMPLATES)
@pytest.mark.parametrize("dashboard", [False, True])
def test_a_stored_content_free_template_is_never_republished(notam_id, stored, dashboard):
    """The reviewer's reproduction, pinned.

    An item whose stored summary is the old content-free template must not put
    that template back on the page, on either surface.
    """
    source = RKSI_OBSTACLE_SOURCES[notam_id]
    assert dashboard_refuses(stored, source), "the fixture must be refused to be a test"
    published = stale_pack_line(source, stored, dashboard=dashboard, notam_id=notam_id)
    assert published != stored
    assert not dashboard_refuses(published, source), f"{notam_id}: {published}"
    assert_not_a_copy(source, published)


@pytest.mark.parametrize("notam_id", sorted(RKSI_OBSTACLE_SOURCES))
@pytest.mark.parametrize("dashboard", [False, True])
def test_a_stale_obstacle_pack_publishes_what_a_fresh_analysis_publishes(notam_id, dashboard):
    """The point of the fix: storage age must not change what is published.

    A flight analysed before this release and a flight analysed after it must
    download the same obstacle line, so re-analysis is never the difference
    between the fixed and the unfixed fault.
    """
    source = RKSI_OBSTACLE_SOURCES[notam_id]
    fresh = _notam_operational_summary(source, "obstacle", "destination")
    stale = stale_pack_line(source, OLD_OBSTACLE_TEMPLATE, dashboard=dashboard, notam_id=notam_id)
    assert stale == fresh, f"{notam_id}: stale pack published {stale!r}, fresh {fresh!r}"


@pytest.mark.parametrize("notam_id", ["SX1/26", "SX88/25", "SX66/26"])
@pytest.mark.parametrize("dashboard", [False, True])
def test_a_stale_obstacle_pack_naming_a_runway_still_denies_a_closure(notam_id, dashboard):
    """The boss's 16 Aug 2026 rule must survive the stale path too, or the
    republished line would be the one place an obstacle can be skim-read as a
    runway closure."""
    published = stale_pack_line(
        RKSI_OBSTACLE_SOURCES[notam_id], OLD_OBSTACLE_TEMPLATE,
        dashboard=dashboard, notam_id=notam_id,
    )
    assert RUNWAY_NOT_CLOSED_NOTE in published, published


@pytest.mark.parametrize("dashboard", [False, True])
def test_a_stored_all_caps_summary_is_never_republished(dashboard):
    """The third shape the dashboard refuses: a stored summary that is really
    the raw notice in capitals. It need not be a substring of item E - an older
    build could have rewrapped it - so C1's copy guard does not see it."""
    source = RKSI_OBSTACLE_SOURCES["SX66/26"]
    stored = "TEMPORARY OBSTACLES ERECTED NORTH OF THE FIELD AND LEFT IN PLACE"
    assert dashboard_refuses(stored, source), "the fixture must be refused to be a test"
    assert not gate_calls_it_a_copy(source, stored), "and it must not be caught as a copy"
    published = stale_pack_line(source, stored, dashboard=dashboard)
    assert published != stored
    assert not dashboard_refuses(published, source), published


@pytest.mark.parametrize("kind", STORED_SUMMARY_KINDS)
@pytest.mark.parametrize("dashboard", [False, True])
def test_a_refused_stored_summary_is_refused_for_every_kind(kind, dashboard):
    """The invariant belongs to the publication path, not to one record kind."""
    source = RAW_ITEM_E["1A1353/26"]
    published = stale_pack_line(
        source, OLD_OBSTACLE_TEMPLATE, kind=kind, dashboard=dashboard,
    )
    assert not dashboard_refuses(published, source), published


@pytest.mark.parametrize("dashboard", [False, True])
def test_a_stale_pack_with_no_source_text_still_abstains_in_shared_words(dashboard):
    """Nothing to derive from: abstain in the derivation's own wording rather
    than republish the template, so both surfaces abstain identically."""
    published = stale_pack_line("", OLD_OBSTACLE_TEMPLATE, dashboard=dashboard)
    assert not dashboard_refuses(published, ""), published
    assert published != OLD_OBSTACLE_TEMPLATE


def test_every_corpus_source_survives_a_stale_template_pack():
    """Sweep the committed corpus as if every record had been analysed by the
    build that produced the template: no source may republish it."""
    checked = 0
    for row in CORPUS_ROWS:
        source = one_line(row.get("text") or "")
        if not source:
            continue
        for stored in STALE_TEMPLATES:
            for dashboard in (False, True):
                published = stale_pack_line(
                    source, stored, dashboard=dashboard,
                    notam_id=str(row.get("notam_id") or "SWEEP"),
                )
                assert not dashboard_refuses(published, source), (
                    f"{row.get('notam_id')} stored={stored!r} dashboard={dashboard}: {published}"
                )
                checked += 1
    assert checked >= 5000, f"only {checked} stale vectors were checked"


def test_the_stale_sq606_download_publishes_no_wording_the_dashboard_refuses(tmp_path_factory):
    """End to end, on the path production actually takes.

    ``render_analysed_briefing`` rebuilds the whole view from ``flight`` and
    ``findings`` (``build_briefing_view``), so the stored ``view`` is NOT what
    the download reads - measured on a real pack analysed by the pre-C2 build,
    the ONLY stale input carrying the refused template is ``findings[].summary``
    (four records; ``flight`` carries none). Re-freeze exactly that, then call
    Download PDF as ``main.get_service_combined_report`` does for a flight
    already in storage, and read the published pages back.
    """
    briefing = rendered(OBSTACLE_CASE, tmp_path_factory)
    payload = json.loads(json.dumps(briefing["payload"]))
    staled = 0
    for finding in payload.get("findings") or []:
        data = finding.get("data")
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except ValueError:
                data = {}
        if str((data or {}).get("pertinence_kind") or "") != "obstacle":
            continue
        finding["summary"] = OLD_OBSTACLE_TEMPLATE
        staled += 1
    assert staled >= 4, (
        f"only {staled} obstacle findings were staled; this test exists for the "
        "four RKSI records and cannot pass because nothing reached it"
    )
    root = tmp_path_factory.mktemp("c2-stale-sq606")
    path = root / f"{OBSTACLE_CASE}_Operational_Flight_Briefing.pdf"
    render_combined_briefing(
        payload["flight"],
        payload["findings"],
        payload.get("view", {}).get("warnings") or [],
        path,
        weather_charts=payload.get("weather_charts") or {},
    )
    with fitz.open(path) as document:
        body = one_line(" ".join(page.get_text() for page in document))
    for template in (OLD_OBSTACLE_TEMPLATE, OLD_OBSTACLE_TEMPLATE_BODY):
        assert template not in body, (
            "the stale-pack download publishes a wording the dashboard refuses "
            f'as stating nothing - "{template}"'
        )
    # And it does not pass by publishing nothing: the stale pack must publish
    # what a freshly analysed one publishes. The obstacle line the fresh render
    # of this same flight reaches page 2 with has to be on the stale page too.
    fresh_body = one_line(" ".join(briefing["pages"]))
    fresh_lines = [
        line for line in (
            one_line(_notam_operational_summary(source, "obstacle", "destination"))
            for source in RKSI_OBSTACLE_SOURCES.values()
        )
        if line and line in fresh_body
    ]
    assert fresh_lines, "the fresh render publishes none of the four derived lines"
    for line in fresh_lines:
        assert line in body, (
            f"the stale-pack download dropped the line the fresh one prints - {line!r}"
        )


# ------------------------- where the repair applies, and where it deliberately does not

REV3_PINNED_ANALYSIS = Path(
    "/Users/jabe/Documents/ezzo/tmp/pdfs/pd-rev3-reference/SQ214_REV3_v16_analysis.json"
)


def stale_notam_finding(stored: str = OLD_OBSTACLE_TEMPLATE) -> dict:
    return {
        "rule_id": "NOTAM-AUTO",
        "engine": "notam",
        "severity": "warning",
        "title": "Destination NOTAM SX88/25",
        "summary": stored,
        # A stored analysis holds ``data`` as a dict, which is what the rest of
        # the view builder requires; the repair also tolerates the JSON-string
        # shape a hand-edited or re-serialised pack can carry.
        "data": {
            "notam_id": "SX88/25",
            "pertinence_kind": "obstacle",
            "role": "destination",
            "applicability": "active",
            "raw_text": RKSI_OBSTACLE_SOURCES["SX88/25"],
        },
    }


def test_the_repair_reads_a_stored_json_string_and_a_live_dict_alike():
    dict_form = stale_notam_finding()
    string_form = {**dict_form, "data": json.dumps(dict_form["data"])}
    assert (
        _republishable_finding(string_form)["summary"]
        == _republishable_finding(dict_form)["summary"]
    )
    assert _republishable_finding(dict_form)["summary"] != OLD_OBSTACLE_TEMPLATE


def test_the_repair_leaves_a_finding_that_says_something_of_its_own_alone():
    """A repair, not a re-analysis. Only a refused summary is replaced, and the
    finding object itself is returned unchanged so nothing downstream can tell
    a repaired pack from one that never needed it."""
    stored = "Runway notice: obstacle erected between RWY 15R/33L and RWY 16L/34R."
    finding = stale_notam_finding(stored)
    assert _republishable_finding(finding) is finding


def test_the_repair_ignores_a_finding_that_holds_no_notam():
    """The refusal predicate is defined for airport NOTAM records; a weather or
    performance finding whose wording happens to be capitalised is none of its
    business."""
    finding = {
        "engine": "performance",
        "summary": "ZFW TOW LDW RECONCILE AGAINST THE FILED PLAN VALUES",
        "data": {"role": "destination"},
    }
    assert _republishable_finding(finding) is finding


def test_the_lossless_audit_composition_keeps_what_the_analysis_held():
    """The repair is scoped to the pilot-facing publication, on purpose.

    ``_render_reference_briefing``'s audit appendix is the lossless record of a
    stored analysis - including the fact that it stored a content-free template
    - and the REV3 raster canary pins it pixel for pixel on a SHA-pinned
    historical pack (``tests/rev3_visual_reference_manifest.json``: "This is NOT
    the pilot-facing download"). Repairing it there would make the audit record
    disagree with the analysis it audits and would move an approved reference.

    Both directions are pinned here so neither can be flipped by accident.
    """
    findings = [stale_notam_finding()]
    flight = {"departure": "WSSS", "destination": "RKSI"}
    published = build_briefing_view(flight, findings, [])
    preserved = build_briefing_view(flight, findings, [], preserve_stored_analysis=True)

    def summaries(view):
        return [
            one_line(row.get("summary") or "")
            for row in view.get("decision_findings") or []
        ]

    assert OLD_OBSTACLE_TEMPLATE in summaries(preserved), summaries(preserved)
    assert OLD_OBSTACLE_TEMPLATE not in summaries(published), summaries(published)
    assert any(
        line and not dashboard_refuses(line, RKSI_OBSTACLE_SOURCES["SX88/25"])
        for line in summaries(published)
    ), summaries(published)


def test_the_rev3_pinned_pack_is_exactly_what_the_repair_would_change():
    """Measure the canary's exposure rather than assert it away.

    The pinned REV3 analysis predates C1/C2, so 20 of its 70 findings carry one
    of the two content-free templates. That is the whole reason the audit
    composition opts out: if this count is ever zero the opt-out is dead code
    and should go, and if the templates were something else the classification
    below would be wrong.
    """
    if not REV3_PINNED_ANALYSIS.is_file():
        pytest.skip("the private REV3 pinned analysis is not available")
    payload = json.loads(REV3_PINNED_ANALYSIS.read_text(encoding="utf-8"))
    repaired = [
        item for item in payload.get("findings") or []
        if _republishable_finding(item) is not item
    ]
    assert len(repaired) == 20, len(repaired)
    for item in repaired:
        stored = one_line(item.get("summary") or "")
        assert OBSTACLE_FILLER_RE.search(stored) or GENERIC_RESTRICTION_RE.match(stored), stored


@pytest.mark.parametrize("stored", STALE_TEMPLATES)
def test_the_audit_headline_keeps_the_template_the_analysis_held(stored):
    """``_pdf_notam_operational_headline`` is the audit composition's own
    headline - it is called from nowhere else - so it records what the stored
    analysis held, by the same rule as the audit view above.

    Without this, hardening the fallback moves the REV3 raster canary on a
    SHA-pinned historical pack, which is a re-mint decision for David rather
    than a side effect of closing a parity fault on the download.
    """
    source = RKSI_OBSTACLE_SOURCES["SX88/25"]
    item = {"item_e_text": source, "summary": stored, "pertinence_kind": "obstacle"}
    common = dict(role="destination", planned_runways=set(), reference_time=None)
    assert _compact_notam_text(
        item, _compact_notam_family(item), preserve_stored_analysis=True, **common,
    ) == stored
    # The publication surface still refuses it.
    assert _compact_notam_text(
        item, _compact_notam_family(item), **common,
    ) != stored


@pytest.mark.parametrize("kind", STORED_SUMMARY_KINDS)
def test_the_audit_record_still_refuses_a_stored_summary_that_copies_its_source(kind):
    """C1's invariant is not relaxed anywhere. A content-free template is a
    faithful record of what the analysis held; a copy of item E is a defect on
    every surface, because ``check_concise_pdf`` deletes the published PDF for
    it. Only the ``states_nothing`` refusal is scoped to the publication.
    """
    raw = RAW_ITEM_E["1A1353/26"]
    item = {"item_e_text": raw, "summary": raw, "pertinence_kind": kind}
    published = _compact_notam_text(
        item,
        _compact_notam_family(item),
        role="destination",
        planned_runways=set(),
        reference_time=None,
        preserve_stored_analysis=True,
    )
    assert_not_a_copy(raw, published)
    assert published != raw
