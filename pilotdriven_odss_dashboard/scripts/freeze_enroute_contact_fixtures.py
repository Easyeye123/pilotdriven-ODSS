#!/usr/bin/env python3
"""Freeze genuine-source Early ATC / FIR calls fixtures for the app's tests.

ATC-RADIO-SOURCE-418 (24 Sep 2026). For each private-corpus OFP named below the
ODSS analysis is run and the fields the shared rule reads are copied, with the
record the ODSS published (view.briefing.enroute_contact, composed by
app/odss/enroute_contact.py), into <app>/tests/fixtures/enroute-contact/<case>.json.
The app's test then proves web/src/lib/enroute-contact.mjs composes exactly the
same record from the same input; scripts/mint-enroute-contact-vectors.mjs on
the app side turns the same inputs (plus labelled SYNTHETIC mutations) into the
vectors this side replays. Nothing here is edited by hand.

  PYTHONPATH=. .venv/bin/python scripts/freeze_enroute_contact_fixtures.py [--app-root PATH] [--corpus PATH]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from app.analysis import run_odss_analysis

ROOT = Path(__file__).resolve().parents[1]
CASES = (
    ("SQ366-SIN-FCO", "SQ36604082026SIN.pdf"),
    ("SQ23-JFK-SIN", "SQ02325072026JFK.pdf"),
    ("SQ882-SIN-HKG-10SEP", "lido-briefing_SQ_882_10Sep2026_SIN_HKG.pdf"),
    ("SQ24-SIN-JFK-15AUG", "lido-briefing_SQ_24_15Aug2026_SIN_JFK.pdf"),
    ("SQ304-SIN-BRU", "lido-briefing_SQ_304_12Jul2026_SIN_BRU.pdf"),
    ("SQ303-BRU-SIN", "SQ30316072026BRU 81.pdf"),
    # HEADING-CONTINUITY-432: its Kabul heading is printed at the foot of p70, the underline on p71.
    ("SQ322-SIN-LHR", "lido-briefing_SQ_322_16Aug2026_SIN_LHR.pdf"),
    # SLOT-ALLOCATION-434: its allocation is printed colon-joined ("WPT DOBAT FL:360 CTO:2202 CTOT:1627"); SQ322's is
    # hyphenated between pipes. Both were read as no allocation before the shared grammar.
    ("SQ352-SIN-CPH", "lido-briefing_SQ_352_15Aug2026_SIN_CPH.pdf"),
    # AIRSPACE-HEADINGS-436: Fukuoka's oceanic data-link notices sit under "RJJJ FUKUOKA FIR OCEANIC" (SQ34, SQ38; SQ24
    # above also holds KZNY 1A487/26 under "KZNY NEW YORK DOMESTIC LOWER"); SQ38's Great Sitkin voice-contact notice
    # sits under the enroute topic heading "VAA GREAT SITKIN" and SQ366's UAV notice under "UAV 401614N 0250927E".
    ("SQ34-SIN-SFO", "lido-briefing_SQ_34_15Aug2026_SIN_SFO.pdf"),
    ("SQ38-SIN-LAX-29AUG", "SQ38-29AUG2026-OFP-for-prod-proof.pdf"),
    # ATC-CLEARANCE-FAMILY (1 Oct 2026): NON-RNAV radar-vector requests to DAEGU/INCHEON ACC under the navaid topic headings
    # "SOT SONGTAN" (SQ605 p60, SQ606 p72) and "PSN BUSAN" (SQ606 p75); SQ194's permission to request vectors beside an
    # equipment duty (SX54/24). CO188/02 is held by SQ23, SQ303, SQ304, SQ322, SQ352 and SQ366 above.
    ("SQ605-ICN-SIN-08SEP", "SQ60508092026ICN.pdf"),
    ("SQ606-SIN-ICN-06SEP", "SQ60606092026SIN.pdf"),
    ("SQ194-SIN-HAN", "lido-briefing_SQ_194_16Aug2026_SIN_HAN.pdf"),
)
# ATC-PDF-PRIORITY (2 Oct 2026): each leg's filed airway, so an airway-only route list is read the same on both sides.
WAYPOINT_FIELDS = ("name", "fir_boundary", "actm_minutes", "source_page", "airway_in")
FLIGHT_FIELDS = ("departure", "destination", "planned_level_profile", "scheduled_departure_utc", "actual_takeoff_utc", "extraction_rules", "notam_procedure_records", "notam_fir_names", "bobcat", "slot_allocation_unread")


def slim_flight(flight: dict) -> dict:
    slim = {"route_waypoints": [{k: w.get(k) for k in WAYPOINT_FIELDS} for w in flight.get("route_waypoints") or [] if isinstance(w, dict)]}
    for key in FLIGHT_FIELDS:
        slim[key] = flight.get(key)
    evidence = flight.get("source_evidence") if isinstance(flight.get("source_evidence"), dict) else {}
    slim["source_evidence"] = {"page1": evidence.get("page1")}
    return slim


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--app-root", default=os.environ.get("PILOTDRIVEN_APP_ROOT", str(ROOT.parent.parent / "pd-code-e-helpyou-20260921")))
    parser.add_argument("--corpus", default=os.environ.get("PILOTDRIVEN_PRIVATE_CFP_CORPUS", str(ROOT.parent / "private_cfp_corpus")))
    args = parser.parse_args()
    corpus = Path(args.corpus)
    out_dir = Path(args.app_root) / "tests" / "fixtures" / "enroute-contact"
    out_dir.mkdir(parents=True, exist_ok=True)
    for case, name in CASES:
        source = corpus / name
        if not source.is_file():
            print(f"skip {case}: {source} not found")
            continue
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = run_odss_analysis(source, root / "analysis", root / "reports", 1)
            payload = json.loads(Path(result["analysis_path"]).read_text(encoding="utf-8"))
        flight = payload["flight"]
        findings = [f for f in payload.get("findings") or [] if isinstance(f, dict) and f.get("engine") == "communications"]
        fixture = {
            "note": "Frozen by pilotdriven_odss_dashboard/scripts/freeze_enroute_contact_fixtures.py from the genuine private-corpus OFP named here; never edited by hand.",
            "frozen": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "source": {"file": name, "sha256": hashlib.sha256(source.read_bytes()).hexdigest(), "case": case},
            "rule": payload["view"]["briefing"]["enroute_contact"]["rule"],
            "flight": slim_flight(flight),
            "findings": findings,
            "enroute_contact": payload["view"]["briefing"]["enroute_contact"],
        }
        target = out_dir / f"{case}.json"
        target.write_text(json.dumps(fixture, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        ec = fixture["enroute_contact"]
        print(f"{case}: {len(ec['crossings'])} crossings, {len(ec['procedures'])} procedures, state {ec['state']} -> {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
