"""F19 of Codex's independent re-QA of release 482 (11 Oct 2026): a confirmed exclusion at any role airport reaches the PDF.

Genuine SQ438 SIN-MLE (7 Oct), A350-941, departure WSSS: SX168/26 "DOWNGRADE OF ACFT STAND 603 TO CODE C". The dashboard
said the A350 (Code E) is above this limit (Code C), but the downloaded six-page briefing never said so. Page 2 carried
the destination's ground card only, so a departure exclusion had no card, and page 2 spent a slot on "Destination NOTAM
SX5/26", a notice the VRMM arrival card already printed. The same notice reversed (SQ437, WSSS destination) and SQ326's
EDDF A3671/26 printed, because both are destination exclusions.

Now every airport the flight holds in another role (departure, destination alternate, EDTO, fuel en-route) has its
confirmed active exclusions carried in one page-2 card, and a card carrying a confirmed exclusion is never crowded off
the six cards: it displaces first a notice card another selected card already prints, then the lowest-ranked card.
A promoted exclusion line whose limit names its own subject states that limit in the notice's own words, because the
summary can describe a different clause (SX168/26's summary is the TXL N4 closure, while the limit is on stand 603).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.odss import aircraft_restriction_applicability as rule

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT.parent / "private_cfp_corpus"

SX168 = ("TEMPO CLOSURE OF TXL N4 BEHIND ACFT STAND 604 AND DOWNGRADE OF ACFT STAND 603 TO CODE C DUE TO CONST WORK. "
         "GND MARKINGS AT STAND 603 WILL BE REMOVED.")
SX168_SUMMARY = "TXL N4 BEHIND STAND 604 closed during the applicable departure window."
EXCLUDES = "above this limit (Code C), so the notice excludes this aircraft from the stated area."
STATED = 'Stated limit: "DOWNGRADE OF ACFT STAND 603 TO CODE C".'


def _notice(notam_id: str, item_e_text: str, summary: str, aircraft_type: str, role: str, **extra) -> dict:
    from app.odss.briefing import _compact_notam_family

    item = {
        "notam_id": notam_id, "item_e_text": item_e_text, "summary": summary, "compact_text": summary,
        "pertinence_kind": extra.pop("pertinence_kind", "taxiway_closure"), "pertinence_rank": extra.pop("pertinence_rank", 4),
        "severity": "warning", "applicability": "active", "stateAtReference": "active_at_reference",
        "role": role, "source_page": extra.pop("source_page", 26), **extra,
    }
    item.setdefault("signal_family", _compact_notam_family(item))
    check = rule.notam_aircraft_size_check({"aircraft_type": aircraft_type}, item)
    if check:
        item["aircraft_size_check"] = check
    return item


def _panel(icao: str, roles: list[str], role_keys: list[str], *items: dict, summary_ids: tuple[str, ...] = ()) -> dict:
    return {
        "icao": icao, "roles": roles, "role": roles[0], "role_keys": role_keys,
        "selected_notams": list(items),
        "card_summary_lines": [
            {"kind": "notam", "label": row["notam_id"], "notam_id": row["notam_id"], "text": row["compact_text"],
             "signal_family": row["signal_family"], "source_page": row.get("source_page"),
             **({"aircraft_size_check": row["aircraft_size_check"]} if row.get("aircraft_size_check") else {})}
            for row in items if row["notam_id"] in summary_ids
        ],
    }


def _sx168(aircraft_type: str = "A350-941", role: str = "departure", **extra) -> dict:
    return _notice("SX168/26", SX168, SX168_SUMMARY, aircraft_type, role, **extra)


def _project(panels: list[dict], findings: list[dict] | None = None) -> list[dict]:
    from app.odss.briefing import _decision_finding_projection

    return _decision_finding_projection(list(findings or []), airport_panels=panels)


def _cards(panels: list[dict], engine: str) -> list[dict]:
    return [row for row in _project(panels) if row["engine"] == engine]


# --- roles -----------------------------------------------------------------------------------------------------

@pytest.mark.parametrize(("roles", "role_keys", "where"), [
    (["departure"], ["departure"], "WSSS departure"),
    (["destination alternate"], ["alternate"], "WSSS destination alternate"),
    (["EDTO"], ["edto"], "WSSS EDTO"),
    (["fuel enroute airport"], ["fuel_enroute_airport"], "WSSS fuel enroute airport"),
    (["destination alternate", "EDTO"], ["alternate", "edto"], "WSSS destination alternate"),
])
def test_an_exclusion_at_any_other_role_airport_has_a_page_two_card(roles, role_keys, where) -> None:
    role = {"alternate": "destination alternate"}.get(role_keys[0], role_keys[0])
    (card,) = _cards([_panel("WSSS", roles, role_keys, _sx168(role=role))], "aircraft_exclusion")
    assert card["title"] == f"Aircraft-size exclusion at {where}"
    assert card["summary"].startswith(f"SX168/26 - {STATED} A350-941 is Code E (64.75 m wingspan): {EXCLUDES}")
    assert card["target"] == "sec_airports"
    assert "SOURCE" not in card["summary"] and "p26" in card["source_reference"]


def test_a_destination_exclusion_stays_on_the_arrival_card_only() -> None:
    panels = [_panel("WSSS", ["destination"], ["destination"], _sx168(role="destination"))]
    assert _cards(panels, "aircraft_exclusion") == []
    (arrival,) = _cards(panels, "arrival_ground")
    assert f"SX168/26 - {STATED}" in arrival["summary"] and EXCLUDES in arrival["summary"]


def test_one_airport_as_both_departure_and_destination_prints_the_exclusion_once() -> None:
    panels = [_panel("WSSS", ["departure", "destination"], ["departure", "destination"], _sx168(role="destination"))]
    rows = _project(panels)
    assert [row["engine"] for row in rows if "SX168/26" in row["summary"]] == ["arrival_ground"]


def test_departure_and_destination_exclusions_each_keep_their_own_card() -> None:
    eddf = _notice("A3671/26", "TWY L20 LTD TO MAX ACFT TYPE CODE C.", "TWY L20 limited to max aircraft type code C.",
                   "A350-941", "destination", pertinence_kind="taxiway_restriction", source_page=30)
    panels = [
        _panel("WSSS", ["departure"], ["departure"], _sx168()),
        _panel("EDDF", ["destination"], ["destination"], eddf),
    ]
    (departure,) = _cards(panels, "aircraft_exclusion")
    (arrival,) = _cards(panels, "arrival_ground")
    assert "SX168/26" in departure["summary"] and "A3671/26" not in departure["summary"]
    # A limit read without its subject keeps the summary, which names the area.
    assert "A3671/26 - TWY L20 limited to max aircraft type code C. A350-941 is Code E" in arrival["summary"]
    assert "SX168/26" not in arrival["summary"]


def test_exclusions_at_several_airports_share_one_bounded_card_in_role_order() -> None:
    def limit(notam_id: str, twy: str, role: str) -> dict:
        return _notice(notam_id, f"TWY {twy} LTD TO MAX ACFT TYPE CODE C.", f"TWY {twy} limited to code C.", "A350-941", role,
                       pertinence_kind="taxiway_restriction")

    panels = [
        _panel("WSSS", ["departure"], ["departure"], _sx168()),
        _panel("VRMM", ["destination"], ["destination"]),
        _panel("VCBI", ["destination alternate"], ["alternate"], limit("A1/26", "K", "destination alternate")),
        _panel("VOMM", ["EDTO"], ["edto"], limit("A2/26", "M", "edto")),
    ]
    (card,) = _cards(panels, "aircraft_exclusion")
    assert card["title"] == "Aircraft-size exclusions at WSSS departure, VCBI destination alternate, VOMM EDTO"
    summary = card["summary"]
    assert summary.index("WSSS departure: SX168/26") < summary.index("VCBI destination alternate: A1/26")
    assert "A2/26" not in summary, "two lines at most on the card"
    assert summary.endswith("1 further aircraft-size exclusion is held on the dashboard Airports page.")


# --- nothing is concluded, nothing is promoted ------------------------------------------------------------------

@pytest.mark.parametrize("aircraft_type", ["737-8", "B777-312ER"])
def test_an_aircraft_within_the_limit_or_unverified_gets_no_exclusion_card(aircraft_type: str) -> None:
    assert _cards([_panel("WSSS", ["departure"], ["departure"], _sx168(aircraft_type))], "aircraft_exclusion") == []


@pytest.mark.parametrize("extra", [
    {"item_e_text": SX168.replace("TO CODE C DUE TO CONST WORK.", "TO CODE C EXC A350 ACFT.")},
    {"item_e_text": SX168.replace("DUE TO CONST WORK.", "WHEN LVP IN FORCE.")},
    {"stateAtReference": "ended_before_reference"},
    {"applicability": "not_applicable"},
])
def test_an_unresolved_ended_or_inactive_exclusion_gets_no_card(extra: dict) -> None:
    item = _sx168(**{key: value for key, value in extra.items() if key != "item_e_text"})
    if "item_e_text" in extra:
        item = _notice("SX168/26", extra["item_e_text"], SX168_SUMMARY, "A350-941", "departure")
        assert (item.get("aircraft_size_check") or {}).get("status") != "confirmed"
    assert _cards([_panel("WSSS", ["departure"], ["departure"], item)], "aircraft_exclusion") == []


# --- the six cards -------------------------------------------------------------------------------------------

def _six_buckets(*, duplicate: bool) -> list[dict]:
    def finding(engine: str, title: str, **data) -> dict:
        return {"engine": engine, "severity": "warning", "title": title, "summary": f"{title} summary.", "data": data}

    return [
        finding("performance", "Performance check"),
        finding("notam", "Destination NOTAM SX5/26" if duplicate else "Destination NOTAM A9/26",
                role="destination", notam_id="SX5/26" if duplicate else "A9/26"),
        finding("weather", "Weather item"),
        finding("mel", "Deferred item"),
        finding("route_airspace", "Route airspace"),
    ]


def _vrmm_and_wsss() -> list[dict]:
    sx5 = _notice("SX5/26", "TWY C SOUTH OF D2 CLSD", "TWY C south of D2 closed during the applicable destination window.",
                  "A350-941", "destination", source_page=29)
    return [
        _panel("WSSS", ["departure"], ["departure"], _sx168()),
        _panel("VRMM", ["destination"], ["destination"], sx5, summary_ids=("SX5/26",)),
    ]


def test_the_exclusion_displaces_a_notice_card_another_card_already_prints() -> None:
    rows = _project(_vrmm_and_wsss(), _six_buckets(duplicate=True))
    titles = [row["title"] for row in rows]
    assert len(rows) == 6
    assert "Aircraft-size exclusion at WSSS departure" in titles
    assert "VRMM arrival ground constraints" in titles
    assert "Destination NOTAM SX5/26" not in titles, "SX5/26 is already printed on the VRMM arrival card"
    assert {"Performance check", "Weather item", "Deferred item", "Route airspace"} <= set(titles)


def test_without_a_duplicate_the_lowest_ranked_card_gives_way() -> None:
    findings = _six_buckets(duplicate=False)
    findings[0] = {**findings[0], "severity": "critical"}
    findings[3] = {**findings[3], "severity": "information"}
    rows = _project(_vrmm_and_wsss(), findings)
    titles = [row["title"] for row in rows]
    assert len(rows) == 6
    assert "Aircraft-size exclusion at WSSS departure" in titles
    assert "Deferred item" not in titles, "the lowest-ranked card gives way"
    assert "Destination NOTAM A9/26" in titles


def test_without_an_exclusion_the_six_cards_are_unchanged() -> None:
    panels = _vrmm_and_wsss()
    panels[0]["selected_notams"] = [_sx168("737-8")]
    titles = [row["title"] for row in _project(panels, _six_buckets(duplicate=True))]
    assert "Destination NOTAM SX5/26" in titles
    assert not any(title.startswith("Aircraft-size exclusion") for title in titles)


# --- genuine OFPs through the real analysis and the physical six-page PDF ----------------------------------------

def _render(tmp_path: Path, name: str, aircraft_type: str | None = None) -> tuple[list[str], dict]:
    import fitz

    from app.analysis import run_odss_analysis
    from app.odss.briefing import build_briefing_view
    from app.odss.combined_brief import render_combined_briefing
    from app.odss.report_quality import validate_combined_briefing_pdf

    source = CORPUS / name
    if not source.exists():
        pytest.skip(f"private CFP corpus file {name} is not available")
    result = run_odss_analysis(source, tmp_path / "analysis", tmp_path / "legacy", 9438)
    payload = json.loads(Path(result["analysis_path"]).read_text(encoding="utf-8"))
    flight = payload["flight"] if aircraft_type is None else {**payload["flight"], "aircraft_type": aircraft_type}
    warnings = payload.get("view", {}).get("warnings") or []
    pdf = tmp_path / f"{source.stem}.pdf"
    render_combined_briefing(flight, payload["findings"], warnings, pdf, source_pdf_path=str(source),
                             weather_charts=payload.get("weather_charts") or {}, include_audit_appendix=False)
    quality = validate_combined_briefing_pdf(pdf)
    assert quality["valid"], quality
    assert quality["page_count"] == 6
    with fitz.open(pdf) as document:
        pages = [" ".join(page.get_text().split()) for page in document]
    view = build_briefing_view(flight, payload["findings"], warnings, include_dashboard_only_panels=True)
    return pages, view


def test_genuine_sq438_prints_its_departure_exclusion_on_page_two(tmp_path: Path) -> None:
    pages, view = _render(tmp_path, "SQ43807102026SIN.pdf")
    wsss = next(p for p in view["airport_operational_panels"] if p["icao"] == "WSSS")
    check = next(n for n in wsss["selected_notams"] if n["notam_id"] == "SX168/26")["aircraft_size_check"]
    assert check["status"] == "confirmed" and check["restrictsThisAircraft"] is True
    page2 = pages[1]
    assert "Aircraft-size exclusion at WSSS departure" in page2
    assert f"SX168/26 - {STATED} {check['sentence']}" in page2
    assert "VRMM arrival ground constraints" in page2
    assert "Destination NOTAM SX5/26" not in page2, "the VRMM arrival card already prints SX5/26"
    assert sum(check["sentence"] in page for page in pages) == 1


def test_genuine_sq438_with_a_code_c_aircraft_keeps_its_previous_cards(tmp_path: Path) -> None:
    pages, _ = _render(tmp_path, "SQ43807102026SIN.pdf", "737-8")
    assert "Aircraft-size exclusion" not in " ".join(pages)
    assert "Destination NOTAM SX5/26" in pages[1]


@pytest.mark.parametrize(("name", "notam_id", "stated", "airport"), [
    ("SQ43708102026MLE.pdf", "SX168/26", STATED, "WSSS"),
    ("lido-briefing_SQ_326_16Aug2026_SIN_FRA.pdf", "A3671/26", "TWY L20", "EDDF"),
])
def test_genuine_destination_exclusions_stay_on_the_arrival_card(tmp_path: Path, name, notam_id, stated, airport) -> None:
    pages, view = _render(tmp_path, name)
    panel = next(p for p in view["airport_operational_panels"] if p["icao"] == airport)
    check = next(n for n in panel["selected_notams"] if n["notam_id"] == notam_id)["aircraft_size_check"]
    page2 = pages[1]
    assert f"{airport} arrival ground constraints" in page2
    assert f"{notam_id} - {stated}" in page2 and check["sentence"] in page2
    assert "Aircraft-size exclusion" not in page2
