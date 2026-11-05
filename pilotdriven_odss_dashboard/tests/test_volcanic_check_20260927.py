"""VOLCANIC-CHECK-436 (independent QA of release 436, 27 Sep 2026, item 2: per-flight checklist and Pacific volcanic
assurance).

David, 24 Sep 2026 06:51: "I also recall that I asked you to make sure the AI goes thru the checklist of items it must
perform for each flight. That list has disappeared? What happens next time say to the Pacific with the volcano
advisories?"

Proven on release 436 (80b535d) with genuine OFPs and blocked live sources:
- PDF page 6 printed "SOURCE ASSURANCE: every listed source record is held." while the VA SIGMET feed and every
  responsible VAAC were unreached (SQ34 SIN-SFO) - the list named only OFP sources;
- PDF page 5's volcanic-ash card never named a VAAC or its reach, and printed the same sentence whether the live sources
  were off, failed or answered with nothing;
- the page-1 tile read "HELD" from a volcano NOTAM alone and "NO DATA" beside a feed VA SIGMET crossing the route;
- the checklist's VA/VAAC row was always "UNRESOLVED" with one generic sentence, and the page-6 card that lists what
  PD checked printed four of the checklist's rows.

The repair composes the four volcanic sources once (app/odss/volcanic_check.py) and every surface prints that record: the
checklist row, page 1, page 5, page 6's source line, and the dashboard (through the view). Page 6 lists every checklist
row grouped by its state.

Synthetic flights and provider answers are LABELLED SYNTHETIC / SIMULATED; genuine OFPs read the private corpus and never
reach a network (sockets are blocked in-process).
"""
from __future__ import annotations

import os
import socket
import gzip
import hashlib
import json
import tarfile
import io
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.odss import vaa as vaa_module
from app.odss.briefing import build_briefing_view
from app.odss.combined_brief import _operational_coverage_receipt
from app.odss.vaa import build_direct_vaa_source_review, evaluate_vaa

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT.parent / "private_cfp_corpus"
SQ34 = "lido-briefing_SQ_34_15Aug2026_SIN_SFO.pdf"
SQ38 = "SQ38-29AUG2026-OFP-for-prod-proof.pdf"
SQ366 = "SQ36604082026SIN.pdf"
PROD_VAAC = "jma-tokyo,anchorage,darwin,toulouse,gts-mirror,wifs-global"


# ------------------------------------------------------------------------------------------ SYNTHETIC flights

def flight(points: list[tuple[float, float]]) -> dict:
    """LABELLED SYNTHETIC: the smallest flight the briefing view accepts, flying through ``points``."""
    return {
        "flight_number": "SQ900", "departure": "ZZAA", "destination": "ZZBB", "departure_runway": "01",
        "destination_runway": "19", "flight_date": "22JUL26", "scheduled_departure_utc": "2026-07-22T04:00:00+00:00",
        "scheduled_arrival_utc": "2026-07-22T10:00:00+00:00", "aircraft_type": "A350-900", "registration": "9V-SXX",
        "ground_distance_nm": 3000, "planned_level_profile": "P0/350",
        "route_waypoints": [
            {"name": f"P{i}", "actm_minutes": 60 * i, "latitude": lat, "longitude": lon, "fir_boundary": None,
             "airway_in": "DCT", "msa_hundreds_ft": 4, "vws": 1}
            for i, (lat, lon) in enumerate(points)
        ],
        "masses": {}, "fuel": {}, "alternates": [], "edto": {}, "weather": [], "notams": [], "personal_notes": [],
        "bobcat": None,
    }


def feed(advisories: list[dict] | None = None, *, status: str = "available", freshness: str = "fresh",
         retrieved: str = "2026-07-22T03:55:00+00:00") -> dict:
    """SIMULATED: the international VA SIGMET feed's answer (current active SIGMETs only, as the live provider).

    ITEM2-VOLCANIC: an answer is only current for a flight when it was retrieved in the window it can cover, so a
    simulated answer is stamped at the time it would have been asked (5 min before the synthetic flight's departure,
    or 30 min before a genuine flight's)."""
    return {
        "schema_version": "1.0", "provider": "noaa-awc-international-sigmet", "source_url": "https://aviationweather.gov",
        "status": status, "retrieved_at_utc": retrieved, "coverage_status": "current_active_sigmets",
        "coverage_start_utc": None, "coverage_end_utc": None, "freshness_status": freshness,
        "advisories": advisories or [], "parse_warnings": [], "raw_sha256": "simulated",
    }


def crossing(ring: list[list[float]]) -> dict:
    """SIMULATED: a VA SIGMET polygon, SFC-FL600, valid for the whole synthetic flight."""
    return {
        "advisory_id": "SIM-VA-1", "hazard": "VA", "fir_id": "SIMX", "valid_from_utc": "2026-07-22T00:00:00+00:00",
        "valid_to_utc": "2026-07-22T14:00:00+00:00", "lower_flight_level": 0, "upper_flight_level": 600,
        "geometry": {"type": "Polygon", "coordinates": [ring]}, "raw_text": "SIMULATED VA SIGMET", "raw_sha256": "sim",
    }


def centres(answers: dict[str, tuple[str, int]]) -> tuple[list[dict], list[dict]]:
    """SIMULATED: per-centre VAAC answers {centre: (status, advisory count)} and the matching mounted list."""
    snapshots = [
        {"centre": centre, "provider": f"sim-{centre.lower()}", "status": status, "coverage_status": "simulated",
         # Every live connector stamps its answer (ITEM2-VOLCANIC: currency for the flight is a held fact).
         "retrieved_at_utc": "2026-07-22T03:55:00+00:00",
         "advisories": [{"advisory_number": f"2026/{i:03d}", "issued_at_utc": "2026-07-22T02:00:00+00:00",
                         "volcano": "SIMULATED", "raw_sha256": f"{centre}{i}"} for i in range(count)]}
        for centre, (status, count) in answers.items() if status != "not_mounted"
    ]
    mounted = [{"token": centre.lower(), "centre": centre, "provider": f"sim-{centre.lower()}"}
               for centre, (status, _) in answers.items() if status != "not_mounted"]
    return snapshots, mounted


def view_of(route: dict, feed_snapshot: dict | None, answers: dict[str, tuple[str, int]], *, ofp_section: str = "unavailable",
            weather: list[dict] | None = None) -> dict:
    if weather:
        route["weather"] = weather
    review = evaluate_vaa(route, feed_snapshot or {"status": "disabled"}, {"status": ofp_section})
    review["product"] = "VA_SIGMET"
    snapshots, mounted = centres(answers)
    route["va_sigmet_review"] = review
    route["direct_vaa_source_review"] = build_direct_vaa_source_review(route, snapshots=snapshots, mounted=mounted)
    route["vaa_review"] = dict(review)
    return build_briefing_view(route, [], [])


EQUATOR = [(0.0, 100.0), (0.0, 110.0)]           # DARWIN's area, settled
# DARWIN, TOKYO, TOKYO (the Kuril band, settled since ITEM2-VOLCANIC), ANCHORAGE (Oakland Oceanic north of the split),
# and one point no row of Doc 9766 assigns by coordinates: Edmonton FIR north of N60 with no FIR named on the route.
PACIFIC = [(0.0, 110.0), (35.0, 140.0), (47.0, 160.0), (45.0, 170.0), (63.0, -130.0)]
BOX = [[104.0, -2.0], [106.0, -2.0], [106.0, 2.0], [104.0, 2.0], [104.0, -2.0]]


def assurance(view: dict) -> dict[str, dict]:
    return {row["source"]: row for row in view["source_assurance"]}


def vaa_row(view: dict) -> dict:
    receipt = _operational_coverage_receipt({}, view, [], None)
    return next(row for row in receipt["rows"] if row["key"] == "vaa_vaac")


# ---------------------------------------------------------------------------------------------- the states

def test_a_feed_sigmet_crossing_the_route_is_found_on_every_surface_record():
    view = view_of(flight(EQUATOR), feed([crossing(BOX)]), {"DARWIN": ("available", 0)})
    check = view["vaa"]["check"]
    assert check["state"] == "FOUND"
    assert check["tile"] == "AFFECTING"
    assert "SIM-VA-1 cross the filed route/time/level" in check["line"]
    row = vaa_row(view)
    assert (row["state"], row["detail"]) == ("FOUND", check["line"])


def test_no_live_source_answering_is_unavailable_never_checked():
    view = view_of(flight(EQUATOR), feed(status="unavailable"), {"DARWIN": ("unavailable", 0)})
    check = view["vaa"]["check"]
    assert check["state"] == "UNAVAILABLE"
    assert "VA SIGMET feed: not reached" in check["line"]
    assert "Responsible VAACs DARWIN: none reached" in check["line"]
    assert vaa_row(view)["state"] == "UNAVAILABLE"
    sources = assurance(view)
    assert sources["VA SIGMET FEED"]["status"] == "NOT REACHED"
    assert sources["RESPONSIBLE VAACS"]["status"] == "NOT REACHED"


def test_sources_that_were_never_configured_are_not_queried():
    view = view_of(flight(EQUATOR), None, {"DARWIN": ("not_mounted", 0)})
    check = view["vaa"]["check"]
    assert check["state"] == "NOT QUERIED"
    assert "VA SIGMET feed: not queried" in check["line"]
    assert "Responsible VAACs DARWIN: not queried" in check["line"]
    assert assurance(view)["VA SIGMET FEED"]["status"] == "NOT QUERIED"


def test_every_source_reached_with_nothing_held_is_the_only_checked_no_match():
    view = view_of(flight(EQUATOR), feed(), {"DARWIN": ("available", 0)})
    check = view["vaa"]["check"]
    assert check["state"] == "CHECKED · NO MATCH", check
    assert check["tile"] == "NO DATA"
    assert "OFP VA SIGMET: 'no data' printed" in check["line"]
    assert "VA SIGMET feed: reached, no current VA SIGMET crosses the route" in check["line"]
    assert "Responsible VAACs DARWIN: all reached; no advisory held" in check["line"]
    assert assurance(view)["RESPONSIBLE VAACS"]["status"] == "REACHED"


def test_an_unsettled_responsibility_keeps_a_fully_reached_pacific_route_unresolved():
    answers = {"ANCHORAGE": ("available", 0), "DARWIN": ("available", 0), "TOKYO": ("available", 0)}
    view = view_of(flight(PACIFIC), feed(), answers)
    check = view["vaa"]["check"]
    assert check["unsettled_points"] == 1
    assert check["state"] == "UNRESOLVED"
    assert "all reached; no advisory held; responsibility unsettled for 1 route point" in check["line"]
    # ITEM2-VOLCANIC: every centre answered, so the reach is REACHED; the unsettled point is its own qualifier. PARTIAL
    # (some centres not reached) used to stand for both facts.
    assert assurance(view)["RESPONSIBLE VAACS"]["status"] == "REACHED · NOT SETTLED"


def test_partial_reach_names_the_centres_not_reached():
    answers = {"ANCHORAGE": ("unavailable", 0), "DARWIN": ("available", 0), "TOKYO": ("unavailable", 0)}
    check = view_of(flight(PACIFIC), feed(), answers)["vaa"]["check"]
    assert check["state"] == "UNRESOLVED"
    assert "DARWIN reached, NOT reached: ANCHORAGE, TOKYO" in check["line"]
    assert check["not_reached"] == ["ANCHORAGE", "TOKYO"]


def test_held_direct_advisories_are_never_a_match():
    check = view_of(flight(EQUATOR), feed(), {"DARWIN": ("available", 2)})["vaa"]["check"]
    assert check["state"] == "UNRESOLVED"
    assert "2 advisories held, route applicability not assessed" in check["line"]
    assert check["tile"] == "HELD"


def test_an_ofp_va_sigmet_record_keeps_the_row_open_even_with_every_source_reached():
    weather = [{"location": "WIIF", "record_type": "VA_SIGMET", "source_page": 13, "text": (
        "WIIF JAKARTA FIR WV SIGMET 08 VALID 220400/220700 VA ERUPTION MT KRAKATAU WI S0200 E10400 - S0200 E10600 - "
        "N0200 E10600 SFC/FL400")}]
    check = view_of(flight(EQUATOR), feed(), {"DARWIN": ("available", 0)}, ofp_section="present", weather=weather)["vaa"]["check"]
    assert check["state"] == "UNRESOLVED"
    assert check["tile"] == "HELD"
    assert check["line"].startswith("OFP VA SIGMET: 1 printed (")


def test_a_stale_feed_is_unresolved():
    check = view_of(flight(EQUATOR), feed(freshness="stale"), {"DARWIN": ("available", 0)})["vaa"]["check"]
    assert check["state"] == "UNRESOLVED"
    assert "VA SIGMET feed: reached, not current" in check["line"]


# --------------------------------------------------------------------------- genuine OFPs, SIMULATED provider answers

def _block_network(monkeypatch):
    def blocked(*_args, **_kwargs):
        raise OSError("network blocked by test_volcanic_check_20260927 (offline)")
    monkeypatch.setattr(socket, "getaddrinfo", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)


def _sources(monkeypatch, scenario: str, crossing_at: tuple[float, float] | None = None,
             retrieved: str = "2026-07-22T03:55:00+00:00"):
    """Production source configuration, with every provider answer SIMULATED in-process for ``scenario``:
    blocked (every fetch fails), reached_empty (every source answers with nothing), crossing (a VA SIGMET box
    across ``crossing_at``, valid all day). Every answer is stamped ``retrieved``."""
    _block_network(monkeypatch)
    monkeypatch.setenv("ODSS_VA_SIGMET_SOURCE", "awc")
    monkeypatch.setenv("ODSS_VAAC_ADVISORY_SOURCE", PROD_VAAC)

    def live(hazard_code: str = "VA") -> dict:
        if scenario == "blocked":
            return {**feed(status="unavailable", retrieved=retrieved), "error": "network blocked (test)"}
        advisories = []
        if scenario == "crossing" and crossing_at:
            lat, lon = crossing_at
            ring = [[lon - 1, lat - 1], [lon + 1, lat - 1], [lon + 1, lat + 1], [lon - 1, lat + 1], [lon - 1, lat - 1]]
            advisories = [{**crossing(ring), "valid_from_utc": "2026-01-01T00:00:00+00:00", "valid_to_utc": "2026-12-31T00:00:00+00:00"}]
        return feed(advisories, retrieved=retrieved)

    def mounted_answers(_flight, mounted):
        status = "unavailable" if scenario == "blocked" else "available"
        return [{"centre": entry["centre"], "provider": entry.get("provider"), "status": status,
                 "coverage_status": "simulated", "advisories": [], "retrieved_at_utc": retrieved}
                for entry in mounted]

    monkeypatch.setattr(vaa_module, "live_vaa_snapshot", live)
    monkeypatch.setattr(vaa_module, "fetch_mounted_vaac_snapshots", mounted_answers)


def _asked_before(parsed: dict) -> str:
    """When a briefing for the genuine flight would have asked its sources: 30 min before scheduled departure."""
    departure = datetime.fromisoformat(parsed["scheduled_departure_utc"])
    return (departure - timedelta(minutes=30)).isoformat()


def genuine_view(monkeypatch, name: str, scenario: str) -> dict:
    from app.odss.parser import extract_pages, parse_lido

    source = CORPUS / name
    if not source.is_file():
        pytest.skip(f"private corpus file {name} is not on this machine")
    pages = extract_pages(source)
    parsed = parse_lido(pages, name)
    points = [(w["latitude"], w["longitude"]) for w in parsed["route_waypoints"] if w.get("latitude") is not None]
    _sources(monkeypatch, scenario, points[len(points) // 2], retrieved=_asked_before(parsed))
    vaa_module.assess_volcanic_ash(parsed, pages)
    return build_briefing_view(parsed, [], [])


@pytest.mark.parametrize("name", [SQ34, SQ38])
def test_genuine_pacific_routes_with_every_live_source_failed_are_unavailable_and_named(monkeypatch, name):
    check = genuine_view(monkeypatch, name, "blocked")["vaa"]["check"]
    assert check["state"] == "UNAVAILABLE"
    assert {"ANCHORAGE", "TOKYO", "WASHINGTON"} <= set(check["responsible"]), check["responsible"]
    assert check["reached"] == []
    # The 21 Aug encoding left the Kuril/Kamchatka band and the NE Pacific unassigned on these routes; ITEM2-VOLCANIC
    # encodes the Oakland Oceanic / Anchorage FIR boundaries Doc 9766 bounds those rows by, and both are settled.
    assert check["unsettled_points"] == 0
    assert "VA SIGMET feed: not reached" in check["line"]
    assert ": none reached" in check["line"]


@pytest.mark.parametrize("name", [SQ34, SQ38])
def test_genuine_pacific_routes_fully_reached_stay_unresolved(monkeypatch, name):
    view = genuine_view(monkeypatch, name, "reached_empty")
    check = view["vaa"]["check"]
    assert check["state"] == "UNRESOLVED"
    assert "all reached; no advisory held" in check["line"]
    # Settled and fully reached, but the routes end in US domestic FIRs, whose VA SIGMETs the international feed
    # does not carry: never a clear check.
    assert check["feed_status"] == "REACHED · COVERAGE GAP"
    assert "are not in this feed" in check["line"]


def test_genuine_sq38_volcano_notice_is_a_notice_not_held_products(monkeypatch):
    check = genuine_view(monkeypatch, SQ38, "reached_empty")["vaa"]["check"]
    assert check["ofp_section"] == "no_data"
    assert any("GREAT SITKIN" in notice for notice in check["ofp_notices"]), check["ofp_notices"]
    assert check["tile"] == "NOTICE"


def test_genuine_settled_europe_route_fully_reached_is_checked_no_match(monkeypatch):
    check = genuine_view(monkeypatch, SQ366, "reached_empty")["vaa"]["check"]
    assert check["unsettled_points"] == 0
    assert check["state"] == "CHECKED · NO MATCH", check["line"]


def test_genuine_settled_route_with_a_simulated_crossing_is_found(monkeypatch):
    check = genuine_view(monkeypatch, SQ366, "crossing")["vaa"]["check"]
    assert check["state"] == "FOUND", check["line"]
    assert check["tile"] == "AFFECTING"


# -------------------------------------------------------------------------------------------- the actual PDF

def genuine_pdf_text(monkeypatch, tmp_path: Path, name: str, scenario: str) -> list[str]:
    import fitz

    from app.analysis import run_odss_analysis
    from app.odss.combined_brief import render_combined_briefing

    source = CORPUS / name
    if not source.is_file():
        pytest.skip(f"private corpus file {name} is not on this machine")
    for key in ("ODSS_SIGMET_SOURCE", "ODSS_OPMET_SOURCE", "ODSS_TC_TRACK_SOURCE", "ODSS_TC_SIGMET_SOURCE",
                "ODSS_ADWX_SOURCE", "ODSS_WEATHER_CHART_AI"):
        monkeypatch.setenv(key, "disabled")
    for key in ("ODSS_DIRECT_SIGMET_SOURCES", "ODSS_TCA_ADVISORY_SOURCE", "ODSS_WEATHER_CHART_MODEL"):
        monkeypatch.setenv(key, "")
    monkeypatch.setenv("ODSS_DATA_DIR", str(tmp_path / "data"))
    from app.odss.parser import extract_pages, parse_lido
    _sources(monkeypatch, scenario, retrieved=_asked_before(parse_lido(extract_pages(source), name)))
    result = run_odss_analysis(source, tmp_path / "results", tmp_path / "reports", 1)
    import json
    analysis = json.loads(Path(result["analysis_path"]).read_text())
    out = tmp_path / "briefing.pdf"
    render_combined_briefing(analysis["flight"], analysis["findings"], analysis["view"].get("warnings") or [], out,
                             source_pdf_path=str(source), weather_charts=analysis.get("weather_charts"),
                             company_briefing_references=None)
    return [" ".join(page.get_text().split()) for page in fitz.open(str(out))]


def checklist_group(closing: str, item: str) -> str | None:
    """The group page 6 prints ``item`` under, in whichever capacity form the page took: whole ("CHECKED: a, b." ...),
    open ("Open: a, b (unresolved); c (source unavailable)." - an item absent from Open is checked) or counts (None: no
    item is named, only the counts)."""
    import re

    card = closing.split("PD CHECKS (", 1)[1].split("SOURCE CONTROL", 1)[0].split("FIR / COMMUNICATION", 1)[0]
    whole = re.findall(r"(CHECKED|UNRESOLVED|SOURCE UNAVAILABLE|NOT QUERIED): ([^.]*)\.", card)
    for title, names in whole:
        if item in [name.strip() for name in names.split(",")]:
            return title.lower()
    if "Open:" in card:
        for names, word in re.findall(r"([^;:]+?) \((unresolved|source unavailable|not queried)\)", card.split("Open:", 1)[1]):
            if item in [name.strip() for name in names.split(",")]:
                return word
        return "checked"
    return None


def checklist_counts(closing: str) -> str:
    return closing.split("PD CHECKS (", 1)[1].split(".", 1)[0]


def test_the_pacific_pdf_never_claims_complete_sources_and_names_every_unreached_centre(monkeypatch, tmp_path):
    pages = genuine_pdf_text(monkeypatch, tmp_path, SQ34, "blocked")
    closing = pages[-1]
    assert "every listed source record is held" not in closing
    assert "SOURCE ASSURANCE:" in closing
    assert "VA SIGMET FEED" in closing and "RESPONSIBLE VAACS" in closing
    # Page 6 lists what PD checked, grouped by result, with the volcanic row where its sources left it (whole, or in the
    # page's compact capacity step, which still names every open item).
    assert "PD CHECKS (" in closing
    assert checklist_group(closing, "volcanic ash") in {"source unavailable", None}, closing
    assert "source unavailable" in checklist_counts(closing), closing
    weather = next(page for page in pages if "VOLCANIC ASH" in page and "FLIGHT HAZARD KEY" in page)
    ash = weather.split("VOLCANIC ASH", 1)[1].split("FLIGHT HAZARD KEY", 1)[0]
    for centre in ("ANCHORAGE", "DARWIN", "TOKYO", "WASHINGTON"):
        assert centre in ash, (centre, ash)
    assert "none reached" in ash and "VA SIGMET feed: not reached" in ash


def test_the_settled_route_pdf_states_the_completed_volcanic_check(monkeypatch, tmp_path):
    pages = genuine_pdf_text(monkeypatch, tmp_path, SQ366, "reached_empty")
    closing = pages[-1]
    assert checklist_group(closing, "volcanic ash") in {"checked", None}, closing
    weather = next(page for page in pages if "VOLCANIC ASH" in page and "FLIGHT HAZARD KEY" in page)
    ash = weather.split("VOLCANIC ASH", 1)[1].split("FLIGHT HAZARD KEY", 1)[0]
    assert "all reached; no advisory held" in ash
    assert "no current VA SIGMET crosses the route" in ash


# --------------------------------------------------------------- actual archived pre-composed-check saved packs

LEGACY_MANIFEST = json.loads((ROOT / "tests/fixtures/saved-analysis-v74-manifest.json").read_text())


def _legacy_analysis(case: dict, root: Path, bundle: Path | None = None) -> tuple[dict, bytes]:
    path = root / case["file"]
    if bundle is None:
        compressed = path.read_bytes()
    else:
        with tarfile.open(bundle, "r:") as archive:
            matches = [member for member in archive.getmembers() if member.name == case["file"]]
            assert len(matches) == 1 and matches[0].isfile(), f"Missing or ambiguous historical fixture: {case['file']}"
            compressed = archive.extractfile(matches[0]).read()
    # Required input: missing/corrupt files fail in local and container runs alike.
    assert hashlib.sha256(compressed).hexdigest() == case["compressed_sha256"], f"Historical fixture changed: {path}"
    raw = gzip.decompress(compressed)
    assert hashlib.sha256(raw).hexdigest() == case["sha256"], f"Historical fixture changed: {path}"
    return json.loads(raw), raw


@pytest.mark.parametrize("case", LEGACY_MANIFEST["cases"], ids=lambda case: case["id"])
def test_a_saved_v74_pack_reopens_with_the_composed_check_and_the_checklist(case, monkeypatch):
    """Recover the lost absolute-path regression using actual archived v74 SQ34 inputs.

    These stored views predate the composed check/checklist. The manifest records their
    provenance and provider simulations; none is passed off as the missing release-436
    gate file. All original assertions remain, now exercised for four evidence conditions.
    """

    from app.odss.flight_briefing_publication import current_rules_briefing

    _block_network(monkeypatch)
    root = Path(os.environ.get("PILOTDRIVEN_PRIVATE_CFP_CORPUS_DIR", str(CORPUS))) / "saved-analysis-v74"
    bundle_value = os.environ.get("PILOTDRIVEN_SAVED_ANALYSIS_BUNDLE")
    bundle = Path(bundle_value) if bundle_value else None
    analysis, raw = _legacy_analysis(case, root, bundle)
    stored = analysis["view"]["briefing"]
    assert stored["publication_rules"] == LEGACY_MANIFEST["publication_rules"]
    assert "coverage_receipt" not in stored and "check" not in (stored.get("vaa") or {})
    served = current_rules_briefing(analysis)
    assert served["rebuilt_from_held_analysis"] is True
    rebuilt = served["briefing"]
    check = rebuilt["vaa"]["check"]
    assert check["state"] in {"FOUND", "CHECKED · NO MATCH", "UNRESOLVED", "UNAVAILABLE", "NOT QUERIED"}
    assert check["state"] == case["expected_state"]
    assert {"ANCHORAGE", "TOKYO"} <= set(check["responsible"])
    assert check["unsettled_points"] > 0 and check["state"] != "CHECKED · NO MATCH"
    rows = {row["key"]: row for row in rebuilt["coverage_receipt"]["rows"]}
    assert rows["vaa_vaac"]["detail"] == check["line"]
    assert "atc_fir_calls" in rows
    assert _legacy_analysis(case, root, bundle)[1] == raw


def test_missing_historical_input_fails_instead_of_skipping(tmp_path):
    with pytest.raises(FileNotFoundError):
        _legacy_analysis(LEGACY_MANIFEST["cases"][0], tmp_path)


def test_modified_historical_input_fails_instead_of_becoming_an_oracle(tmp_path):
    case = LEGACY_MANIFEST["cases"][0]
    (tmp_path / case["file"]).write_bytes(gzip.compress(b'{}', mtime=0))
    with pytest.raises(AssertionError, match="Historical fixture changed"):
        _legacy_analysis(case, tmp_path)


@pytest.mark.parametrize("damage", ["missing_bundle", "missing_member", "duplicate", "link", "modified"])
def test_build_bundle_damage_fails_without_falling_back_to_local_inputs(tmp_path, damage):
    case = LEGACY_MANIFEST["cases"][0]
    bundle = tmp_path / "bundle.tar"
    if damage != "missing_bundle":
        with tarfile.open(bundle, "w") as archive:
            count = 2 if damage == "duplicate" else 1
            for _ in range(count):
                member = tarfile.TarInfo("unrelated.json.gz" if damage == "missing_member" else case["file"])
                if damage == "link":
                    member.type = tarfile.SYMTYPE
                    member.linkname = "/outside"
                    archive.addfile(member)
                else:
                    content = gzip.compress(b'{}', mtime=0)
                    member.size = len(content)
                    archive.addfile(member, io.BytesIO(content))
    with pytest.raises((FileNotFoundError, AssertionError)):
        _legacy_analysis(case, CORPUS / "saved-analysis-v74", bundle)
