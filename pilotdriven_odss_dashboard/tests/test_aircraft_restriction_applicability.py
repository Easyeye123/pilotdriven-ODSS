"""Code E (audit C23): the ODSS evaluator of the shared aircraft-size rules.

The vectors and the rules JSON are byte-identical copies of the app's files
(tests/fixtures/aircraft-restriction-vectors.json and aircraft-restriction-rules.json
in pilotdriven-notam-briefing). The digests below are pinned in BOTH suites: if
one side changes without the other, the dashboard and the PDF would be
evaluating different rules, and one of the two suites fails.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest

from app.odss import aircraft_restriction_applicability as rule

RULES_FILE = Path(rule.__file__).with_name("aircraft_restriction_rules.json")
VECTORS_FILE = Path(__file__).parent / "fixtures" / "aircraft-restriction-vectors.json"
SHARED_RULES_SHA256 = "8667d3ea732cbfeb0e5f202cf32ab154e396e05e40f21d0c1d229b46e60eaa4d"
SHARED_VECTORS_SHA256 = "9d6f40c1871200a98baec563a8e74c70309fd13d1362c18fb500be7527886003"

VECTORS = json.loads(VECTORS_FILE.read_text(encoding="utf-8"))

PERMISSION_WORDING = re.compile(
    r"\b(?:cleared|clear to|approved|permitted|authori[sz]ed|may (?:taxi|land|use)|available to this aircraft)\b",
    re.IGNORECASE,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_shared_files_are_the_apps_bytes() -> None:
    assert _sha256(RULES_FILE) == SHARED_RULES_SHA256
    assert _sha256(VECTORS_FILE) == SHARED_VECTORS_SHA256
    assert VECTORS["specVersion"] == rule.spec_version()


@pytest.mark.parametrize("row", VECTORS["codeLetterBoundaries"], ids=lambda row: str(row["wingspanM"]))
def test_code_letter_bands_are_up_to_but_not_including(row: dict) -> None:
    assert rule.aerodrome_code_letter_for_wingspan(row["wingspanM"]) == row["code"]


def test_every_catalogue_aircraft_agrees_with_the_icao_table() -> None:
    aircraft = rule.rules()["aircraft"]
    assert [entry["ruleId"] for entry in aircraft] == [
        "AIRBUS_A350_900_ICAO_CODE_E_V1",
        "AIRBUS_A380_800_ICAO_CODE_F_V1",
        "BOEING_787_10_ICAO_CODE_E_V1",
        "BOEING_737_8_ICAO_CODE_C_V1",
    ]
    for entry in aircraft:
        assert rule.aerodrome_code_letter_for_wingspan(entry["wingspanM"]) == entry["code"]
        for alias in entry["aliases"]:
            assert rule.assess_aircraft_aerodrome_code(alias)["code"] == entry["code"]


@pytest.mark.parametrize("aircraft_type", ["A350-1041", "A35K", "B77W", "B779", "B787-9", "737-800", "A380", ""])
def test_types_outside_the_catalogue_stay_unknown(aircraft_type: str) -> None:
    held = rule.assess_aircraft_aerodrome_code(aircraft_type)
    assert held["status"] == "unknown"
    assert held["code"] is None


@pytest.mark.parametrize("vector", VECTORS["vectors"], ids=lambda vector: vector["id"])
def test_shared_vector(vector: dict) -> None:
    result = rule.assess_aircraft_restriction_applicability(
        vector["noticeText"],
        vector["aircraftType"],
        explicit_governed_code=vector.get("explicitGovernedCode"),
    )
    expected = vector["expect"]
    if expected is None:
        assert result is None, "no aircraft-size limit may be read from this notice"
        return
    assert result is not None
    restriction = result["restriction"] or {}
    assert result["status"] == expected["status"]
    assert result["outcome"] == expected["outcome"]
    assert result["restrictsThisAircraft"] is expected["restrictsThisAircraft"]
    assert result["reason"] == expected["reason"]
    assert restriction.get("formId") == expected["formId"]
    assert restriction.get("semantics") == expected["semantics"]
    assert restriction.get("limitLabel") == expected["limitLabel"]
    assert result["aircraft"]["code"] == expected["aircraftCode"]
    assert result["aircraft"]["ruleId"] == expected["aircraftRuleId"]
    if "sentence" in expected:
        assert result["sentence"] == expected["sentence"]
    if "otherConditionIds" in expected:
        assert [entry["id"] for entry in restriction["otherConditions"]] == expected["otherConditionIds"]
    if "comparisonRelation" in expected:
        assert (result["comparison"] or {}).get("relation") == expected["comparisonRelation"]
    if "comparisonBasis" in expected:
        assert result["comparison"]["basis"] == expected["comparisonBasis"]
    if "conditionTexts" in expected:
        # The notice's OWN condition words, not a label for them.
        assert [entry["text"] for entry in restriction["otherConditions"]] == expected["conditionTexts"]
        for text in expected["conditionTexts"][:2]:
            assert f'"{text}"' in result["sentence"]
        assert not re.search(
            r"excludes this aircraft|applies to this aircraft|within this limit|outside the restricted class",
            result["sentence"],
        )
        assert "was not decided" in result["sentence"]
    if "unreadGuard" in expected:
        assert (result["unread"] or {}).get("id") == expected["unreadGuard"]
        assert result["comparison"] is None, "an unread limit is never compared"
        assert result["restriction"] is None
    if result["status"] == "confirmed":
        assert restriction["otherConditions"] == [], "a conclusion is only ever drawn from an unconditional limit"
        assert result["unread"] is None
    assert result["operationalPermission"] is False
    # OUR words never grant anything; the notice's own quoted words are not ours.
    assert not PERMISSION_WORDING.search(re.sub(r'"[^"]*"', '""', result["sentence"]))
    if result["outcome"] in {"within_limit", "outside_restricted_class"}:
        assert "not a clearance" in result["sentence"]
    if result["status"] != "confirmed":
        assert result["outcome"] is None


def test_notam_record_helper_uses_the_ofp_aircraft_and_the_whole_item_e() -> None:
    flight = {"aircraft_type": "A350-941"}
    item = {"notam_id": "1A1868/26", "item_e_text": "TWY E BTN TWY F5 AND TWY F6 DOWNGRADED TO CODE E DUE WIP"}
    check = rule.notam_aircraft_size_check(flight, item)
    assert check["outcome"] == "within_limit"
    assert check["aircraft"]["typeSource"] == "uploaded_ofp"
    assert rule.notam_aircraft_size_check({"aircraft_type": "A380-841"}, item)["outcome"] == "exceeds_limit"
    assert rule.notam_aircraft_size_check({}, item)["status"] == "unknown"
    assert rule.notam_aircraft_size_check(flight, {"item_e_text": "ILS RWY 07R U/S"}) is None
    assert rule.notam_aircraft_size_check(flight, {"item_e_text": ""}) is None


# --- Publication: the same comparison reaches the card line and the Decision Analysis card ---

_VHHH_ITEM = {
    "notam_id": "1A1868/26",
    "location": "VHHH",
    "category": "AIRPORT",
    "item_e_text": "TWY E BTN TWY F5 AND TWY F6 DOWNGRADED TO CODE E DUE WIP",
    "summary": "TWY E between TWY F5 and TWY F6 downgraded to code E due to work in progress.",
    "pertinence_kind": "taxiway_restriction",
    "pertinence_rank": 6,
    "severity": "warning",
    "applicability": "active",
    "role": "destination",
    "source_page": 28,
}


def _destination_lines(aircraft_type: str, item_e_text: str | None = None) -> list[dict]:
    from app.odss.briefing import _compact_notam_lines

    item = dict(_VHHH_ITEM)
    if item_e_text:
        item["item_e_text"] = item_e_text
    check = rule.notam_aircraft_size_check({"aircraft_type": aircraft_type}, item)
    if check:
        item["aircraft_size_check"] = check
    return _compact_notam_lines([item], "destination")


def _arrival_ground_summary(aircraft_type: str, item_e_text: str | None = None) -> str:
    from app.odss.briefing import _decision_finding_projection

    projected = _decision_finding_projection(
        [],
        airport_panels=[{
            "icao": "VHHH",
            "role_keys": ["destination"],
            "card_summary_lines": _destination_lines(aircraft_type, item_e_text),
            "selected_notams": [],
        }],
    )
    cards = [row for row in projected if row["engine"] == "arrival_ground"]
    assert len(cards) == 1
    return cards[0]["summary"]


def test_card_line_keeps_the_notice_statement_and_carries_the_comparison_beside_it() -> None:
    (line,) = _destination_lines("A350-941")
    # The line itself is still only what the notice states ...
    assert line["text"] == _VHHH_ITEM["summary"]
    # ... and the comparison travels with it as structured data.
    assert line["aircraft_size_check"]["outcome"] == "within_limit"
    assert line["aircraft_size_check"]["operationalPermission"] is False


def test_decision_analysis_card_states_the_comparison_for_the_ofp_aircraft() -> None:
    summary = _arrival_ground_summary("A350-941")
    assert "downgraded to code E" in summary
    assert "A350-941 is Code E (64.75 m wingspan): within this limit (Code E)." in summary
    assert "not a clearance" in summary
    assert not PERMISSION_WORDING.search(summary)


def test_decision_analysis_card_changes_with_the_aircraft_and_never_guesses() -> None:
    assert "A380-841 is Code F (79.75 m wingspan): above this limit (Code E)" in _arrival_ground_summary("A380-841")
    unverified = _arrival_ground_summary("B777-312ER")
    assert "was not compared: no verified size data is held for B777-312ER" in unverified
    assert "within this limit" not in unverified and "above this limit" not in unverified


def test_a_notice_without_a_size_limit_publishes_exactly_what_it_did_before() -> None:
    from app.odss.briefing import _compact_notam_lines

    item = {**_VHHH_ITEM, "item_e_text": "TWY E BTN TWY F5 AND TWY F6 CLSD DUE WIP",
            "summary": "TWY E between TWY F5 and TWY F6 closed due to work in progress.",
            "pertinence_kind": "taxiway_closure"}
    assert rule.notam_aircraft_size_check({"aircraft_type": "A350-941"}, item) is None
    (line,) = _compact_notam_lines([item], "destination")
    assert "aircraft_size_check" not in line


# --- Codex independent review, 22 Sep 2026: propagation of withheld conclusions (synthetic wordings) ---

@pytest.mark.parametrize("item_e_text", [
    "TWY A LTD TO MAX ACFT CODE C EXC A350 ACFT",
    "TWY A LTD TO MAX ACFT CODE C WHEN LVP IN FORCE",
    "TWY A LTD TO MAX ACFT CODE C. THIS RESTRICTION APPLIES ONLY WHEN LVP IN FORCE. CTC APRON CONTROL.",
    # Codex fix2 review: the qualifier follows the limit, in its own sentence or the next.
    "TWY A LTD TO MAX ACFT CODE C. THIS LIMIT DOES NOT APPLY TO A350 ACFT.",
    "TWY A LTD TO MAX ACFT CODE C. A350 ACFT ARE EXEMPT.",
    "TWY A LTD TO MAX ACFT CODE C NOT APPLICABLE TO A350 ACFT.",
])
def test_decision_card_never_concludes_from_an_unresolved_condition(item_e_text: str) -> None:
    (line,) = _destination_lines("A350-941", item_e_text)
    check = line["aircraft_size_check"]
    assert check["status"] == "review_required"
    assert check["outcome"] is None and check["restrictsThisAircraft"] is None
    assert check["comparison"] == {"relation": "exceeds_limit", "basis": "aircraft_code_above_maximum"}

    summary = _arrival_ground_summary("A350-941", item_e_text)
    assert "above the stated limit (Code C)" in summary
    assert "was not decided" in summary
    assert "excludes this aircraft" not in summary
    quoted = check["restriction"]["otherConditions"][0]["text"]
    assert f'"{quoted}"' in summary, "the card must carry the notice's own condition words"


@pytest.mark.parametrize("aircraft_type,item_e_text,forbidden", [
    ("A380-841", "TWY A CLSD FOR ACFT CODE E AND F", "outside the restricted class"),
    ("A350-941", "TWY A NOT RESTRICTED TO MAX ACFT CODE C", "excludes this aircraft"),
])
def test_decision_card_never_publishes_a_partial_reading(aircraft_type: str, item_e_text: str, forbidden: str) -> None:
    summary = _arrival_ground_summary(aircraft_type, item_e_text)
    assert "do not fully read" in summary and "was not compared" in summary
    assert forbidden not in summary


def test_quoted_condition_words_cannot_trip_the_copy_invariant() -> None:
    """The publication gate deletes a PDF whose line copies 18 source words; a quote is bounded to 12."""
    from app.odss.notam_restriction_line import copies_its_source

    notice = (
        "TWY A LTD TO MAX ACFT CODE C WHEN LOW VISIBILITY PROCEDURES ARE IN FORCE AND THE FOLLOW ME VEHICLE IS NOT "
        "AVAILABLE AT THE HOLDING POINT OF RUNWAY 07R OR WHEN DIRECTED BY APRON CONTROL ON FREQUENCY 121.9"
    )
    check = rule.assess_aircraft_restriction_applicability(notice, "A350-941")
    assert check["reason"] == "unresolved_condition_in_notice"
    for condition in check["restriction"]["otherConditions"]:
        assert len(condition["text"].split(" ")) <= 12
    assert not copies_its_source(notice, check["sentence"])


# --- Codex live QA, 22 Sep 2026: a confirmed aircraft exclusion must reach the real PDF ---

def _panel(*items: dict, summary_ids: tuple[str, ...] = ()) -> dict:
    from app.odss.briefing import _compact_notam_family

    selected = []
    for item in items:
        held = dict(item)
        held.setdefault("signal_family", _compact_notam_family(held))
        held.setdefault("compact_text", held.get("summary"))
        selected.append(held)
    return {
        "icao": "EDDF",
        "role_keys": ["destination"],
        "selected_notams": selected,
        "card_summary_lines": [
            {"kind": "notam", "label": row["notam_id"], "notam_id": row["notam_id"], "text": row["compact_text"],
             "signal_family": row["signal_family"], "source_page": row.get("source_page"),
             **({"aircraft_size_check": row["aircraft_size_check"]} if row.get("aircraft_size_check") else {})}
            for row in selected if row["notam_id"] in summary_ids
        ],
    }


def _notice(notam_id: str, item_e_text: str, summary: str, aircraft_type: str, **extra) -> dict:
    item = {
        "notam_id": notam_id, "item_e_text": item_e_text, "summary": summary,
        "pertinence_kind": extra.pop("pertinence_kind", "taxiway_restriction"), "pertinence_rank": 6,
        "severity": "warning", "applicability": "active", "stateAtReference": "active_at_reference",
        "role": "destination", "source_page": 30, **extra,
    }
    check = rule.notam_aircraft_size_check({"aircraft_type": aircraft_type}, item)
    if check:
        item["aircraft_size_check"] = check
    return item


def _ground_card(panel: dict) -> str:
    from app.odss.briefing import _decision_finding_projection

    cards = [row for row in _decision_finding_projection([], airport_panels=[panel]) if row["engine"] == "arrival_ground"]
    return cards[0]["summary"] if cards else ""


_CLOSURE = dict(notam_id="A3047/26", item_e_text="TWY W CLSD", summary="TWY W closed during the applicable destination window.",
                pertinence_kind="taxiway_closure")


def test_a_confirmed_exclusion_survives_the_one_notice_per_family_cap() -> None:
    """SQ326's shape: the taxiway slot went to a closure, and the Code C limit that
    excludes the A380 was dropped from the card although its row carried it."""
    closure = _notice(aircraft_type="A380-841", **_CLOSURE)
    limit = _notice("A3671/26", "TWY L20 LTD TO MAX ACFT TYPE CODE C.", "TWY L20 limited to max aircraft type code C.", "A380-841")
    card = _ground_card(_panel(closure, limit, summary_ids=("A3047/26",)))
    assert "A3047/26 - TWY W closed" in card, "the existing line is not displaced"
    assert "A3671/26 - TWY L20 limited to max aircraft type code C." in card
    assert "A380-841 is Code F (79.75 m wingspan): above this limit (Code C)" in card


@pytest.mark.parametrize("aircraft_type", ["737-8", "B777-312ER"])
def test_changed_aircraft_is_not_promoted_when_nothing_is_concluded(aircraft_type: str) -> None:
    """Same notices, another aircraft: a Code C aircraft is within the limit and an
    unverified type concludes nothing, so neither is forced into the card."""
    closure = _notice(aircraft_type=aircraft_type, **_CLOSURE)
    limit = _notice("A3671/26", "TWY L20 LTD TO MAX ACFT TYPE CODE C.", "TWY L20 limited to max aircraft type code C.", aircraft_type)
    card = _ground_card(_panel(closure, limit, summary_ids=("A3047/26",)))
    assert "A3047/26" in card
    assert "A3671/26" not in card


def test_promotion_never_invents_applicability() -> None:
    limit = "TWY L20 LTD TO MAX ACFT TYPE CODE C"
    summary = "TWY L20 limited to max aircraft type code C."
    unresolved = _notice("A1/26", f"{limit} WHEN LVP IN FORCE", summary, "A380-841")
    ended = _notice("A2/26", limit, summary, "A380-841", stateAtReference="ended_before_reference")
    inactive = _notice("A3/26", limit, summary, "A380-841", applicability="not_applicable")
    departing = _notice("A4/26", f"FLIGHTS DEPARTING: {limit}", summary, "A380-841")
    lighting = _notice("A5/26", f"RWY 07C EDGE LGT U/S. {limit}", summary, "A380-841", pertinence_kind="runway_lighting_restriction",
                       signal_family="lighting")
    card = _ground_card(_panel(unresolved, ended, inactive, departing, lighting))
    assert card == "", card


def test_promotion_is_bounded_and_never_repeats_a_line_already_on_the_card() -> None:
    limits = [
        _notice(f"A90{index}/26", f"TWY L2{index} LTD TO MAX ACFT TYPE CODE C.", f"TWY L2{index} limited to code C.", "A380-841")
        for index in range(4)
    ]
    card = _ground_card(_panel(*limits, summary_ids=("A900/26",)))
    assert card.count("above this limit (Code C)") == 3, "one held line plus at most two promoted"
    assert card.count("A900/26") == 1


_SQ326 = Path(__file__).resolve().parents[2] / "private_cfp_corpus" / "lido-briefing_SQ_326_16Aug2026_SIN_FRA.pdf"


@pytest.mark.skipif(not _SQ326.exists(), reason="the private OFP corpus is not available")
@pytest.mark.parametrize("aircraft_type,expected,absent", [
    (None, "A380-841 is Code F (79.75 m wingspan): above this limit (Code C)", None),
    ("737-8", None, "A3671/26"),
])
def test_original_sq326_pdf_carries_the_exclusion_and_a_changed_aircraft_does_not(
    tmp_path: Path, aircraft_type: str | None, expected: str | None, absent: str | None,
) -> None:
    """The exact original OFP of the live finding, through the real analysis and the
    physical six-page PDF - and the same OFP with the aircraft changed."""
    import fitz

    from app.analysis import run_odss_analysis
    from app.odss.combined_brief import render_combined_briefing
    from app.odss.report_quality import validate_combined_briefing_pdf

    result = run_odss_analysis(_SQ326, tmp_path / "analysis", tmp_path / "legacy", 9326)
    payload = json.loads(Path(result["analysis_path"]).read_text(encoding="utf-8"))
    flight = payload["flight"] if aircraft_type is None else {**payload["flight"], "aircraft_type": aircraft_type}
    pdf = tmp_path / "SQ326.pdf"
    render_combined_briefing(
        flight, payload["findings"], payload.get("view", {}).get("warnings") or [], pdf,
        source_pdf_path=str(_SQ326), weather_charts=payload.get("weather_charts") or {},
        include_audit_appendix=False,
    )
    quality = validate_combined_briefing_pdf(pdf)
    assert quality["valid"], quality
    assert quality["page_count"] == 6, "the promoted line must not overflow the six-page layout"
    with fitz.open(pdf) as document:
        text = " ".join(" ".join(page.get_text().split()) for page in document)
    assert "EDDF arrival ground constraints" in text
    if expected:
        assert "A3671/26" in text
        assert expected in text
    if absent:
        assert absent not in text


def test_a_qualified_exclusion_is_never_promoted_into_the_pdf_card_and_an_unrelated_negation_changes_nothing() -> None:
    """Codex fix2 review. An exemption after the limit concludes nothing, so the
    promotion that carries CONFIRMED exclusions into the PDF must leave it out;
    a negation about another facility must not stop a clean exclusion being carried."""
    closure = _notice(aircraft_type="A380-841", **_CLOSURE)
    exempted = _notice("A3671/26", "TWY L20 LTD TO MAX ACFT TYPE CODE C. A380 ACFT ARE EXEMPT.",
                       "TWY L20 limited to max aircraft type code C.", "A380-841")
    assert exempted["aircraft_size_check"]["status"] == "review_required"
    assert "A3671/26" not in _ground_card(_panel(closure, exempted, summary_ids=("A3047/26",)))

    clean = _notice("A3671/26", "ILS RWY 25C NOT AVBL. TWY L20 LTD TO MAX ACFT TYPE CODE C.",
                    "TWY L20 limited to max aircraft type code C.", "A380-841")
    assert clean["aircraft_size_check"]["outcome"] == "exceeds_limit"
    assert "above this limit (Code C)" in _ground_card(_panel(closure, clean, summary_ids=("A3047/26",)))
