from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.odss.reporting import render_pdf
from app.odss.timing import build_timing_view, timing_finding


def finding(engine: str, title: str, summary: str, severity: str = "warning", **data):
    return {
        "engine": engine,
        "severity": severity,
        "title": title,
        "summary": summary,
        "details": ["Representative CI visual-regression content."],
        "data": data,
    }


def sample_flight():
    route = [
        ("EBBR", 0, 50.90, 4.48, None, 32, 2, None),
        ("-EDUU", 17, 50.20, 6.63, "EDUU", None, 2, "L607"),
        ("ENITA", 41, 49.70, 12.47, None, 60, 3, "DCT"),
        ("-LOVV", 53, 48.96, 14.94, "LOVV", None, 3, "DCT"),
        ("UDROS", 140, 42.74, 30.60, None, 111, 1, "UM859"),
        ("REBLO", 207, 40.84, 43.69, None, 154, 0, "UR317"),
        ("MATAL", 215, 40.77, 45.50, None, 159, 2, "M11"),
        ("-UTAV", 307, 36.91, 61.59, "UTAV", None, 3, "A846"),
        ("RANAH", 321, 35.58, 63.20, None, 97, 1, "A846"),
        ("DUDEG", 354, 32.78, 67.45, None, 166, 1, "L750"),
        ("BIROS", 366, 31.67, 69.00, None, 119, 2, "L750"),
        ("-OPKR", 383, 30.00, 70.73, "OPKR", None, 2, "G201"),
        ("ENTRY1", 559, 15.85, 90.34, None, None, None, "L759"),
        ("-VOMF", 580, 13.94, 92.33, "VOMF", None, 3, "L759"),
        ("EXIT1", 590, 13.05, 93.22, None, None, None, "L759"),
        ("TOD", 699, 3.52, 103.13, None, None, 1, "Y514"),
        ("WSSS", 727, 1.36, 103.99, None, 4, 0, "DCT"),
    ]
    waypoints = []
    for name, actm, lat, lon, fir, msa, vws, airway in route:
        waypoints.append({
            "name": name,
            "actm_minutes": actm,
            "latitude": lat,
            "longitude": lon,
            "fir_boundary": fir,
            "airway_in": airway,
            "msa_hundreds_ft": msa,
            "msa_asterisk": bool(msa and msa > 100),
            "vws": vws,
        })
    return {
        "flight_number": "SQ303",
        "flight_date": "16JUL26",
        "departure": "EBBR",
        "destination": "WSSS",
        "departure_runway": "07R",
        "destination_runway": "20R",
        "scheduled_departure_utc": "2026-07-16T09:45:00+00:00",
        "scheduled_arrival_utc": "2026-07-16T22:40:00+00:00",
        "aircraft_type": "A350-941",
        "registration": "9V-SMR",
        "ground_distance_nm": 5933,
        "planned_level_profile": "BRU/350/ENITA/370/UDROS/390/MEMID/410",
        "route_waypoints": waypoints,
        "masses": {
            "planned_zfw_kg": 166486,
            "planned_landing_weight_kg": 175802,
            "planned_takeoff_weight_kg": 245529,
        },
        "fuel": {
            "fuel_in_tanks_kg": 79643,
            "trip_fuel_kg": 69727,
            "planned_destination_fuel_kg": 9316,
        },
        "alternates": [{"airport": "WSAP", "runway": "20", "approach": "CAT1DME"}],
        "edto": {
            "entry_actm_minutes": 559,
            "exit_actm_minutes": 590,
            "etp_actm_minutes": [574],
            "airports": [{
                "airport": "VTBD",
                "runway": "21L",
                "approach": "CAT1+VORDME",
                "period_start_utc": "2026-07-16T19:53:00+00:00",
                "period_end_utc": "2026-07-16T22:09:00+00:00",
            }],
        },
        "weather": [
            {"location": "EBBR", "record_type": "METAR", "text": "SA 160620 05003KT 020V080 CAVOK 19/14 Q1019 NOSIG"},
            {"location": "WSSS", "record_type": "METAR", "text": "SA 160630 17007KT 9999 FEW018TCU FEW020CB SCT300 31/25 Q1011 NOSIG"},
        ],
        "notams": [],
        "bobcat": None,
        "personal_notes": [],
    }


def sample_findings():
    return [
        finding("mel", "MEL 44-15-02A - PA handset", "Verify operative handset coverage at the applicable exit pair."),
        finding("cddl", "CDL 57-23 - MLG door seal", "Exact approved performance penalty requires source review.", "unknown"),
        finding("performance", "Take-off performance summary", "Conditional RTOW margin 22,504 kg.", "information"),
        finding("notam", "Departure NOTAM 1A2469/26", "TWY Y closed due work in progress.", "warning", role="departure", priority_score=8),
        finding("notam", "Destination NOTAM SX120/25", "Runway closure schedule requires arrival-period review.", "critical", role="destination", priority_score=20),
        finding("notam", "Destination Alternate NOTAM 1A1772/26", "RWY 02 approach crossbar lights partly obstructed.", "warning", role="destination alternate", priority_score=9),
        finding("weather", "Enroute weather - VABB", "Monsoon rain, haze and temporary thunderstorms along the South Asian segment."),
        finding("weather", "EDTO airport weather - VTBD", "Temporary TSRA window requires delay sensitivity review."),
        finding("communications", "Early ATC/FIR action before OAKX", "ACTM 05.11 - Kabul TIBA.", "warning", action_actm_minutes=311),
        finding("communications", "Early ATC/FIR action before OPLR", "ACTM 05.52 - Lahore ACC.", "warning", action_actm_minutes=352),
        finding("terrain", "High-MSA event 1", "ACTM 03.08-03.55, max 159*.", "warning", start_actm_minutes=188),
        finding("terrain", "High-MSA event 2", "ACTM 05.24-06.26, max 166*.", "warning", start_actm_minutes=324),
        finding("vws", "VWS event 1", "ACTM 00.02-00.20, maximum 007.", "warning", start_actm_minutes=2),
        finding("depressurisation", "Profile 1 - RANAH to UPVAL", "Applicable chart 10-5; critical point DUDEG.", "warning", chart_number="10-5", critical_point="DUDEG", start_actm_minutes=321),
        finding("edto", "EDTO checked-period summary", "ACTM 09.19-09.50.", "information", start_actm_minutes=559),
        finding("qa", "Destination fuel reconciliation", "Calculated and stated destination fuel are consistent.", "information"),
    ]


def main() -> None:
    output = Path("visual-samples")
    output.mkdir(exist_ok=True)
    flight = sample_flight()
    findings = sample_findings()
    flight["actual_takeoff_utc"] = "2026-07-16T09:52:00+00:00"
    flight["timing_view"] = build_timing_view(
        flight,
        findings,
        flight["actual_takeoff_utc"],
    )
    findings.append(timing_finding(flight["timing_view"]))
    render_pdf(flight, findings, [], 1, output / "sample-level-1.pdf")
    render_pdf(flight, findings, [], 2, output / "sample-level-2.pdf")


if __name__ == "__main__":
    main()
