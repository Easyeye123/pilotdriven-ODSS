"""ITEM 3, Gatwick (14 Oct 2026): no surface may disagree with another about when a station notice applies.

Cross-runtime census over every held original OFP and over LABELLED SYNTHETIC timing forms injected into the
genuine SQ314 text. This service decides each notice for the airport cards and the PDF text; the app decides it for
the dashboard chart, the PDF map marks and its NOTAM records (scripts/notam-timing-census.mjs, run through
PILOTDRIVEN_APP_ROOT). Two timing scenarios: the OFP's own times, and an entered ATOT (STD + 23 min) whose timing
view the app converts into station references exactly as the dashboard does.

Departure and destination: every surface must reach the same verdict, at the same reference instant, with the same
minutes; a dated runway regime must be drawn on the chart in the state the PDF publishes for that runway. Every
other station: the inputs both parsers read (validity, Item D, review) must be identical and the app's decision must
be the shared evaluator's decision on those inputs - only the open no-reference-station policy (the product owner's
decision: notam_timing_rules.json "noReferenceStations") may still differ, and its count is reported.
"""
from __future__ import annotations

from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

import pytest

from app.odss.briefing import build_briefing_view
from app.odss.engines import analyse
from app.odss.parser import extract_pages, parse_lido
from app.odss.timing import build_timing_view
from tests.cross_runtime import sibling_app_root

ROOT = Path(__file__).resolve().parents[1]
ATOT_OFFSET = timedelta(minutes=23)
ODSS_ROLE = {"departure": "departure", "destination": "destination", "destination_alternate": "destination alternate",
             "edto": "EDTO", "edto_suitable": "EDTO", "edto_adequate": "EDTO", "fuel_enroute": "fuel enroute airport",
             "enroute": "informational"}
ROLE_RANK = ["departure", "destination", "destination_alternate", "edto_suitable", "edto_adequate", "edto", "fuel_enroute", "enroute"]
STATUS = {"active": "affecting", "review": "review", "outside_time_window": "outside_window", "outside_schedule": "outside_window"}
APP_STATUS = {"affecting": "affecting", "review_schedule": "review", "outside_window": "outside_window"}
BASE = "lido-briefing_SQ_314_15Aug2026_SIN_LGW.pdf"


def _app_root() -> Path:
    configured = os.environ.get("PILOTDRIVEN_APP_ROOT")
    root = Path(configured) if configured else sibling_app_root(Path(__file__), "pd-item3-app-20261014")
    if root is None or not (root / "scripts" / "notam-timing-census.mjs").exists() or not shutil.which("node"):
        if configured:
            raise FileNotFoundError(f"PILOTDRIVEN_APP_ROOT has no scripts/notam-timing-census.mjs: {root}")
        pytest.skip("the app checkout or Node is not available for the cross-runtime timing census")
    return root


def _corpus() -> Path:
    configured = os.environ.get("PILOTDRIVEN_PRIVATE_CFP_CORPUS_DIR")
    corpus = Path(configured) if configured else ROOT.parent / "private_cfp_corpus"
    if not corpus.is_dir():
        if configured:
            raise FileNotFoundError(f"Configured PILOTDRIVEN_PRIVATE_CFP_CORPUS_DIR is missing: {corpus}")
        pytest.skip("the private CFP corpus is not available")
    return corpus


def _key(value: object) -> str:
    text = str(value or "").upper().strip()
    match = re.fullmatch(r"1?([A-Z]{1,2})0*(\d+)/(\d{2})", text)
    return f"{match.group(1)}{match.group(2)}/{match.group(3)}" if match else text


def _minute(value: object) -> str | None:
    if not value:
        return None
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).strftime("%Y-%m-%dT%H:%M")


def _inject(pages: list[str], stations: dict) -> list[str]:
    pages = list(pages)
    for icao, rows in stations.items():
        heading = re.compile(rf"^\s*{icao}\s*/[A-Z]{{3}}\s+\S.*$")
        for index, text in enumerate(pages):
            lines = text.split("\n")
            at = next((i for i in range(len(lines) - 1) if heading.match(lines[i]) and re.fullmatch(r"\s*-{5,}\s*", lines[i + 1])), None)
            if at is None:
                continue
            block = [line for row in rows for line in [f"{row['id']}                                  VALID: {row['validity']}",
                                                       *(f"  {body}" for body in row["body"])]]
            pages[index] = "\n".join(lines[:at + 2] + block + lines[at + 2:])
            break
        else:
            raise AssertionError(f"no NOTAM heading for {icao}")
    return pages


def _odss(pages: list[str], name: str, atot: bool) -> dict:
    flight = parse_lido(pages, name)
    timing_view = None
    if atot:
        value = (datetime.fromisoformat(str(flight["scheduled_departure_utc"]).replace("Z", "+00:00")) + ATOT_OFFSET).isoformat()
        flight["actual_takeoff_utc"] = value
        flight["timing_reference"] = {"reference_type": "takeoff", "reference_utc": value, "reference_waypoint": None,
                                      "reference_actm_minutes": 0, "actual_takeoff_utc": value}
    findings, warnings = analyse(flight)
    if atot:
        timing_view = build_timing_view(flight, findings, flight["actual_takeoff_utc"], flight.get("timing_reference"))
    view = build_briefing_view(flight, findings, warnings, timing_view, None, include_dashboard_only_panels=True)
    effects: dict[tuple[str, str, str], list[dict]] = {}
    text_states: dict[tuple[str, str, str], list[str]] = {}
    for row in [*(view.get("airport_pdf_analysis") or []), *(view.get("alternate_pdf_analysis") or [])]:
        for effect in row.get("surface_effects") or []:
            effects.setdefault((row["icao"], _key(effect["notam_id"]), row["role"]), []).append(effect)
        for line in row.get("lines") or []:
            for notam_id in line.get("notam_ids") or []:
                text_states.setdefault((row["icao"], _key(notam_id), row["role"]), []).append(str(line.get("state")))
        for item in row.get("unresolved_detail") or []:
            if isinstance(item, dict) and item.get("reason") == "timing":
                text_states.setdefault((row["icao"], _key(item.get("id") or item.get("notam_id")), row["role"]), []).append("unresolved_timing")
    records = {(row["location"], _key(row["notam_id"])): row for row in flight["audit_evidence"]["notam"]["records"]}
    sources = {(row["location"], _key(row["notam_id"])): row for row in flight["notams"]}
    return {"records": records, "sources": sources, "effects": effects, "text": text_states,
            "timing": None if timing_view is None else {"actual_takeoff_utc": flight["actual_takeoff_utc"],
                                                         "waypoints": timing_view.get("waypoints"),
                                                         "fir_crossings": timing_view.get("fir_crossings")}}


def _app(request: dict) -> dict:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "request.json"
        path.write_text(json.dumps(request, default=str))
        done = subprocess.run(["node", "scripts/notam-timing-census.mjs", "--request", str(path)], cwd=_app_root(),
                              capture_output=True, text=True, timeout=900, check=False)
    assert done.returncode == 0, done.stderr[-4000:]
    return json.loads(done.stdout)


def _shared_input(source: dict) -> dict:
    from app.odss.notam_timing import notice_timing_input
    return notice_timing_input(source)


def _compare(name: str, scenario: str, odss: dict, app: dict, prefix: str | tuple[str, ...] | None = None) -> tuple[list[str], list[str], int]:
    from app.odss.notam_timing import decide_notice_timing
    failures: list[str] = []
    policy: list[str] = []
    compared = 0
    regime_seen: set[tuple] = set()
    for station in app["stations"]:
        roles = sorted(station["roles"], key=lambda role: ROLE_RANK.index(role) if role in ROLE_RANK else 99)
        primary = next((role for role in roles if role in ODSS_ROLE), None)
        if primary is None:
            continue
        for notice in station["notices"]:
            if prefix and not str(notice["notamNumber"]).startswith(prefix):
                continue
            key = (station["icao"], _key(notice["notamNumber"]))
            record, source = odss["records"].get(key), odss["sources"].get(key)
            if record is None:
                continue
            compared += 1
            where = f"{scenario} {name} {station['icao']} {primary} {notice['notamNumber']}"
            shared = _shared_input(source)
            validity = shared["validity"] or {}
            # The end is compared as read: an instant (explicit or EST) or open (UFN, PERM); both treat EST as the end.
            open_end = {"until_further_notice", "permanent"}
            app_input = (_minute(notice["startsAt"]), _minute(notice["endsAt"]), notice["endKind"] in open_end, notice["schedule"],
                         bool(notice["reviewReason"]) or notice["parseStatus"] == "manual_review" or notice["applicability"]["status"] == "review_schedule")
            decided = decide_notice_timing(shared, {**station["window"]}) if shared["validity"] else None
            odss_input = (_minute(validity.get("startsAt")), _minute(validity.get("endsAt")), validity.get("endKind") in open_end, shared["schedule"],
                          bool(shared["review"]) or not shared["validity"] or (decided is not None and decided["status"] == "review"))
            if app_input != odss_input:
                failures.append(f"{where}: inputs differ app={app_input} odss={odss_input}")
                continue
            app_decision = notice["applicability"]
            app_verdict = (APP_STATUS.get(app_decision["status"]), app_decision["stateAtReference"], _minute(app_decision["referenceAt"]), app_decision["minutesDelta"])
            if primary not in {"departure", "destination"}:
                window = {**station["window"]}
                expected = decide_notice_timing(shared, window)
                evaluated = (expected["status"], expected["stateAtReference"], _minute(expected["referenceAt"]), expected["minutesDelta"])
                if evaluated != app_verdict:
                    failures.append(f"{where}: the app's decision {app_verdict} is not the shared rules' {evaluated} on the same inputs and window")
                row = next((row for row in record.get("role_applicability") or [] if row["role"] == ODSS_ROLE[primary]), None)
                if row is None or (STATUS.get(row["applicability"]), row["stateAtReference"], _minute(row["referenceAt"]), row["minutesDelta"]) != app_verdict:
                    policy.append(where)
                continue
            row = next((row for row in record.get("role_applicability") or [] if row["role"] == primary), None)
            if row is None:
                failures.append(f"{where}: ODSS holds no {primary} assessment")
                continue
            odss_verdict = (STATUS.get(row["applicability"], row["applicability"]), row["stateAtReference"], _minute(row["referenceAt"]), row["minutesDelta"])
            if odss_verdict != app_verdict:
                failures.append(f"{where}: card/PDF text {odss_verdict} != chart/PDF map/records {app_verdict} | {source.get('text', '')[:120]}")
            regime_rows = [chart for chart in notice["chart"] if chart.get("regime")]
            effects = [effect for effect in odss["effects"].get((station["icao"], key[1], primary), []) if effect.get("scope") == "whole_entity" and effect.get("text")]
            for effect in effects:
                label = "/".join(effect["runways"])
                regime_seen.add((station["icao"], key[1], label))
                drawn = [chart for chart in regime_rows if chart["entityRef"] and sorted(chart["entityRef"].split("/")) == sorted(effect["runways"])]
                if not drawn or drawn[0]["stateAtReference"] != effect["stateAtReference"]:
                    failures.append(f"{where}: PDF RWY {label} {effect['stateAtReference']} but chart {[(c['entityRef'], c['stateAtReference']) for c in regime_rows]}")
            for chart in regime_rows:
                if not any(sorted(chart["entityRef"].split("/")) == sorted(effect["runways"]) for effect in effects):
                    failures.append(f"{where}: chart draws regime RWY {chart['entityRef']} the PDF does not publish")
            if not effects:
                for state in odss["text"].get((station["icao"], key[1], primary), []):
                    allowed = {"active": {"active_at_reference"}, "scheduled": {"begins_after_reference"},
                               "unresolved_timing": {"unknown_at_reference"}}.get(state)
                    if allowed is not None and app_verdict[1] not in allowed:
                        failures.append(f"{where}: PDF text '{state}' but chart/records {app_verdict}")
    return failures, policy, compared


def _run(pdfs: list[Path], inject: dict | None = None, prefix: str | tuple[str, ...] | None = None) -> tuple[list[str], list[str], int]:
    odss_runs: dict[str, dict] = {}
    request = {"pdfs": [], "inject": inject}
    for pdf in pdfs:
        pages = extract_pages(pdf)
        if inject:
            pages = _inject(pages, inject["stations"])
        odss_runs[pdf.name] = {"scheduled": _odss(pages, pdf.name, False), "atot": _odss(pages, pdf.name, True)}
        request["pdfs"].append({"name": pdf.name, "path": str(pdf), "atotTiming": odss_runs[pdf.name]["atot"]["timing"]})
    app = _app(request)
    failures: list[str] = []
    policy: list[str] = []
    compared = 0
    for pdf in pdfs:
        for scenario in ("scheduled", "atot"):
            held = app[pdf.name][scenario]
            assert "error" not in held, f"{pdf.name} {scenario}: {held.get('error')}"
            found, open_policy, count = _compare(pdf.name, scenario, odss_runs[pdf.name][scenario], held, prefix)
            failures.extend(found)
            policy.extend(open_policy)
            compared += count
    return failures, policy, compared


def test_every_held_original_ofp_has_one_timing_verdict_per_station_notice_on_every_surface() -> None:
    corpus = _corpus()
    _app_root()
    pdfs = sorted(corpus.glob("*.pdf"))
    assert len(pdfs) >= 30, f"expected the 30 held originals, found {len(pdfs)}"
    failures, policy, compared = _run(pdfs)
    print(f"compared {compared} station notices; open no-reference-station policy differences: {len(policy)}")
    assert compared > 4000
    assert not failures, f"{len(failures)} cross-surface timing disagreements:\n" + "\n".join(failures[:60])


def test_labelled_synthetic_timing_forms_reach_one_verdict_on_every_surface() -> None:
    corpus = _corpus()
    _app_root()
    cases = json.loads((ROOT / "tests" / "fixtures" / "notam-timing-synthetic-injection.json").read_text())
    assert cases["label"] == "SYNTHETIC" and cases["base"] == BASE
    # the labelled synthetic ids: Z9nnn (the census forms) and Codex's QA518 records Z68nn at EGKK
    failures, policy, compared = _run([corpus / BASE], inject=cases, prefix=("Z9", "Z68"))
    print(f"compared {compared} synthetic station notices; open no-reference-station policy differences: {len(policy)}")
    assert compared == 2 * sum(len(rows) for rows in cases["stations"].values())
    assert not failures, f"{len(failures)} cross-surface timing disagreements:\n" + "\n".join(failures[:60])
