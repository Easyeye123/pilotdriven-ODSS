"""The boss's six-page Flight Briefing format, asserted on real corpus flights.

9 Sep 2026, 21:17-21:20. David sent four reference briefings and said:

    "This format from beginning has always been this."
    "Get this right, and then we talk about tweaking from this."
    "Page 1 is good."
    [circling the reference page 2 DECISION ANALYSIS] "This for the longest
    time doesn't work."
    "So you have to check and make sure the memory losses and standard
    established does not degenerate. How do you ensure that???"

His reference ``SQ910_21AUG2026_Flight_Briefing.pdf`` is six pages: OVERVIEW,
DECISION ANALYSIS, PERFORMANCE / FUEL / TECH, AIRPORTS / ALTERNATES,
WEATHER / ROUTE HAZARDS, ENROUTE / INTAM / ASSURANCE. Every page carries the
navigation ribbon and the footer triplet. The production download on 15 Sep
2026 was nine pages with our own section names and no Decision Analysis page
at all.

This module is the answer to "how do you ensure that": the structure is
asserted against the analysed briefing rendered from the real private CFP
corpus - the same SQ910 OFP his reference was made from - not from a
hand-written fixture that can be edited to match whatever we happen to draw.
"""
from __future__ import annotations

from pathlib import Path
import re

import fitz
import pytest

from app.analysis import run_odss_analysis
from app.odss.briefing import build_briefing_view
from app.odss.combined_brief import (
    COMBINED_BRIEFING_SCHEMA_VERSION,
    combined_briefing_cache_token,
    render_combined_briefing,
)
from app.odss.concise_pdf_gate import (
    MAX_BRIEFING_PAGES,
    NAV_RIBBON,
    PAGE_TITLES,
    check_concise_pdf,
    normalized,
)
from app.odss.operational_format import text as published_value
from scripts.run_private_cfp_corpus import scan_physical_pdf


CORPUS = Path(__file__).resolve().parents[2] / "private_cfp_corpus"

# The three flights David sent reference briefings for on 9 Sep 2026, plus the
# SIN-HKG flight from his 9 Sep video, whose analysed prose says "...; review
# required." - the wording that must not be mistaken for an item-level badge.
#
# The six flights after them are the deferred-declaration corpus: none of the
# first four carries a lowercase-destroyed abbreviation or a form-debris
# subject, which is exactly why a suite built on them alone let "Section mel
# and CMS rev 18NOV 25", "Non-essential equipment and nef" and "Both VCRU
# (101HW & 103HW) removed as per" reach the page. Each name below is the flight
# the corresponding defect was measured on.
CORPUS_CASES = {
    "SQ910": "SQ91021082026SIN.pdf",
    "SQ481": "SQ48125082026JNB.pdf",
    "SQ38": "SQ38-29AUG2026-OFP-for-prod-proof.pdf",
    "SQ882": "lido-briefing_SQ_882_09Sep2026_SIN_HKG.pdf",
    # "SECTION MEL AND CMS REV 18NOV 25" - a manual heading, and "mel".
    "SQ366": "SQ36604082026SIN.pdf",
    # "NON-ESSENTIAL EQUIPMENT AND FURNISHINGS (NEF)" and the mid-cell slice
    # "- GALLEY WASTE COMPARTMENT ACCESS DOOR INSTALLED)".
    "SQ605": "SQ60508092026ICN.pdf",
    # "MAINT ENTRY: BOTH VCRU (101HW & 103HW) REMOVED AS PER" and the doubled
    # drop-down "TRASH COMPACTOR, TRASH COMPACTOR, OTHERS (PLS ENTER COMMENTS)".
    "SQ214": "SQ21419082026PER.pdf",
    # "FOUND LH INNER WING LEADING EDGE DND FIXED SEAL WITH" and "DM COM VHF".
    "SQ297": "lido-briefing_SQ_297_16Aug2026_SIN_CHC.pdf",
    # "VIDEO PB ON ECP NOT RESPONSIVE" and "LH WING, SLAT #6 LOWER SEAL FOUND".
    "SQ882-10Sep": "lido-briefing_SQ_882_10Sep2026_SIN_HKG.pdf",
    # "WHOLE ACRFT CHILLERS INOP X DRY ICE REQ" - the half-cased phrase.
    "SQ279": "lido-briefing_SQ_279_15Aug2026_SIN_ADL.pdf",
}

# The publication schema the nine-page briefing was deployed under. David's own
# test path is a SAVED pack: the analysis JSON, and therefore its snapshot
# hash, does not change when he re-opens it after a deployment.
NINE_PAGE_SCHEMA_VERSION = "2026-09-09-flight-window-surface-semantics-v47"

# The page-1 release caveat the nine-page briefing published.
RELEASE_CAVEAT = (
    "Current weather, airport surface state and operative aircraft limitations "
    "must be confirmed before use."
)

_RENDERED: dict[str, dict] = {}


def rendered(flight_key: str, tmp_path_factory) -> dict:
    """Run the real analysis once per flight and publish the real download."""
    if flight_key in _RENDERED:
        return _RENDERED[flight_key]
    source = CORPUS / CORPUS_CASES[flight_key]
    if not source.is_file():
        pytest.skip(f"private CFP corpus file {CORPUS_CASES[flight_key]} is not available")
    import json

    root = tmp_path_factory.mktemp(f"boss-format-{flight_key}")
    result = run_odss_analysis(source, root / "analysis", root / "reports", 1)
    payload = json.loads(Path(result["analysis_path"]).read_text(encoding="utf-8"))
    flight = payload["flight"]
    findings = payload["findings"]
    warnings = payload.get("view", {}).get("warnings") or []
    path = root / f"{flight_key}_Flight_Briefing.pdf"
    render_combined_briefing(
        flight, findings, warnings, path,
        weather_charts=payload.get("weather_charts") or {},
    )
    view = build_briefing_view(
        flight, findings, warnings,
        timing_view=flight.get("timing_view"),
        weather_charts=payload.get("weather_charts") or {},
    )
    with fitz.open(path) as document:
        pages = [page.get_text() for page in document]
    _RENDERED[flight_key] = {
        "key": flight_key,
        "path": path, "flight": flight, "findings": findings,
        "view": view, "pages": pages,
        "folded": [normalized(page) for page in pages],
    }
    return _RENDERED[flight_key]


@pytest.fixture(scope="session", params=sorted(CORPUS_CASES))
def briefing(request, tmp_path_factory):
    return rendered(request.param, tmp_path_factory)


def test_download_is_the_six_page_reference_format(briefing):
    """Nine pages with our own names is the thing he rejected."""
    assert MAX_BRIEFING_PAGES == 6
    with fitz.open(briefing["path"]) as document:
        assert len(document) == 6


def test_every_page_carries_its_reference_title_in_order(briefing):
    titles = (
        "OVERVIEW",
        "DECISION ANALYSIS",
        "PERFORMANCE, FUEL AND TECHNICAL STATUS",
        "AIRPORTS / ALTERNATES",
        "WEATHER / ROUTE HAZARDS",
        "ENROUTE / INTAM / ASSURANCE",
    )
    assert tuple(PAGE_TITLES) == titles
    for index, title in enumerate(titles):
        assert normalized(title) in briefing["folded"][index], (
            f"page {index + 1} must be {title}"
        )


def test_navigation_ribbon_is_on_every_page_with_the_active_item(briefing):
    assert NAV_RIBBON == (
        "OVERVIEW", "ANALYSIS", "PERF / FUEL / TECH",
        "AIRPORTS", "WEATHER", "ENROUTE / INTAM",
    )
    for index, folded in enumerate(briefing["folded"]):
        for item in NAV_RIBBON:
            assert normalized(item) in folded, (
                f"page {index + 1} is missing ribbon item {item}"
            )
        assert normalized(f"FLIGHT BRIEFING | PAGE {index + 1} OF 6") in folded
    # The active ribbon item is underlined, exactly like his reference.
    with fitz.open(briefing["path"]) as document:
        for index, page in enumerate(document):
            spans = [
                span
                for block in page.get_text("dict")["blocks"]
                for line in block.get("lines", [])
                for span in line["spans"]
                if span["text"].strip() == NAV_RIBBON[index]
            ]
            assert spans, f"page {index + 1} has no ribbon entry to underline"
            target = spans[0]
            rules = [
                drawing for drawing in page.get_drawings()
                if abs(drawing["rect"].height) <= 2.5
                and drawing["rect"].x0 <= target["bbox"][0] + 1.5
                and drawing["rect"].x1 >= target["bbox"][2] - 1.5
                and 0 < drawing["rect"].y0 - target["bbox"][3] < 8
            ]
            assert rules, f"ribbon item {NAV_RIBBON[index]} is not underlined"


def test_footer_triplet_names_the_flight_the_assurance_and_the_page(briefing):
    identity = briefing["view"]["flight_identity"]
    flight = briefing["flight"]
    left = (
        f"{briefing['view']['flight_number']} | "
        f"{briefing['view']['flight_date']} | "
        f"{flight['departure']}-{flight['destination']} | "
        f"{identity['aircraft_type']} {identity['registration']} | "
        f"OFP {identity['ofp']}"
    )
    for index, folded in enumerate(briefing["folded"]):
        assert normalized(left) in folded, f"page {index + 1} footer identity"
        assert normalized(f"Page {index + 1} of 6") in folded
    assert normalized(
        "CFP P1 PRIORITISED | SOURCE FACTS + LABELLED ANALYSIS | AI AUTHORITY: NONE"
    ) in briefing["folded"][0]


def test_page_one_is_departure_route_map_destination_then_tiles_and_strip(briefing):
    page = briefing["folded"][0]
    for marker in (
        "DEPARTURE", "DESTINATION", "CFP ROUTE - PERTINENT DECISION GATES",
        "PERFORMANCE", "FUEL", "TECH STATUS", "WEATHER / HAZARDS", "ALTN / ROUTE",
        "RELEASE", "BEFORE PUSH", "ROUTE", "ARRIVAL", "WEATHER",
        "PLAN", "SCHEDULE", "METAR", "TAF", "PERTINENT",
    ):
        assert normalized(marker) in page, f"page 1 is missing {marker}"
    assert page.count("CFP P1") >= 5, "each page-1 tile carries its provenance tag"
    # The schematic route map he circled is drawn, not described.
    with fitz.open(briefing["path"]) as document:
        assert len(document[0].get_drawings()) > 40


def test_page_one_destination_prints_his_taf_tempo_field(briefing):
    """His destination column reads TAF TEMPO; ours read a bare TAF.

    Fix round 1 finding. The conformance gate compared only the first word of
    each of his field labels, so this disagreement between his reference PDF
    and our render passed as valid. Binding rule 7: the reference wins, so the
    destination weather field is published with his whole label - and with the
    TEMPO group under it, because a label has to match the value beneath it.
    """
    page = briefing["folded"][0]
    assert normalized("TAF TEMPO") in page, (
        "page 1 destination column must publish David's TAF TEMPO field"
    )
    # His departure column is a plain TAF; only the destination one is TEMPO.
    with fitz.open(briefing["path"]) as document:
        spans = [
            span
            for block in document[0].get_text("dict")["blocks"]
            for line in block.get("lines", [])
            for span in line["spans"]
            if normalized(span["text"]) in {"TAF", "TAF TEMPO"}
        ]
    by_label = {normalized(span["text"]): span for span in spans}
    assert set(by_label) == {"TAF", "TAF TEMPO"}, sorted(by_label)
    assert by_label["TAF"]["bbox"][0] < by_label["TAF TEMPO"]["bbox"][0], (
        "TAF belongs to the departure column and TAF TEMPO to the destination one"
    )


def test_the_taf_tempo_field_never_publishes_an_absent_tempo_as_fair_weather():
    """A gap is named, never rendered as an empty forecast.

    "Coverage gap is not NIL" is a rule of this codebase. The field prints the
    source TEMPO group verbatim when the TAF holds one, and says so plainly
    when it does not.
    """
    from app.odss.operational_format import taf_tempo_field

    held = (
        "FT 201700 2018/2124 25007KT 9999 FEW025 TX32/2106Z TN26/2021Z "
        "TEMPO 2103/2109 27015KT FEW025 BKN090="
    )
    assert taf_tempo_field(held) == "TEMPO 2103/2109 27015KT FEW025 BKN090"
    probability = (
        "FT 010500 0106/0212 12008KT 9999 SCT020 BECMG 0110/0112 18010KT "
        "PROB30 TEMPO 0114/0118 4000 TSRA BKN012CB="
    )
    assert taf_tempo_field(probability) == "PROB30 TEMPO 0114/0118 4000 TSRA BKN012CB"
    no_tempo = "FT 201700 2018/2200 16008KT 9999 FEW015 SCT020="
    assert "TEMPO" in taf_tempo_field(no_tempo)
    assert "no tempo group" in taf_tempo_field(no_tempo).lower()
    assert taf_tempo_field("") == published_value(None)
    assert taf_tempo_field(None) == published_value(None)


def test_page_two_is_the_decision_analysis_he_circled_in_green(briefing):
    """'This for the longest time doesn't work.' - 9 Sep 2026, 21:17:52."""
    page = briefing["folded"][1]
    findings = briefing["view"]["decision_findings"]
    assert findings, "the analysis must hold ranked decision findings"
    assert normalized("DECISION ANALYSIS") in page
    assert normalized("FLIGHT-PHASE DECISION TIMELINE") in page
    pills = re.findall(r"\b(MAJOR|MODERATE|INFO|REVIEW)\b", briefing["pages"][1])
    assert len([p for p in pills if p in {"MAJOR", "MODERATE"}]) >= 1, (
        "a severity pill must be published for the evidenced findings"
    )
    assert len(pills) >= len(findings)
    for finding in findings:
        assert normalized(finding["title"]) in page, (
            f"decision finding {finding['rank']} is missing from page 2"
        )
    # Every dot on the timeline is annotated with its level and time.
    assert normalized("DEP") in page
    assert re.search(r"\b\d{2}:\d{2}\b|\b\d{4}Z\b", briefing["pages"][1])


def test_relocated_content_keeps_its_owning_section(briefing):
    """Nothing published today is dropped; it moves to the section that owns it."""
    view, folded = briefing["view"], briefing["folded"]
    for analysed in view["airport_pdf_analysis"]:
        for line in analysed["lines"]:
            assert normalized(line["text"]) in folded[3], (
                f"{analysed['icao']} consequence left the airports page"
            )
    for row in view["deferred_pdf_analysis"]:
        assert normalized(row["text"]) in folded[2], (
            "a deferred declaration left the performance / tech page"
        )
    assert normalized(view["departure"]["weather"]["metar"]) in folded[4]
    assert normalized(view["destination"]["weather"]["metar"]) in folded[4]


def test_publication_gate_and_physical_scan_accept_the_new_format(briefing):
    view = briefing["view"]
    result = check_concise_pdf(
        briefing["path"], flight=briefing["flight"], view=view,
        airport_analysis=view["airport_pdf_analysis"],
        alternate_analysis=view["alternate_pdf_analysis"],
    )
    assert result["valid"], result["violations"]
    assert result["page_count"] == 6
    physical = scan_physical_pdf(briefing["path"])
    assert physical["valid"], physical["violations"][:4]
    with fitz.open(briefing["path"]) as document:
        for page in document:
            for block in page.get_text("dict")["blocks"]:
                for line in block.get("lines", []):
                    for span in line["spans"]:
                        assert span["size"] >= 8.9, span["text"]


def test_a_saved_pack_cannot_keep_serving_the_cached_nine_page_pdf():
    """His test path is 'open the saved pack, press Download PDF'.

    ``COMBINED_BRIEFING_SCHEMA_VERSION`` is the only version input to the
    report-file cache key, and ``REPORT_DIR/flight_<id>_combined_<token>.pdf``
    lives on the persistent ODSS data volume. A publication contract that goes
    from nine pages to six without bumping it serves him the old nine-page
    file for every flight he had already rendered - "you keep saying fixed and
    when I test it doesn't work".
    """
    assert COMBINED_BRIEFING_SCHEMA_VERSION != NINE_PAGE_SCHEMA_VERSION
    snapshot = "an-analysis-snapshot-that-did-not-change"
    assert combined_briefing_cache_token(snapshot, 7) != combined_briefing_cache_token(
        snapshot, 7, schema_version=NINE_PAGE_SCHEMA_VERSION
    )


def test_no_page_copies_a_raw_deferred_source_remark(briefing):
    """'by copying in blocks and capital is very hard to read' - 9 Sep 21:28.

    The analysed consequence for every deferred item is published on the
    performance / technical page. A short defect-only continuation can be a
    subject with its consequence; maintenance/form instruction blocks cannot.
    """
    for item_index, item in enumerate(briefing["flight"].get("deferred_items") or []):
        remark = normalized(item.get("company_remark"))
        if len(remark.split()) < 8:
            continue
        for index, folded in enumerate(briefing["folded"]):
            if remark not in folded:
                continue
            # Independent source oracle for the one corpus field containing a
            # complete defect rather than a maintenance instruction. The
            # malformed description itself must never be published instead.
            assert (briefing["key"], item_index, remark) == (
                "SQ605", 2, "AFT GALLEY LH WASTE CONTAINER DOOR IN GALLEY LATCH MISSING"
            ), f"page {index + 1} copied a source instruction: {remark}"
            assert index in (1, 2)
            assert folded.count(remark) == 1
            assert str(item["company_remark"]) not in " ".join(briefing["pages"][index].split())
            assert "WASTE CONTAINER DOOR RETENTION NEEDS A PERMITTED CONFIGURATION DECISION" in folded
            assert "DOES NOT ESTABLISH AN ACCEPTABLE SECURING METHOD OR PERMISSION TO USE IT" in folded


def test_the_gate_rejects_a_copied_source_remark_on_the_decision_page(briefing, tmp_path):
    """The check that exists to stop this must cover the page it lands on."""
    remarks = [
        str(item.get("company_remark"))
        for item in briefing["flight"].get("deferred_items") or []
        if len(normalized(item.get("company_remark")).split()) >= 8
    ]
    if not remarks:
        pytest.skip("this flight holds no long deferred source remark")
    stamped = tmp_path / "remark-stamped.pdf"
    with fitz.open(briefing["path"]) as document:
        document[1].insert_text(
            (40, 330), remarks[0], fontsize=9.0, fontname="helv",
        )
        document.save(stamped)
    codes = [
        violation["code"]
        for violation in check_concise_pdf(stamped, flight=briefing["flight"], view=briefing["view"])["violations"]
    ]
    assert "COPIED_DEFERRED_REMARK" in codes


def test_analysed_prose_saying_review_required_is_not_an_item_badge(briefing):
    """Real analysed prose ends '...; review required.' on most corpus flights.

    Switching the whole item-badge check off for page 2 whenever that wording
    appears is a weakened gate, not a more precise one.
    """
    if briefing["key"] == "SQ882":
        # Keeps this case honest: if the engine ever stops publishing the
        # wording, the test stops proving anything and must be re-pointed.
        assert re.search(r"\breview required\b", briefing["pages"][1]), (
            "SQ882 is in this suite because its analysed page-2 prose says "
            "'...; review required.' - re-point this case if that changes"
        )
    view = briefing["view"]
    with_view = check_concise_pdf(
        briefing["path"], flight=briefing["flight"], view=view,
        airport_analysis=view["airport_pdf_analysis"],
        alternate_analysis=view["alternate_pdf_analysis"],
    )
    # report_quality dispatches with the path alone; the gate must still work.
    without_view = check_concise_pdf(briefing["path"])
    for result in (with_view, without_view):
        assert not [
            violation for violation in result["violations"]
            if violation["code"] == "REPEATED_ITEM_WARNING"
        ], result["violations"]


def test_a_repeated_item_badge_on_page_two_is_still_rejected(briefing, tmp_path):
    """And the badge itself is caught, with or without the analysis view."""
    stamped = tmp_path / "badge-stamped.pdf"
    with fitz.open(briefing["path"]) as document:
        document[1].insert_text(
            (40, 330), "CDDL REVIEW REQUIRED", fontsize=9.0, fontname="helv",
        )
        document.save(stamped)
    view = briefing["view"]
    calls = (
        {},
        {
            "flight": briefing["flight"], "view": view,
            "airport_analysis": view["airport_pdf_analysis"],
            "alternate_analysis": view["alternate_pdf_analysis"],
        },
    )
    for kwargs in calls:
        codes = [
            violation["code"]
            for violation in check_concise_pdf(stamped, **kwargs)["violations"]
        ]
        assert "REPEATED_ITEM_WARNING" in codes, codes


def test_the_release_caveat_from_the_nine_page_brief_is_still_published(briefing):
    """Relocated, not deleted: the caveat now sits with the release record."""
    assert normalized(RELEASE_CAVEAT) in briefing["folded"][5]


def test_the_analysed_surface_consequence_count_is_still_published(briefing):
    """The nine-page ARRIVAL SURFACE card counted them; page 1 still does."""
    for role in ("departure", "destination"):
        analysed = next(
            item for item in briefing["view"]["airport_pdf_analysis"]
            if item["role"] == role
        )
        assert normalized(
            f"{len(analysed['lines'])} analysed surface/approach consequence(s)"
        ) in briefing["folded"][0], role


def test_the_vws_threshold_summary_is_still_published(briefing):
    """``vws_events or [vws_summary]`` dropped it whenever events existed."""
    vws = (briefing["view"].get("terrain") or {}).get("vws_review") or {}
    summary = (
        f"{int(vws.get('event_count') or 0)} event(s) at the analysed "
        f"{published_value(vws.get('threshold'))} threshold. Maximum "
        f"{published_value(vws.get('maximum_display'))} at "
        f"{published_value(vws.get('maximum_waypoint'))}, ACTM "
        f"{published_value(vws.get('maximum_actm_display'))}."
    )
    assert normalized(summary) in briefing["folded"][5]


def _deferred_finding(briefing) -> dict:
    """The ranked deferred-declaration card on the DECISION ANALYSIS page."""
    return next(
        (
            finding
            for finding in briefing["view"].get("decision_findings") or []
            if str(finding.get("engine") or "") == "deferred_dispatch_gate"
        ),
        {},
    )


def _material_gate(briefing, finding) -> dict:
    """The gate the ranked card was built from, found by its published tag."""
    reference = str(finding.get("source_reference") or "")
    for gate in briefing["view"].get("deferred_dispatch_gates") or []:
        declarations = [
            str(segment.get("source_declaration") or "").strip()
            for segment in gate.get("source_segments") or []
        ]
        if declarations and all(
            declaration and declaration in reference for declaration in declarations
        ):
            return gate
    return {}


def _subjects_of(gate) -> list[str]:
    from app.odss.analysed_briefing_content import deferred_source_subject

    return [
        subject
        for segment in gate.get("source_segments") or []
        if (
            subject := deferred_source_subject(segment, gate.get("title")).rstrip(" .;")
        )
    ]


def test_the_decision_card_says_what_is_wrong_with_the_aircraft(briefing):
    """His reference card names the defect; ours named a document number.

    ``SQ910_21AUG2026_Flight_Briefing.pdf`` page 2 publishes this same item as
    "Engine 2 latch is a release gate - The aft-most fan-cowl latch
    access-panel latch is loose. HST is applied; the condition is to be checked
    before every departure", tagged "CFP p1 / IN SIA/00-017 R1". Ours printed
    "IN SIA/00-017 R1 - dispatch confirmation" over a consequence sentence,
    with no statement of the defect anywhere in the six pages. The answer to
    "by copying in blocks and capital is very hard to read" (9 Sep 21:28) is
    sentence case, not deletion of the subject.
    """
    if not (briefing["view"].get("deferred_dispatch_gates") or []):
        pytest.skip("this flight holds no deferred declaration")
    from app.odss.analysed_briefing_content import deferred_item_label

    finding = _deferred_finding(briefing)
    assert finding, "a deferred declaration must reach the ranked decision page"
    gate = _material_gate(briefing, finding)
    assert gate, "the ranked card must name the declaration it came from"
    headline = str(finding.get("title") or "")
    subjects = _subjects_of(gate)
    assert subjects, "the ranked source-bound declaration must identify its defect"
    assert any(subject in headline for subject in subjects), (
        f"the decision card headline names no defect: {headline!r}"
    )
    # It is on the page he circled in green, not only in the view.
    assert normalized(headline) in briefing["folded"][1], headline
    # ...and it is analysed text, never the declaration's block capitals.
    card = f"{headline} {finding.get('summary')}"
    for gate in briefing["view"]["deferred_dispatch_gates"]:
        for segment in gate.get("source_segments") or []:
            description = " ".join(str(segment.get("description") or "").split())
            if description.isupper() and len(description.split()) >= 2:
                assert description not in card, description


def test_every_deferred_defect_is_published_in_sentence_case(briefing):
    """Relocated, not deleted - and readable where it lands.

    Round 2 dropped the subject for every declaration whose effect a rule could
    analyse, which is most of them. Each one the source states as a self-
    contained defect is published again, cased, on the page that owns it.
    """
    from app.odss.analysed_briefing_content import (deferred_consequence_rows,
                                                    deferred_source_subject)

    body = " ".join(briefing["folded"])
    rows = deferred_consequence_rows(briefing["view"])
    analysed = " ".join(row["text"] for row in rows)
    published = {row["subject"] for row in rows if row["subject"]}
    for gate in briefing["view"].get("deferred_dispatch_gates") or []:
        for segment in gate.get("source_segments") or []:
            description = " ".join(str(segment.get("description") or "").split())
            subject = deferred_source_subject(segment, gate.get("title")).rstrip(" .;")
            if not subject:
                continue
            assert any(subject in value for value in published), (
                f"the analysed projection does not say what is wrong with the "
                f"aircraft: {subject!r}"
            )
            assert normalized(subject) in body, f"no page publishes it: {subject!r}"
            if description.rstrip(" .;") != subject:
                assert description.rstrip(" .;") not in analysed, description


# Lower-case forms that can only be a destroyed abbreviation. Each one is a
# whole word in the published text, so an ordinary English word that merely
# contains the letters (for example "melt", "catering") cannot match.
DESTROYED_ABBREVIATIONS = (
    "mel", "cdl", "cddl", "nef", "ecp", "ils", "cat", "tcas", "gpu", "irs",
    "egt", "efb", "aog", "vhf", "emer", "acrft", "inop", "req", "fwd", "acars",
    "adiru", "eicas", "ecam", "etops", "edto", "metar", "sigmet", "notam",
    "intam", "atis", "autoland", "pax", "lav", "apu", "vcru", "wac", "jcl",
    "ycl", "pdu", "mlg", "avncs", "hst", "rwy", "zfw", "rtow", "mtow", "eosid",
)


def test_no_page_lowercases_an_operational_abbreviation(briefing):
    """The casing rule must not answer block capitals by destroying shorthand.

    Round 3 lowered any word that carried a vowel and was not on a 25-item
    allowlist, so "SECTION MEL AND CMS REV 18NOV 25" published "mel" and
    "NON-ESSENTIAL EQUIPMENT AND NEF" published "nef" - on the page he circled
    in green, on flights he personally tested.
    """
    body = "\n".join(briefing["pages"])
    for abbreviation in DESTROYED_ABBREVIATIONS:
        hit = re.search(rf"(?<![A-Za-z]){abbreviation}(?![A-Za-z])", body)
        assert not hit, (
            f"{abbreviation!r} is published in lower case: "
            f"{body[max(0, hit.start() - 60):hit.end() + 60]!r}"
        )


# Tokens that leave a phrase open, restated here rather than imported so the
# test is not the implementation asserting itself.
OPEN_TAIL = {
    "a", "an", "the", "and", "or", "as", "at", "by", "for", "from", "in",
    "into", "of", "on", "onto", "over", "per", "to", "under", "upon", "via",
    "with", "within", "than", "that", "which", "when", "while", "if", "due",
    "both", "each", "all", "any", "no", "not", "is", "are", "was", "were",
    "be", "been", "has", "have", "had", "will", "must", "may", "can", "x",
    "found", "noted", "reported", "observed", "suspected", "chilling",
}


def test_no_published_deferred_subject_is_truncated_duplicated_or_form_debris(briefing):
    """A published subject has to be a statement, not a slice of a form cell.

    The OFP's deferred table wraps its description cell into the company-remark
    cell, writes the selected drop-down twice and leaves "OTHERS (PLS ENTER
    COMMENTS)" behind. Round 3 published that cell unconditionally, so page 2
    carried a headline ending "removed as per" and page 3 carried "Trash
    compactor, trash compactor, others (PLS enter comments)". His 9 Sep 20:52
    was "Why are the MEL/CDL content repeated?" and 21:23 "This is also rubbish
    generated".
    """
    from app.odss.analysed_briefing_content import deferred_consequence_rows

    subjects = [
        row["subject"]
        for row in deferred_consequence_rows(briefing["view"])
        if row["subject"]
    ]
    finding = _deferred_finding(briefing)
    headline = str(finding.get("title") or "").removesuffix(" - dispatch confirmation")
    for subject in [*subjects, *([headline] if headline else [])]:
        words = re.findall(r"[A-Za-z0-9]+", subject)
        assert words, subject
        assert subject[0].isalnum(), f"starts mid-cell: {subject!r}"
        assert subject.count("(") == subject.count(")"), f"unbalanced: {subject!r}"
        assert subject.rstrip()[-1] not in ",;:/-&+(", f"cut short: {subject!r}"
        trailing = re.search(r"(?:^|[^A-Za-z0-9])([A-Za-z]+)\s*$", subject)
        if trailing:
            assert trailing.group(1).lower() not in OPEN_TAIL, (
                f"ends mid-sentence: {subject!r}"
            )
        assert not re.search(
            r"\(\s*(?:PLS|PLEASE)\b|\bENTER\s+COMMENTS?\b", subject, re.I
        ), f"form placeholder: {subject!r}"
        # No phrase is published twice inside one subject.
        segments = [
            " ".join(re.findall(r"[A-Za-z0-9]+", part)).lower()
            for part in re.split(r"\s*[,;]\s*|\s+X\s+", subject)
        ]
        segments = [segment for segment in segments if segment]
        assert len(segments) == len(set(segments)), f"repeated segment: {subject!r}"


def test_the_named_source_cells_are_not_published_as_defects(briefing):
    """The reviewer's own strings, on the flights they were measured on.

    Compared with the letter case the page actually draws, not folded: the
    declaration reference "MEL PREAMBLE SECTION MEL AND CMS REV 18NOV 25" is
    provenance and is meant to be there in capitals; "Section mel and CMS rev
    18NOV 25" as a sentence is the defect.
    """
    body = re.sub(r"\s+", " ", "\n".join(briefing["pages"]))
    for fragment in (
        "Both VCRU (101HW & 103HW) removed as per",
        "Found LH inner wing leading edge DND fixed seal with",
        "LH wing, slat #6 lower seal found",
    ):
        assert not re.search(re.escape(fragment) + r"\s*(?:[.;]|- dispatch confirmation)", body), fragment
    for fragment in (
        "Trash compactor, trash compactor",
        "others (PLS enter comments)",
        "- galley waste compartment access door installed)",
        "Section mel and CMS rev 18NOV 25",
    ):
        assert fragment not in body, fragment


def test_the_status_release_gate_still_names_the_deferred_defect(briefing):
    """The web release gate lost the defect identity in round 2 as well.

    BEFORE PUSH on page 1 and the app's STATUS gate read from this row; a
    detail that carries only the consequence does not say what is deferred.
    """
    if not (briefing["view"].get("deferred_dispatch_gates") or []):
        pytest.skip("this flight holds no deferred declaration")
    finding = _deferred_finding(briefing)
    status = next(
        gate
        for gate in briefing["view"]["release_gates"]
        if gate["label"] == "STATUS"
    )
    assert str(finding.get("title") or "") in status["detail"]
    assert str(finding.get("summary") or "") in status["detail"]
    subjects = _subjects_of(_material_gate(briefing, finding))
    assert subjects, "STATUS must not pass with a content-free paperwork fallback"
    assert any(subject in status["detail"] for subject in subjects)


def test_the_sq910_card_names_the_engine_2_fan_cowl_latch(briefing):
    """The exact strings a reader searched his own flight for and did not find."""
    if briefing["key"] != "SQ910":
        pytest.skip("his reference briefing was made from the SQ910 21 Aug OFP")
    body = "\n".join(briefing["pages"])
    for phrase in ("eng 2", "fan cowl", "latch", "hst"):
        assert phrase in body.lower(), phrase
    defect = "ENG 2 fan cowls latch access panel aft-most latch is loose"
    # The card itself, free of line wrapping, and the page it is drawn on.
    assert _deferred_finding(briefing)["title"] == f"{defect} - dispatch confirmation"
    assert normalized(defect) in briefing["folded"][1]
    # Round 1 named it in the source's block capitals, which he objected to.
    assert "ENG 2 FAN COWLS LATCH" not in body
    # ...and "ENG" is not "Eng": an abbreviation keeps the source's capitals.
    assert "Eng 2 fan cowls" not in body
    # Round 2's fix stands: the company remark itself is still not republished.
    assert normalized(
        "HST APPLIED, CONDITION TO BE CHECKED PRIOR EVERY DEPARTURE TO APPLY "
        "WHENEVER NECESSARY"
    ) not in " ".join(briefing["folded"])


def test_page_one_weather_fields_are_his_trimmed_groups_with_the_local_clock(briefing):
    """B4 fix round 1 (17 Sep 2026): page 1 printed the OFP record envelope.

    His page 1 reads ``METAR 11004KT 9999 FEW018`` / ``TAF 16008KT 9999
    FEW015/SCT020`` / ``SCHEDULE 0050Z / 0850 LT``; ours read ``SA 201900
    11004KT 9999 FEW018 BKN300 28/23 Q1011 NOSIG=`` and ``0050Z / 21AUG26``.
    The trim rule is shared with the dashboard (page_one_weather.py ==
    page1-weather.mjs, pinned by tests/fixtures/page1-weather-vectors.json),
    so both surfaces print the same groups for the same held record.
    """
    from app.odss.page_one_weather import held_text, page_one_metar_field, page_one_taf_field

    page = briefing["folded"][0]
    view = briefing["view"]
    for role in ("departure", "destination"):
        weather = (view.get(role) or {}).get("weather") or {}
        metar = weather.get("metar")
        if metar:
            assert normalized(page_one_metar_field(metar, "WEATHER page")) in page, f"{role} METAR in his form"
            envelope = " ".join(held_text(metar).split()[:2])
            assert normalized(envelope) not in page, f"{role} METAR envelope {envelope} is not on page 1"
        if role == "departure" and weather.get("taf"):
            assert normalized(page_one_taf_field(weather["taf"], "WEATHER page")) in page, "departure TAF in his form"
    assert normalized("SCHEDULE") in page
    assert re.search(r"SCHEDULE \d{4}Z (?:\d{4} LT|LT NOT HELD)", page), "SCHEDULE is the UTC clock beside the local one"
    if briefing["key"] == "SQ910":
        for expected in ("11004KT 9999 FEW018/BKN300", "16008KT 9999 FEW015/SCT020",
                         "VRB02KT 9999 FEW025", "0050Z / 0850 LT"):
            assert normalized(expected) in page, expected
        body = page.replace(normalized("SQ910 | 21AUG26"), "")
        for gone in ("SA 201900", "FT 201700", "2018/2200", "NOSIG", "Q1011", "RMK A2983", "0050Z / 21AUG26"):
            assert normalized(gone) not in body, gone


RECOVERED_DEFECTS = {
    "SQ214": ("Both VCRU (101HW & 103HW) removed as per MAF 23224", "Can't feed waste"),
    "SQ297": ("fixed seal with 2.5CM torn", "all galley chillers working intermittent"),
    "SQ882-10Sep": ("slat #6 lower seal found deteriorated", "air chiller not cold"),
    "SQ366": ("potable water ice protection", "SYTEM INOP"),
    "SQ605": ("waste container door", "latch missing"),
}


def test_complete_source_continuations_are_visible_in_the_actual_download(briefing):
    """Independent source anchors: no helper-generated expected value or empty-subject escape."""
    if briefing['key'] not in RECOVERED_DEFECTS:
        pytest.skip('no formerly truncated subject in this source case')
    body = ' '.join(briefing['folded'])
    for fact in RECOVERED_DEFECTS[briefing['key']]:
        assert normalized(fact) in body, f"{briefing['key']} download omitted held defect: {fact}"


@pytest.mark.parametrize('mutation', ['uppercase-copy', 'cased-copy', 'source-loss', 'consequence-loss', 'unrelated-owner'])
def test_sq605_source_subject_exception_cannot_hide_physical_corruption(mutation, tmp_path_factory, tmp_path):
    """Use the real six-page download and the view supplied to publication."""
    import copy

    brief = rendered('SQ605', tmp_path_factory)
    subject = 'Aft galley LH waste container door in galley latch missing'
    view = copy.deepcopy(brief['view'])
    path = tmp_path / f'{mutation}.pdf'
    with fitz.open(brief['path']) as document:
        if mutation in ('uppercase-copy', 'cased-copy'):
            value = subject.upper() if mutation == 'uppercase-copy' else subject
            document[1].insert_text((40, 500), value, fontsize=9, fontname='helv')
        elif mutation in ('source-loss', 'consequence-loss'):
            needle = subject if mutation == 'source-loss' else 'securing'
            hits = document[2].search_for(needle)
            assert hits, f'physical mutation did not find {needle}'
            for hit in hits:
                document[2].add_redact_annot(hit)
            document[2].apply_redactions()
        else:
            row = next(row for row in view['deferred_pdf_analysis'] if row['source_item_indices'] == [2])
            row['source_item_indices'] = [1]
        document.save(path)
    if mutation == 'consequence-loss':
        with fitz.open(path) as document:
            assert normalized(subject) in normalized(document[2].get_text())
    codes = {item['code'] for item in check_concise_pdf(path, flight=brief['flight'], view=view)['violations']}
    expected = 'DEFERRED_CONSEQUENCE_PARITY' if mutation == 'source-loss' else 'COPIED_DEFERRED_REMARK'
    assert expected in codes, (mutation, codes)
