"""F5 of the release-420 independent production QA (24 Sep 2026): the fresh
genuine SQ24 upload could not download or save its briefing - the service
answered HTTP 500 for reports/combined. The server log holds the cause:
``ValueError: Concise PDF capacity exceeded in WEATHER / ROUTE HAZARDS: 423pt
of content in 421pt of page`` - page 5 tried its nine grids and four type
sizes and then failed closed, because unlike page 6 it had no whole-unit
deferral ladder; a production analysis (live weather beside the OFP's own)
carries more page-5 content than the corpus renders with live weather off,
and several corpus flights sit within a few points of the same edge.

The general repair, both tested here on the genuine SQ24 15 Aug analysis with
its page-5 content inflated by labelled SYNTHETIC rows (the exact production
content is not held locally): page 5 defers whole units to the dashboard and
says so on the page (FLIGHT HAZARD KEY entries, EDTO airport windows, SIGMET
rows - every one of them a dashboard-held record), never a cut line and never
a stale PDF; and the service answers a composition failure with a structured
503 that names the page and the reason instead of a bare 500, so the app's
"Current reports are blocked" state can say why.
"""
from __future__ import annotations

import copy
import glob
import json
from pathlib import Path

import fitz
import pytest

from app.odss import reference_conformance as conformance
from app.odss.combined_brief import render_combined_briefing

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "tests" / "boss_reference_format_manifest.json"
CORPUS_OUTPUT = Path("/private/tmp/claude-502/-Users-jabe-Documents-ezzo/229f75b3-d51b-4bfc-8abe-10f8457eedb8/scratchpad/r20/corpus-gate6b")


def genuine_analysis(case: str) -> dict:
    files = glob.glob(str(CORPUS_OUTPUT / case / "analysis" / "*_analysis.json"))
    if not files:
        pytest.skip(f"gate-6 analysis for {case} is not on this machine")
    return json.loads(Path(files[0]).read_text(encoding="utf-8"))


def inflate_page5(payload: dict, rows: int) -> dict:
    """LABELLED SYNTHETIC: more planning-ETP clock rows than page 5 can hold at any grid or size.

    The renderer rebuilds its view from the flight, so the surplus goes into a flight field only page 5
    prints (ROUTE / EDTO CLOCKS reads flight.flight_planning_etps); the exact production surplus - live
    weather beside the OFP's own - is not held locally, and any page-5 unit list overflows the same way.
    """
    payload = copy.deepcopy(payload)
    etps = list(payload["flight"].get("flight_planning_etps") or [])
    for n in range(rows):
        etps.append({"label": f"SYNTHETIC-ETP-{n + 1:02d}", "from": "SYNTA", "to": "SYNTB", "distance_nm": 100 + n, "eet_token": f"0{n % 9 + 1}:00"})
    payload["flight"]["flight_planning_etps"] = etps
    return payload


CORPUS = ROOT.parent / "private_cfp_corpus"


def source_for(payload: dict) -> str | None:
    """The genuine OFP the analysis was made from (the renderer's chart gates read it), when it is on this machine."""
    name = str((payload.get("flight") or {}).get("document_id") or "")
    candidate = CORPUS / name
    return str(candidate) if name and candidate.is_file() else None


def render(payload: dict, path: Path) -> list[str]:
    render_combined_briefing(payload["flight"], payload["findings"], payload.get("view", {}).get("warnings") or [], path,
                             source_pdf_path=source_for(payload), weather_charts=payload.get("weather_charts") or {})
    with fitz.open(path) as document:
        return [page.get_text() for page in document]


def test_page_five_defers_whole_units_to_the_dashboard_instead_of_failing_closed(tmp_path):
    payload = inflate_page5(genuine_analysis("SQ24-SIN-JFK-15AUG"), 40)
    pages = render(payload, tmp_path / "inflated.pdf")
    assert len(pages) == 6
    page5 = " ".join(pages[4].split())
    assert "WEATHER / ROUTE HAZARDS" in page5
    assert "further route / EDTO clock row(s) on the dashboard" in page5, "the deferral is stated on the page"
    assert "SYNTHETIC-ETP-01" in page5, "the first rows still print in full"
    assert "SYNTHETIC-ETP-40" not in page5
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    result = conformance.check_reference_conformance(tmp_path / "inflated.pdf", structure=manifest["reference_structure"], contract_extensions=manifest["contract_extensions"])
    assert result["valid"], result["violations"]


def test_page_five_with_room_keeps_every_unit_and_states_no_deferral(tmp_path):
    payload = genuine_analysis("SQ24-SIN-JFK-15AUG")
    pages = render(payload, tmp_path / "plain.pdf")
    assert len(pages) == 6
    assert "further SIGMET row(s)" not in pages[4] and "further EDTO airport window(s)" not in pages[4] and "further plotted hazard(s)" not in pages[4] and "further route / EDTO clock row(s)" not in pages[4]


def test_every_corpus_page_five_survives_a_production_sized_surplus(tmp_path):
    """Every held analysis keeps rendering with 24 extra page-5 units - the surplus a live-weather production analysis can add."""
    cases = sorted(p.name for p in CORPUS_OUTPUT.iterdir() if (p / "analysis").is_dir()) if CORPUS_OUTPUT.is_dir() else []
    if not cases:
        pytest.skip("gate-6 output is not on this machine")
    for case in cases:
        pages = render(inflate_page5(genuine_analysis(case), 24), tmp_path / f"{case}.pdf")
        assert len(pages) == 6, case


def test_the_gate_accepts_only_an_exactly_stated_trailing_deferral():
    from app.odss.concise_pdf_gate import lines_after_stated_deferral, normalized
    lines = [f"SYNT/S{n} (TURB): Route crossing 1200-1300Z within validity." for n in range(1, 6)]
    page = normalized(" ".join(lines[:3]) + " +2 further SIGMET row(s) on the dashboard.")
    assert lines_after_stated_deferral(lines, page, "SIGMET row(s)") == lines[:3], "exactly the last two rows are deferred"
    kept = lines_after_stated_deferral(lines, normalized(" ".join(lines[:2]) + " +2 further SIGMET row(s) on the dashboard."), "SIGMET row(s)")
    assert lines[2] in kept, "a third missing row stays a line the page must print, so the gate still refuses it"
    assert lines_after_stated_deferral(lines, normalized(" ".join(lines[:3])), "SIGMET row(s)") == lines, "no statement, no deferral"
    assert lines_after_stated_deferral(lines, normalized(" ".join(lines) + " +2 further SIGMET row(s) on the dashboard."), "SIGMET row(s)") == lines, "a stated row that is printed anyway is not a deferral"
    assert lines_after_stated_deferral(lines, page, None) == lines, "an unbound-deferral unit keeps every line"


def test_the_service_answers_a_composition_failure_with_the_page_and_the_reason(monkeypatch, service_app):
    """A page that cannot be composed is a stated 503 with the page and the reason, not a bare 500 (the fresh SQ24 journey)."""
    import app.main as main
    from tests.test_service_api_v06 import _authorization, _build_lido_pdf

    created = service_app.post("/v1/analyses", headers=_authorization(), files={"file": ("SQ304.pdf", _build_lido_pdf(), "application/pdf")})
    assert created.status_code in (200, 201), created.text
    analysis_id = created.json()["analysis_id"]
    assert created.json()["status"] == "Completed"

    def refuse(*args, **kwargs):
        raise ValueError("Concise PDF capacity exceeded in WEATHER / ROUTE HAZARDS: 423pt of content in 421pt of page. No source continuation is permitted.")

    monkeypatch.setattr(main, "render_combined_briefing", refuse)
    response = service_app.get(f"/v1/analyses/{analysis_id}/reports/combined", headers=_authorization())
    assert response.status_code == 503, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "briefing_composition_failed"
    assert "WEATHER / ROUTE HAZARDS" in detail["message"] and "423pt" in detail["message"]
    assert detail["retryable"] is False


from tests.test_service_api_v06 import service_app  # noqa: E402,F401 - the service fixture (temporary dirs, token)


def test_page_six_holds_a_primary_row_with_many_printed_conditions(tmp_path):
    """The historical SQ322 stress source is an opposite-direction control.

    Its many-clause SX33 notice applies FROM Kabul; this flight reaches
    Pakistan before Kabul. Keep the whole qualified source and its failed
    direction, never promote it as an unresolved primary call. The next
    genuine SQ23 test remains the qualifying positive capacity case.
    """
    from app.odss.enroute_contact import is_call_line, primary_procedure_line

    payload = genuine_analysis("SQ322-SIN-LHR")
    composed = payload["view"]["briefing"]["enroute_contact"]
    opposite = next(row for row in composed["procedures"] if row["notam_id"] == "SX33/26")
    assert opposite["source_page"] == 69 and opposite["kind"] == "voice_contact"
    assert opposite["applicability_state"] == "not_applicable" and opposite["latest_actm"] is None
    assert next(c for c in opposite["conditions"] if c["kind"] == "direction")["result"] == "not_met"
    assert next(c for c in opposite["conditions"] if c["text"].startswith("DRG THE NON AVAILABILITY"))["result"] == "unresolved"
    assert opposite["printed_details"]["frequencies"] == ["124.100 MHZ", "118.950 MHZ"]
    assert opposite["printed_details"]["lead"] == "AT LEAST 15 MIN PRIOR TO ENTERING KARACHI OR LAHORE FIR"
    assert "VIA MOTMO (P500)" in opposite["instruction"] and not is_call_line(opposite)
    assert opposite["actions"][0]["printed_details"]["frequencies"] == [
        "128.350 MHZ", "121.650 MHZ", "124.100 MHZ", "118.950 MHZ", "120.750 MHZ", "125.750 MHZ"]
    primary = primary_procedure_line(composed["procedure_lines"])
    assert primary["notam_ids"] == ["1G216/26"] and primary["source_pages"] == [71]
    pages = render(payload, tmp_path / "sq322.pdf")
    assert len(pages) == 6
    page6 = " ".join(pages[5].split())
    assert "FIR / COMMUNICATION" in page6
    assert "+05:34 OAKX entry." in page6 and "NOTAM 1G216/26, OFP p71" in page6
    assert "125.2MHZ 10 MINS PRIOR ENTERING TO FIR" in page6
    assert "not later than ACTM 05:24" in page6 and "conditions held" in page6
    assert "NOTAM SX33/26" not in page6, "the opposite-direction notice is not promoted to the primary call"
    # ATC-CLEARANCE-FAMILY (1 Oct 2026): the added CO188/02 row (LTAA p74) is one more line and one more deferred row.
    assert len(composed["procedure_lines"]) == 28
    # ITEM 4 F3-R460 (9 Oct 2026): EGLL A2905/26 (TWY BRAVO (SOUTH) between ECHO and FOXTROT) now carries its stated
    # PDF consequence instead of an unresolved entry, so the airport assessment shortens and page 6 keeps one more call
    # row - Turkmenabat's AX1/23 - with one fewer deferred.
    assert "NOTAM AX1/23, OFP p72" in page6
    assert "+26 further rows on the dashboard" in page6 and "OPKR 2, OPLR 1" in page6


def test_page_six_cuts_clauses_before_it_drops_a_valued_call_row(tmp_path):
    """RESTRICTION-COMPLETENESS-430: genuine SQ23's Karachi row (SX33/26, p110) grew by its DRG prerequisite and VIA MOTMO
    scope; the card cuts clauses to a prefix before dropping the row, so the physical page keeps the crew's contact row with
    its frequencies, its prerequisite's opening words and its unresolved state (on the earlier ladder it went to the
    dashboard list)."""
    payload = genuine_analysis("SQ23-JFK-SIN")
    composed = payload["view"]["briefing"]["enroute_contact"]
    qualified = next(row for row in composed["procedures"] if row["notam_id"] == "SX33/26")
    assert qualified["source_page"] == 110 and qualified["fir"] == "OPLR"
    assert qualified["applicability_state"] == "conditions_unresolved"
    assert next(c for c in qualified["conditions"] if c["kind"] == "direction")["result"] == "met"
    assert qualified["printed_details"]["frequencies"] == ["124.100 MHZ", "118.950 MHZ"]
    assert qualified["printed_details"]["lead"] == "AT LEAST 15 MIN PRIOR TO ENTERING KARACHI OR LAHORE FIR"
    assert qualified["latest_actm"] == "11:41"
    pages = render(payload, tmp_path / "sq23.pdf")
    assert len(pages) == 6
    page6 = " ".join(pages[5].split())
    row = page6[page6.index("OPLR entry."):]
    row = row[:row.index("conditions unresolved") + len("conditions unresolved")]
    assert "NOTAM SX33/26, OFP p110" in row and "124.100 MHZ, 118.950 MHZ" in row, row
    assert "AT LEAST 15 MIN PRIOR TO ENTERING KARACHI OR LAHORE FIR" in row, row
    assert "not later than ACTM 11:41" in row, row
    assert "DRG THE NON AVAILABILITY" in row, row
    # ATC-CLEARANCE-FAMILY (1 Oct 2026): the added CO188/02 row (LTAA p106) is one more line and one more deferred row.
    assert len(composed["procedure_lines"]) == 32 and "+29 further rows on the dashboard" in page6
    deferred = page6.split("+29 further rows on the dashboard", 1)[1].split("No slot-control", 1)[0]
    assert "SX33/26" not in deferred, "the qualifying call prints rather than becoming a dashboard-only row"
    assert "Source FIR KZDC; route/time unresolved." in page6
    assert "NOTAM 1A1513/26, OFP p94" in page6 and "KZNY 1A487/26 (p98)" in page6


@pytest.mark.parametrize("state", ["conditions_held", "conditions_unresolved"])
def test_capacity_attempt_keeps_primary_and_next_qualifying_other_fir_call(state):
    """LABELLED SYNTHETIC: own eligibility, then held printed conditions, then
    existing order govern the extra slot - not notice identity, number of
    frequencies or apparent urgency (ATC-PDF-PRIORITY, 2 Oct 2026: a held call
    is preferred over an earlier unresolved one).
    """
    from app.odss.operational_format import _primary_and_next_valued_call

    def line(label, fir="ZZBB", **changes):
        return {"label": label, "fir": fir, "kind": "voice_contact", "actor": "crew",
                "instruction_effect": "instruction", "applicability_state": "conditions_held",
                "printed_details": {"lead": "SYNTHETIC PRINTED LEAD"}, **changes}

    primary = line("primary", "ZZAA")
    same_fir = line("same FIR", "ZZAA")
    opposite = line("opposite direction", applicability_state="not_applicable")
    other_actor = line("other actor", actor="other")
    permission = line("permission", instruction_effect="permission")
    no_values = line("no printed value", printed_details={})
    qualified = line("qualified", applicability_state=state)
    later = line("later", "ZZCC")
    rows = [primary, same_fir, opposite, other_actor, permission, no_values, qualified, later]
    original = copy.deepcopy(rows)
    assert _primary_and_next_valued_call(rows, primary) == [primary, qualified if state == "conditions_held" else later]
    assert rows == original
    assert _primary_and_next_valued_call([primary, same_fir, opposite, other_actor, permission, no_values], primary) == [primary]
    assert _primary_and_next_valued_call([], None) == []
