"""ITEM 3, Gatwick (14 Oct 2026): one timing decision for an OFP station notice.

"The briefing text, airport map and PDF still disagree about when the closure applies." The decision "is this notice
in force at this station's reference time" was made three times: by the app (briefing.mjs on its first-line D
schedule) for the dashboard chart, the PDF map marks and the NOTAM records; here (engines._assess_notam_window on
enrichment's schedule-line reader and _schedule_overlaps) for the airport cards and the PDF text; and by
runway_closure_schedule for dated runway regimes. A census of all 30 held originals on release 498 found 848 notices
whose surfaces disagree (output/pd-item3-timing-20261014). The rules now live once, in notam_timing_rules.json - the
app's notam-timing-rules.json byte for byte - and both suites run tests/fixtures/notam-timing-vectors.json.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path

import pytest

from app.odss import engines
from app.odss.briefing import build_briefing_view
from app.odss.enrichment import _parse_airport_notams
from app.odss.engines import analyse
from app.odss.parser import extract_pages, parse_lido

ROOT = Path(__file__).resolve().parents[1]
RULES_FILE = ROOT / "app" / "odss" / "notam_timing_rules.json"
VECTORS_FILE = ROOT / "tests" / "fixtures" / "notam-timing-vectors.json"
CORPUS = ROOT.parent / "private_cfp_corpus"
# The app pins the same two digests (tests/notam-timing-shared-rules-20261014.test.mjs).
SHARED_RULES_SHA256 = "a2730975243f6a0a42de5cf5fa31d95db9d68f8b7598f0f2ed63a1e18982b05a"
SHARED_VECTORS_SHA256 = "84eab490df220efa49693cfa9f7d61393d34ed658e6dc2f0ed8b98cedf2b0b40"
VECTORS = json.loads(VECTORS_FILE.read_text(encoding="utf-8"))
STATUS = {"active": "affecting", "review": "review", "outside_time_window": "outside_window", "outside_schedule": "outside_window"}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def test_the_timing_rules_and_vectors_are_the_apps_bytes() -> None:
    assert _sha256(RULES_FILE) == SHARED_RULES_SHA256
    assert _sha256(VECTORS_FILE) == SHARED_VECTORS_SHA256
    assert json.loads(RULES_FILE.read_text())["specVersion"] == VECTORS["specVersion"]


def _flight(reference: datetime) -> dict:
    # Synthetic timing contract: ZZZZ is the destination, judged at its own scheduled arrival.
    return {"departure": "XXXX", "destination": "ZZZZ", "scheduled_departure_utc": (reference - timedelta(hours=8)).isoformat(),
            "scheduled_arrival_utc": reference.isoformat(), "route_waypoints": [], "alternates": [], "edto": {"airports": []}}


def _assess(vector: dict) -> dict:
    """The production path: enrichment's LIDO record reader, then the engine's destination window assessment."""
    reference = _utc(vector["referenceAt"])
    block = "\n".join([f"Z1/26 VALID: {vector['validity']}", *vector["lines"]])
    record = _parse_airport_notams("ZZZZ", block, reference, include_all=True)[0]
    flight = _flight(reference)
    role, start, end = engines._notam_role_window(flight, "ZZZZ", set(), {})
    assert role == "destination"
    assert (start.isoformat(), end.isoformat()) == (_utc(vector["window"]["startsAt"]).isoformat(), _utc(vector["window"]["endsAt"]).isoformat())
    valid_from = datetime.fromisoformat(record["valid_from_utc"])
    valid_to = datetime.fromisoformat(record["valid_to_utc"]) if record.get("valid_to_utc") else datetime.max.replace(tzinfo=timezone.utc)
    return engines._assess_notam_window(record, flight, role, start, end, valid_from, valid_to)


@pytest.mark.parametrize("vector", [v for v in VECTORS["decisionCases"] if v["referenceAt"]], ids=lambda vector: vector["id"])
def test_every_shared_vector_decides_the_same_through_the_engine(vector: dict) -> None:
    row = _assess(vector)
    expected = {key: value for key, value in vector["expect"].items() if key != "referenceInterval"}
    got = {"status": STATUS.get(row["applicability"], row["applicability"]), "stateAtReference": row["stateAtReference"],
           "minutesDelta": row["minutesDelta"]}
    assert got == expected, f"{vector['id']} ({vector['label']}): {row}"
    interval = vector["expect"].get("referenceInterval")
    if interval:
        held = row.get("referenceInterval") or {}
        assert _utc(held["startsAt"]) == _utc(interval["startsAt"]), row
        assert (held.get("endsAt") is None) if interval["endsAt"] is None else _utc(held["endsAt"]) == _utc(interval["endsAt"]), row


def _corpus_view(file: str) -> tuple[dict, list, dict]:
    source = CORPUS / file
    if not source.exists():
        pytest.skip(f"private CFP corpus file {file} is not available")
    flight = parse_lido(extract_pages(source), source.name)
    findings, warnings = analyse(flight)
    return flight, findings, build_briefing_view(flight, findings, warnings, include_dashboard_only_panels=True)


def _notice(findings: list, notam_id: str, location: str) -> dict:
    return next(item["data"] for item in findings if item["engine"] == "notam"
                and item["data"]["notam_id"] == notam_id and item["data"]["location"] == location)


def _audit(flight: dict, notam_id: str, location: str) -> dict:
    """The engine's record of a notice; LIDO prints some series with a leading 1 (1A2106/26 is A2106/26)."""
    return next(row for row in flight["audit_evidence"]["notam"]["records"]
                if row["notam_id"].removeprefix("1") == notam_id and row["location"] == location)


def test_genuine_sq322_heathrow_crane_2130_0330_is_not_published_active_at_the_0455z_arrival() -> None:
    flight, findings, _ = _corpus_view("lido-briefing_SQ_322_16Aug2026_SIN_LHR.pdf")
    record = _audit(flight, "A2106/26", "EGLL")
    assert record["schedule"] == "2130-0330"
    destination = next(row for row in record["role_applicability"] if row["role"] == "destination")
    assert destination["referenceAt"].startswith("2026-08-17T04:55")
    assert (destination["applicability"], destination["stateAtReference"], destination["minutesDelta"]) == ("active", "ended_before_reference", 85)


def test_genuine_rpll_b3172_26_exception_schedule_is_a_review_not_continuously_active() -> None:
    flight, findings, _ = _corpus_view("lido-briefing_SQ_910_15Aug2026_SIN_MNL.pdf")
    record = _audit(flight, "B3172/26", "RPLL")
    assert record["schedule"] == "0000-2359 EXC JUL 04 06"
    destination = next(row for row in record["role_applicability"] if row["role"] == "destination")
    assert (destination["applicability"], destination["stateAtReference"]) == ("review", "unknown_at_reference")


def test_genuine_sq910_departure_window_is_two_hours_so_the_0200z_taxiway_closure_is_in_it() -> None:
    # ETD 15 AUG 0050Z; A2423/26 closes TWY N2 AUG 12 14 15 0200-0900. The chart and the PDF map drew it as scheduled
    # (app +/-2h) while the card and the PDF text left it out (one-hour ODSS departure window).
    flight, findings, view = _corpus_view("lido-briefing_SQ_910_15Aug2026_SIN_MNL.pdf")
    record = _audit(flight, "A2423/26", "WSSS")
    departure = next(row for row in record["role_applicability"] if row["role"] == "departure")
    assert departure["window_label"] == "14 AUG 2250Z-15 AUG 0250Z"
    assert (departure["applicability"], departure["stateAtReference"], departure["minutesDelta"]) == ("active", "begins_after_reference", 70)
    assert departure["referenceInterval"] == {"startsAt": "2026-08-15T02:00:00.000Z", "endsAt": "2026-08-15T09:00:00.000Z"}


def test_genuine_sq214_changi_sx120_25_keeps_its_review_and_its_per_runway_regime_statement() -> None:
    # Control: the 19 Sep 2026 regime rule is unchanged - the notice stays a timing review (other schedule clauses
    # are not evaluated) and RWY 02L/20R's regime is published as closing 1730-2130Z after the 1410Z arrival.
    flight, findings, view = _corpus_view("lido-briefing_SQ_214_16Aug2026_PER_SIN.pdf")
    notice = _notice(findings, "SX120/25", "WSSS")
    assert notice["applicability"] == "review"
    destination = next(row for row in view["airport_pdf_analysis"] if row["role"] == "destination")
    effects = [effect for effect in destination["surface_effects"] if effect["notam_id"] == "SX120/25"]
    assert [(effect["runways"], effect["stateAtReference"]) for effect in effects] == [(["02L", "20R"], "begins_after_reference")]
