"""QA500 (15 Oct 2026): the labelled synthetic timing forms reach their LABELLED verdict on every surface.

The parity census (tests/test_notam_timing_parity_20261014.py) proves the card, the PDF text, the chart and the PDF map
agree with each other; on release 500 they agreed on the wrong answer for a wrapped Item D ("AUG 16" / "1800-2000",
active all day on every surface). Here each LABELLED SYNTHETIC record of tests/fixtures/notam-timing-synthetic-
injection.json that states its scheduled-time verdict (departure WSSS, destination EGKK of the genuine SQ314 text) must
reach that verdict on ODSS's role assessment (the card and PDF pages 1, 2 and 4), in the PDF airport text, in the app's
NOTAM record and on the app's chart. The parity test's helpers are reused unchanged.
"""
from __future__ import annotations

import json
from pathlib import Path

from app.odss.parser import extract_pages
from tests.test_notam_timing_parity_20261014 import BASE, _app, _app_root, _corpus, _inject, _key, _odss

ROOT = Path(__file__).resolve().parents[1]
VERDICT = {"active": ("affecting", "active_at_reference"), "scheduled": ("affecting", "begins_after_reference"),
           "ended": ("affecting", "ended_before_reference"), "excluded": ("outside_window", None), "review": ("review", "unknown_at_reference")}
ODSS_STATUS = {"active": "affecting", "review": "review", "outside_time_window": "outside_window", "outside_schedule": "outside_window"}
APP_STATUS = {"affecting": "affecting", "review_schedule": "review", "outside_window": "outside_window"}
TEXT_ALLOWED = {"active": {"active"}, "scheduled": {"scheduled"}, "review": {"unresolved_timing"}, "ended": set(), "excluded": set()}


def _matches(expected: str, status: str, state: str | None) -> bool:
    want_status, want_state = VERDICT[expected]
    return status == want_status and (want_state is None or state == want_state)


def test_labelled_synthetic_forms_reach_their_labelled_verdict_on_the_card_pdf_text_records_and_chart() -> None:
    corpus = _corpus()
    _app_root()
    cases = json.loads((ROOT / "tests" / "fixtures" / "notam-timing-synthetic-injection.json").read_text())
    assert cases["label"] == "SYNTHETIC" and cases["base"] == BASE
    pdf = corpus / BASE
    odss = _odss(_inject(extract_pages(pdf), cases["stations"]), pdf.name, False)
    app = _app({"pdfs": [{"name": pdf.name, "path": str(pdf), "atotTiming": None}], "inject": cases})[pdf.name]["scheduled"]
    stations = {station["icao"]: station for station in app["stations"]}
    roles = {"WSSS": "departure", "EGKK": "destination"}
    failures: list[str] = []
    checked = 0
    for icao, role in roles.items():
        notices = {_key(notice["notamNumber"]): notice for notice in stations[icao]["notices"]}
        for row in cases["stations"][icao]:
            expected = row.get("expect_scheduled")
            if not expected:
                continue
            checked += 1
            key = _key(row["id"])
            where = f"{icao} {role} {row['id']} {row['case']} (labelled {expected})"
            notice = notices.get(key)
            if notice is None:
                failures.append(f"{where}: the app holds no record")
                continue
            applicability = notice["applicability"]
            if not _matches(expected, APP_STATUS.get(applicability["status"], applicability["status"]), applicability["stateAtReference"]):
                failures.append(f"{where}: app records {applicability['status']}/{applicability['stateAtReference']}")
            drawn_active = [chart for chart in notice["chart"] if chart.get("stateAtReference") == "active_at_reference" or chart.get("mode") == "active"]
            if drawn_active and expected != "active":
                failures.append(f"{where}: chart draws it active {drawn_active}")
            record = odss["records"].get((icao, key))
            assessed = next((item for item in (record or {}).get("role_applicability") or [] if item["role"] == role), None)
            if assessed is None:
                failures.append(f"{where}: ODSS holds no {role} assessment")
            elif not _matches(expected, ODSS_STATUS.get(assessed["applicability"], assessed["applicability"]), assessed["stateAtReference"]):
                failures.append(f"{where}: card/PDF assessment {assessed['applicability']}/{assessed['stateAtReference']}")
            claimed = {state for state in odss["text"].get((icao, key, role), []) if state in {"active", "scheduled", "unresolved_timing"}}
            if claimed - TEXT_ALLOWED[expected]:
                failures.append(f"{where}: PDF text says {sorted(claimed)}")
    assert checked == sum(1 for icao in roles for row in cases["stations"][icao] if row.get("expect_scheduled"))
    assert not failures, f"{len(failures)} of {checked} labelled records off their verdict:\n" + "\n".join(failures)
