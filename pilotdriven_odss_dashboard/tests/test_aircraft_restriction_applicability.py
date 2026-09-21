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
SHARED_RULES_SHA256 = "951fd6125b7673cbd45b265cc186faa588bef0a98d4c02d3edebe1dfd8a4cbdf"
SHARED_VECTORS_SHA256 = "110aacef2c60c0cd1802a8018d6f1c0908156129e7d8464dab5746c935c83b50"

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
    assert result["operationalPermission"] is False
    assert not PERMISSION_WORDING.search(result["sentence"])
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


def _destination_lines(aircraft_type: str) -> list[dict]:
    from app.odss.briefing import _compact_notam_lines

    item = dict(_VHHH_ITEM)
    check = rule.notam_aircraft_size_check({"aircraft_type": aircraft_type}, item)
    if check:
        item["aircraft_size_check"] = check
    return _compact_notam_lines([item], "destination")


def _arrival_ground_summary(aircraft_type: str) -> str:
    from app.odss.briefing import _decision_finding_projection

    projected = _decision_finding_projection(
        [],
        airport_panels=[{
            "icao": "VHHH",
            "role_keys": ["destination"],
            "card_summary_lines": _destination_lines(aircraft_type),
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
