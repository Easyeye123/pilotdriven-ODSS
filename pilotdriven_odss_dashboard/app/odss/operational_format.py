"""Landscape card composition from the supplied September briefing reference.

This module projects the existing governed briefing view. It does not analyse
weather, infer aircraft limitations, or import facts from a reference flight.
Cards use a fixed readable type size and fail closed on capacity overflow.
Airport figures use only the supplied validated surface geometry.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
import re
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfbase.pdfmetrics import stringWidth

from .analysed_briefing_content import cyclone_content, release_condition_groups
from .analysed_briefing_map import build_publication_map, draw_publication_map
from .constants import format_actm

SIZE = landscape(A4)
MARGIN = 28.0
GAP = 18.0
TOP = 493.0
BOTTOM = 48.0
BODY = 10.5
LEADING = 12.8
BG = colors.HexColor("#061321")
PANEL = colors.HexColor("#102237")
BORDER = colors.HexColor("#315269")
WHITE = colors.HexColor("#F2F5FA")
MUTED = colors.HexColor("#B1C0CD")
CYAN = colors.HexColor("#50D5EF")
GREEN = colors.HexColor("#42D6A3")
AMBER = colors.HexColor("#FFBC38")
RED = colors.HexColor("#FF5267")


def text(value: Any, missing: str = "Not held") -> str:
    return str(value).strip() if value is not None and str(value).strip() else missing


def kg(value: Any) -> str:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f"{value:,.0f} kg"
    return "Not held"


def clock(value: Any) -> str:
    value = text(value)
    return value + "Z" if len(value) == 4 and value.isdigit() else value


def utc_label(value: Any) -> str:
    from datetime import datetime
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return stamp.strftime("%d%b %H%MZ").upper() if stamp.tzinfo else "not held"
    except (ValueError, TypeError):
        return "not held"


def unique(values: list[Any]) -> list[str]:
    return list(dict.fromkeys(str(v).strip() for v in values if v is not None and str(v).strip()))


def analysed_vaa_lines(view: dict[str, Any]) -> list[str]:
    """Publish computed route/time consequences, excluding raw volcano notices."""
    lines = []
    for row in (view.get("vaa") or {}).get("cfp_advisories") or []:
        if row.get("advisory_kind") == "CFP_VAA_NOTICE":
            continue
        derived = text(row.get("derived"), "Applicability not established")
        derived = re.sub(r"\. Flight-analysis screening of the OFP advisory polygon.*$", ".", derived)
        derived = derived.replace("Closest approach ", "Closest ").replace("the SIGMET's validity", "validity")
        lines.append(f"{text(row.get('volcano') or row.get('name'))}: {derived}")
    return lines


def wrap(value: str, width: float, *, font: str = "Helvetica", size: float = BODY) -> list[str]:
    """Wrap without ellipsis, including unbroken source tokens."""
    lines: list[str] = []
    for paragraph in str(value).splitlines() or [""]:
        line = ""
        for word in paragraph.split():
            candidate = f"{line} {word}".strip()
            if stringWidth(candidate, font, size) <= width:
                line = candidate
                continue
            if line:
                lines.append(line)
                line = ""
            while stringWidth(word, font, size) > width:
                end = len(word) - 1
                while end > 1 and stringWidth(word[:end], font, size) > width:
                    end -= 1
                lines.append(word[:end])
                word = word[end:]
            line = word
        lines.append(line)
    return lines


@dataclass
class Card:
    title: str
    paragraphs: list[str]
    accent: Any = field(default_factory=lambda: CYAN)
    target: str | None = None
    left_aligned: bool = False
    top_aligned: bool = False
    paragraph_gap: float = 0
    width_weight: float = 1


@dataclass
class CardBox:
    title: str
    lines: list[str]
    accent: Any
    x: float
    y: float
    width: float
    height: float
    target: str | None = None
    left_aligned: bool = False
    top_aligned: bool = False
    paragraph_gap: float = 0
    paragraph_starts: list[int] = field(default_factory=list)


@dataclass
class Page:
    title: str
    bookmark: str
    boxes: list[CardBox] = field(default_factory=list)
    route_map: dict[str, Any] | None = None
    surface_overlay: dict[str, Any] | None = None
    airport_role: str | None = None


def plan_page(title: str, bookmark: str, rows: list[tuple[float, list[Card]]], *, route_map=None, surface_overlay=None, airport_role=None) -> list[Page]:
    """Enforce the reference grid at fixed type size; never spill source text."""
    full_width = SIZE[0] - 2 * MARGIN
    first = Page(title, bookmark, route_map=route_map, surface_overlay=surface_overlay, airport_role=airport_role)
    top = 232.0 if airport_role else TOP if route_map is None else 213.0
    for height, cards in rows:
        usable_width = full_width - GAP * (len(cards) - 1)
        total_weight = sum(card.width_weight for card in cards)
        x = MARGIN
        for card in cards:
            width = usable_width * card.width_weight / total_weight
            title_lines = wrap(card.title, width - 20, font="Helvetica-Bold", size=14) if card.title else []
            head_height = len(title_lines) * 16 + 15 if card.title else 0
            available_height = max(LEADING, height - head_height - 17)
            capacity = int(available_height // LEADING)
            lines, starts = [], []
            for paragraph in card.paragraphs:
                starts.append(len(lines))
                lines.extend(wrap(paragraph, width - 28))
            gap_height = max(0, len(starts) - 1) * card.paragraph_gap
            if len(lines) * LEADING + gap_height > available_height + .01:
                raise ValueError(f"Concise PDF capacity exceeded in {title} / {card.title}: {len(lines)} lines, {capacity} available. No source continuation is permitted.")
            else:
                shown = lines
            first.boxes.append(CardBox(card.title, shown, card.accent, x, top - height, width, height, card.target, card.left_aligned, card.top_aligned, card.paragraph_gap, starts))
            x += width + GAP
        top -= height + GAP
    if top + GAP < BOTTOM - 0.1:
        raise ValueError(f"Reference grid exceeds page: {title}")
    return [first]


def draw_chrome(canvas, flight: dict[str, Any], view: dict[str, Any], title: str, number: int, count: int) -> None:
    width, height = SIZE
    canvas.setFillColor(BG)
    canvas.rect(0, 0, width, height, fill=1, stroke=0)
    # Two distinct lines prevent long section titles colliding with identity.
    identity = view.get("flight_identity") or {}
    canvas.setFillColor(MUTED)
    canvas.setFont("Helvetica", 9)
    canvas.drawRightString(width - MARGIN, height - 20, " · ".join((text(view.get("flight_number")), text(view.get("route_label")), text(view.get("flight_date")), f"OFP {text(identity.get('ofp'), 'unavailable')}")))
    size = 23.0
    while size > 16 and stringWidth(title, "Helvetica-Bold", size) > width - 2 * MARGIN:
        size -= 0.25
    if stringWidth(title, "Helvetica-Bold", size) > width - 2 * MARGIN:
        raise ValueError(f"Section title exceeds readable width: {title}")
    canvas.setFont("Helvetica-Bold", size)
    canvas.setFillColor(WHITE)
    canvas.drawString(MARGIN, height - 47, title)
    canvas.setFillColor(colors.HexColor("#573900"))
    canvas.roundRect(MARGIN, height - 78, width - 2 * MARGIN, 23, 5, fill=1, stroke=0)
    canvas.setFont("Helvetica-Bold", 11)
    canvas.setFillColor(AMBER)
    canvas.drawCentredString(width / 2, height - 70, "BRIEFING FOR CREW REVIEW - CURRENT SOURCE VERIFICATION REQUIRED")
    canvas.setStrokeColor(BORDER)
    canvas.line(MARGIN, 29, width - MARGIN, 29)
    canvas.setFillColor(MUTED)
    canvas.setFont("Helvetica", 9)
    canvas.drawString(MARGIN, 13, "PilotDriven Flight Briefing · UTC · NOT FOR NAVIGATION")
    footer = title.replace("FLIGHT BRIEFING - ", "")
    if stringWidth(f"PAGE {number}/{count} · {footer}", "Helvetica", 9) > width * .52:
        footer = " / ".join(title.split(", ")[:2]) if number == 4 else f"SECTION {number}"
    canvas.drawRightString(width - MARGIN, 13, f"PAGE {number}/{count} · {footer}")
    canvas.linkRect("Return to master summary", "sec_overview", (width - 210, 6, width - MARGIN, 26), relative=0, thickness=0)


def draw_page(canvas, flight, view, page: Page, number: int, count: int) -> None:
    draw_chrome(canvas, flight, view, page.title, number, count)
    canvas.bookmarkPage(page.bookmark, fit="XYZ", left=0, top=SIZE[1], zoom=0)
    canvas.addOutlineEntry(page.title, page.bookmark, level=0)
    if page.route_map is not None:
        draw_publication_map(canvas, page.route_map, MARGIN, 233, SIZE[0] - 2 * MARGIN, TOP - 233)
    if page.airport_role:
        draw_airport_figure(canvas, page.surface_overlay, MARGIN, 250, SIZE[0] - 2 * MARGIN, TOP - 250, planned_runway=flight.get(f"{page.airport_role}_runway"))
    for box in page.boxes:
        canvas.setFillColor(PANEL)
        canvas.setStrokeColor(BORDER)
        canvas.roundRect(box.x, box.y, box.width, box.height, 8, stroke=1, fill=1)
        if box.target:
            canvas.linkRect(f"Open {box.title} detail", box.target, (box.x, box.y, box.x + box.width, box.y + box.height), relative=0, thickness=0)
        title_lines = wrap(box.title, box.width - 20, font="Helvetica-Bold", size=14) if box.title else []
        canvas.setFont("Helvetica-Bold", 14)
        canvas.setFillColor(box.accent)
        baseline = box.y + box.height - 23
        for line in title_lines:
            canvas.drawCentredString(box.x + box.width / 2, baseline, line)
            baseline -= 16
        body_top = baseline - 8 if box.title else box.y + box.height - 16
        body_bottom = box.y + 14
        start = body_top if box.top_aligned else body_top - max(0, (body_top - body_bottom - (len(box.lines) - 1) * LEADING) / 2)
        canvas.setFont("Helvetica", BODY)
        canvas.setFillColor(WHITE)
        for index, line in enumerate(box.lines):
            if index and index in box.paragraph_starts:
                start -= box.paragraph_gap
            if start < box.y + 10:
                raise ValueError(f"Card body exceeds measured capacity: {box.title}")
            if box.left_aligned:
                canvas.drawString(box.x + 14, start, line)
            else:
                canvas.drawCentredString(box.x + box.width / 2, start, line)
            start -= LEADING


def analysed_airport_overlay(overlay, analysis):
    """Bind evaluated runway consequences to existing, supplied geometry only."""
    from copy import deepcopy
    result = deepcopy(overlay) if overlay else None
    if result is None:
        return None
    features = (result.get("featureCollection") or {}).get("features") or []
    for effect in analysis.get("surface_effects") or []:
        runways = set(effect.get("runways") or [])
        feature_ids = [f.get("id") for f in features
                       if (f.get("properties") or {}).get("aeroway") == "runway"
                       and set(str((f.get("properties") or {}).get("ref") or "").split("/")) & runways]
        if feature_ids:
            result.setdefault("mapped", []).append({
                **effect, "notamNumber": effect["notam_id"], "entityType": "runway",
                "entityRef": "/".join(effect["runways"]), "featureIds": feature_ids,
            })
    return result


def draw_airport_figure(canvas, overlay, x, y, width, height, *, planned_runway=None) -> None:
    """Draw supplied geometry only; a scheduled/unknown mark is not a closure."""
    from .surface_overlays import surface_mark_presentation

    overlay = overlay or {}
    bounds = overlay.get("bounds") or {}
    if not all(isinstance(bounds.get(k), (int, float)) for k in ("west", "south", "east", "north")):
        canvas.setFillColor(MUTED)
        canvas.setFont("Helvetica", BODY)
        canvas.drawCentredString(x + width / 2, y + height / 2, "Airport surface geometry is not held in this analysis.")
        return
    marks = {}
    for mark in overlay.get("mapped") or []:
        presentation = surface_mark_presentation(mark)
        # Navaid failures do not become runway or taxiway road closures.
        if presentation in {"closure", "scheduled", "shortening"}:
            for feature_id in mark.get("featureIds") or []:
                # Partial extents must not paint the whole supplied way red.
                state = presentation if mark.get("scope") == "whole_entity" else "scheduled"
                priority = {None: 0, "scheduled": 1, "shortening": 2, "closure": 3}
                if priority[state] > priority[marks.get(feature_id)]:
                    marks[feature_id] = state
    west, south, east, north = (bounds[k] for k in ("west", "south", "east", "north"))
    if east <= west or north <= south:
        raise ValueError("Airport figure bounds are invalid")
    import math
    longitude_factor = max(0.01, math.cos(math.radians((south + north) / 2)))
    dx, dy = (east - west) * longitude_factor, north - south
    scale = min((width - 50) / dx, (height - 45) / dy)
    def point(coordinate):
        return (x + (width - dx * scale) / 2 + (coordinate[0] - west) * longitude_factor * scale,
                y + 28 + (height - 45 - dy * scale) / 2 + (coordinate[1] - south) * scale)
    labels = {}
    for feature in (overlay.get("featureCollection") or {}).get("features") or []:
        prop = feature.get("properties") or {}
        geometry = feature.get("geometry") or {}
        lines = [geometry.get("coordinates") or []] if geometry.get("type") == "LineString" else geometry.get("coordinates") or []
        mark = marks.get(prop.get("featureId") or feature.get("id"))
        planned = bool(planned_runway and str(planned_runway) in str(prop.get("ref") or "").split("/"))
        colour = RED if mark == "closure" else AMBER if mark else CYAN if planned else MUTED
        for line in lines:
            if len(line) < 2:
                continue
            canvas.setStrokeColor(colour)
            canvas.setLineWidth(3.2 if mark else 2.4 if prop.get("aeroway") == "runway" else 0.7)
            path = canvas.beginPath()
            path.moveTo(*point(line[0]))
            for coordinate in line[1:]:
                path.lineTo(*point(coordinate))
            canvas.drawPath(path, stroke=1, fill=0)
            if prop.get("ref") and (prop.get("aeroway") == "runway" or mark):
                # OSM can split one runway into several ways. Label its
                # longest held segment once, with measured collision checks.
                length = sum(math.dist(point(a), point(b)) for a, b in zip(line, line[1:]))
                ref = str(prop["ref"])
                if length > labels.get(ref, (0,))[0]:
                    first, last = point(line[0]), point(line[-1])
                    labels[ref] = (length, ((first[0] + last[0]) / 2, (first[1] + last[1]) / 2), colour)
    occupied = []
    for ref, (_, (lx, ly), colour) in sorted(labels.items()):
        label_width = stringWidth(ref, "Helvetica-Bold", 9)
        for ox, oy in ((0, 9), (0, 23), (35, 9), (-35, 9), (0, -17), (55, 23), (-55, 23)):
            px, py = lx + ox, ly + oy
            box = (px - label_width / 2 - 2, py - 3, px + label_width / 2 + 2, py + 10)
            if box[0] < x or box[2] > x + width or box[1] < y + 25 or box[3] > y + height:
                continue
            if any(box[0] < b[2] and box[2] > b[0] and box[1] < b[3] and box[3] > b[1] for b in occupied):
                continue
            # A padded opaque plate prevents runway/taxiway strokes crossing
            # the glyphs. Labels retain leaders to their measured positions.
            canvas.setStrokeColor(colour)
            canvas.setLineWidth(.5)
            canvas.line(lx, ly, px, py + 3)
            canvas.setFillColor(BG)
            canvas.roundRect(box[0], box[1], box[2]-box[0], box[3]-box[1], 2, fill=1, stroke=0)
            canvas.setFillColor(colour)
            canvas.setFont("Helvetica-Bold", 9)
            canvas.drawCentredString(px, py, ref)
            occupied.append(box)
            break
        else:
            raise ValueError(f"Airport figure has no readable label position for {ref}")
    canvas.setFont("Helvetica", 9)
    canvas.setFillColor(MUTED)
    canvas.drawString(x, y + 4, "OSM reference · cyan: planned runway · red: unavailable to this flight · amber: scheduled/partial/shortened")


def build_sections(flight, view, findings, references=None) -> dict[str, list[Page]]:
    """Nine analysed pages; warnings have one closing owner, raw stays in app."""
    from .airport_pdf_analysis import airport_pdf_analysis
    from .combined_brief import _operational_coverage_receipt

    identity = view.get("flight_identity") or {}
    one = view.get("page_one") or {}
    fuel = view.get("fuel_summary") or {}
    fuel_rows = fuel.get("rows") or {}
    masses = fuel.get("masses_kg") or {}
    perf = view.get("performance_publication") or {}
    inputs = perf.get("inputs") or {}
    terrain = view.get("terrain") or {}
    vws = terrain.get("vws_review") or {}
    hazards = view.get("hazards") or {}
    receipt = _operational_coverage_receipt(flight, view, findings, references)
    airport_analysis = airport_pdf_analysis(flight, view.get("airport_operational_panels") or [])
    amount = lambda key: kg((fuel_rows.get(key) or {}).get("fuel_kg"))
    sections = {}
    vws_summary = f"{int(vws.get('event_count') or 0)} event(s) at the analysed {text(vws.get('threshold'))} threshold. Maximum {text(vws.get('maximum_display'))} at {text(vws.get('maximum_waypoint'))}, ACTM {text(vws.get('maximum_actm_display'))}."
    terrain_summary = f"{len(terrain.get('events') or [])} high-MSA event(s); controlled-profile status is in the closing review record."
    mass_lines = [f"PZFW {kg(masses.get('pzfw'))} · PTOW {kg(masses.get('ptow'))}", f"PLWT {kg(masses.get('plwt'))}", f"Selected RTOW {kg(perf.get('selected_rtow_kg'))} · margin {kg(perf.get('margin_kg'))}"]
    fuel_summary_lines = [f"FLT PLAN REQMT {amount('flt_plan_reqmt')} · EXCESS {amount('excess_fuel')}", f"BURNOFF {amount('burnoff')} · STAT CONT {amount('stat_cont')}", f"ALTN FUEL {amount('altn_fuel')} · ALTN HOLD {amount('altn_hold')}", f"TAXI FUEL {kg(fuel.get('taxi_fuel_kg'))}"]
    sections["summary"] = plan_page("FLIGHT BRIEFING - MASTER SUMMARY", "sec_overview", [
        (126, [Card("FLIGHT", [f"{text(view.get('flight_number'))} · {text(identity.get('registration'))} · {text(identity.get('aircraft_type'))}", f"{text(flight.get('departure'))}/{text(flight.get('departure_runway'))} to {text(flight.get('destination'))}/{text(flight.get('destination_runway'))}", text(identity.get("rules")), f"CRUISE CI {text(identity.get('cost_index'))}"]), Card("TIME", [f"SCHED DEP {clock(identity.get('etd_hhmm'))} · SCHED ARR {clock(identity.get('scheduled_eta_hhmm'))}", f"Block {text(identity.get('block'))} · Flight Time {text((view.get('metrics') or {}).get('eet'))}", (f"ATOT {clock(identity.get('actual_takeoff_hhmm'))} · TARGET ARRIVAL {clock(identity.get('eta_hhmm'))}" if identity.get("actual_takeoff_hhmm") else "ATOT not entered · TARGET ARRIVAL NOT CALCULATED"), "Clocks: ATOT + OFP ACTM"]), Card("ROUTE / LEVELS", [f"SID {text(one.get('sid'))} · STAR {text(one.get('star'))}", f"Route distance: {text(one.get('ground_distance_nm'))} NM", f"Levels: {text((view.get('metrics') or {}).get('cruise'))}. Filed track on page 2."])]),
        (126, [Card("FUEL IN TANKS - " + amount("fuel_in_tanks"), fuel_summary_lines, GREEN, "sec_performance"), Card("MASS / PERFORMANCE", mass_lines, GREEN, "sec_performance")]),
        (157, [Card("VWS / TERRAIN", [vws_summary, terrain_summary], AMBER, "sec_terrain"), Card("ARRIVAL SURFACE", [f"Planned {text(flight.get('destination'))} RWY {text(flight.get('destination_runway'))}", f"{len(airport_analysis[1]['lines'])} analysed surface/approach consequence(s).", "Open the arrival page for flight-time effects and inline notice IDs."], RED, "sec_destination"), Card("RELEASE CONDITIONS", ["Review record and source checks on page 9.", "Current weather, airport surface state and operative aircraft limitations must be confirmed before use."], AMBER, "sec_coverage")]),
    ])
    states = {r["key"]: r["state"] for r in receipt["rows"]}
    edto = view.get("edto") or {}
    route_clocks = [f"S{r.get('number')}: {text(r.get('entry_name'))} {text(r.get('entry'))} / {text(r.get('exit_name'))} {text(r.get('exit'))}; ETP ACTM {', '.join(r.get('etps') or []) or 'not held'}." for r in edto.get("sectors") or []]
    for r in flight.get("flight_planning_etps") or []:
        route_clocks.append(f"{text(r.get('label'))} {text(r.get('from'))}/{text(r.get('to'))}: {text(r.get('distance_nm'))} NM; EET {text(r.get('eet_token'))}.")
    edto_windows = [f"{text(r.get('airport'))}/{text(r.get('runway'))}: {text(r.get('approach'))} {text(r.get('minima'))}; {text(r.get('period'))}." for r in edto.get("airports") or []]
    sections["route"] = plan_page("ROUTE HAZARD OVERLAY", "sec_route", [(165, [Card("ROUTE / EDTO CLOCKS", route_clocks or [text(identity.get("rules")), "No EDTO or additional planning ETP is held."], CYAN), Card("EDTO AIRPORT WINDOWS", edto_windows or ["No EDTO airport window is held."], AMBER)])], route_map=build_publication_map(flight, view))
    terrain_lines = []
    for event in terrain.get("events") or []:
        first, last, maximum, drop = (event.get(k) or {} for k in ("first_high", "last_high", "maximum", "drop"))
        msa = maximum.get("msa_hundreds_ft")
        span = (text(first.get('name')) if first.get('name') == last.get('name')
                else f"{text(first.get('name'))}-{text(last.get('name'))}")
        terrain_lines.append(f"{span}: max {int(msa) * 100:,} ft at {text(maximum.get('name'))}; next threshold drop {text(drop.get('name'))}." if msa is not None else "A terrain event is held without a resolved maximum.")
    vws_events = [f"{text(f.get('title'))}: {text(f.get('summary'))}" for f in findings if f.get("engine") == "vws"]
    sections["terrain"] = plan_page("VWS, CAT AND TERRAIN", "sec_terrain", [
        (153, [Card("OFP VWS EVENT", vws_events or [vws_summary], AMBER), Card("INTERPRETATION", ["OFP samples describe the printed waypoint values; they do not establish continuous conditions between every waypoint.", "OFP VWS is not a CAT measurement. Missing samples do not demonstrate continuous low VWS."])]),
        (166, [Card("EXTERNAL CAT REVIEW", [f"OFP VWS: {text(vws.get('maximum_display'))} maximum.", f"WAFS/SIGWX evidence: {'held' if states['wafs_sigwx'] in {'HELD', 'FOUND'} else 'not established'}.", f"AIREP/PIREP retrieval: {'held' if states['airep_pirep'] in {'HELD', 'FOUND'} else 'not established'}.", "Source-check completion is recorded on page 9."], AMBER), Card("HIGH MSA", terrain_lines or [text(terrain.get("summary"))], RED)]),
        (90, [Card("OPERATIONAL CONSEQUENCE", [terrain_summary, "Use the source-held event positions to distinguish turbulence sampling from terrain exposure; neither establishes a controlled escape procedure."], AMBER)]),
    ])
    terminal = []
    for role in ("departure", "destination"):
        station = view.get(role) or {}
        terminal.append(f"{text(station.get('icao'))} METAR: {text((station.get('weather') or {}).get('metar'))}")
        forecast = ((view.get("overview") or {}).get(role) or {}).get("forecast_at_reference") or {}
        conditions = forecast.get("applicable_conditions")
        if conditions:
            terminal.append(f"{text(station.get('icao'))} forecast {text(forecast.get('utc_window'))}: {conditions}")
        source = forecast.get("forecast_source") or {}
        if source:
            label = source.get('display_title') or ('Uploaded OFP' if source.get('source_type') == 'uploaded_cfp' else 'Source not held')
            terminal.append(f"{label}; issued {utc_label(source.get('issued_at_utc'))}; valid {utc_label(source.get('valid_from_utc'))}-{utc_label(source.get('valid_to_utc'))}.")
        elif conditions:
            terminal.append("Forecast source, issue and validity times are not held.")
    sigmets = []
    for card in hazards.get("sigmet_cards") or []:
        screening = str(card.get("screening") or "")
        if "does not intersect the polygon" not in screening and card.get("disposition") != "REVIEW REQUIRED":
            analysed = screening.replace("The polygon crosses the route about ", "Route intersection ").replace("inside the product's validity", "within validity")
            analysed = re.sub(r"\s*(?:NOT PROMOTED\.|PROMOTED - review required\.)$", "", analysed)
            analysed = re.sub(r"Route intersection .*?, but the product ", "Product ", analysed)
            sigmets.append(f"{text(card.get('name'))}: {analysed or 'Flight applicability is not established.'}")
    tc_lines = cyclone_content(flight)["lines"]
    vaa_lines = analysed_vaa_lines(view)
    sections["weather"] = plan_page("WEATHER, SIGMET, TROPICAL CYCLONE AND VOLCANIC ASH", "sec_hazards", [
        (239, [Card("TERMINAL WEATHER", terminal), Card("SIGMET", sigmets or ["No route-specific SIGMET consequence was established from the held records."], AMBER)]),
        (188, [Card("TROPICAL CYCLONE", tc_lines or ["No governed route-specific cyclone consequence was established from the held sources."], AMBER), Card("VOLCANIC ASH", vaa_lines or ["No route-specific ash consequence was established from the held sources."], GREEN)]),
    ])
    fuel_lines = [f"{label} {amount(key)}" for key, label in (("burnoff", "BURNOFF"), ("stat_cont", "STAT CONT"), ("altn_fuel", "ALTN FUEL"), ("altn_hold", "ALTN HOLD"))]
    for key, label in (("dest_hold_top_up", "DEST HOLD TOP-UP"), ("edto_top_up", "EDTO TOP-UP")):
        if (fuel_rows.get(key) or {}).get("fuel_kg"):
            fuel_lines.append(f"{label} {amount(key)}")
    fuel_lines += [f"TAXI FUEL {kg(fuel.get('taxi_fuel_kg'))}", f"FLT PLAN REQMT {amount('flt_plan_reqmt')}", f"Arithmetic: {text(fuel.get('state'))}"]
    derived = fuel.get("derived_fuel_kg") or {}
    mass_checks = {c.get('name'): c.get('passed') for c in fuel.get('checks') or []}
    mass_equations = [f"PZFW {kg(masses.get('pzfw'))} + tanks {amount('fuel_in_tanks')} - taxi {kg(fuel.get('taxi_fuel_kg'))}", f"PTOW {kg(masses.get('ptow'))}", f"PLWT {kg(masses.get('plwt'))} · burnoff {amount('burnoff')}", "Mass identities: " + ("verified" if all(mass_checks.get(k) is True for k in ('mass_landing_identity', 'mass_takeoff_identity')) else "not reconciled")]
    dest_fuel = [f"Tanks - taxi: {kg(derived.get('takeoff'))}", f"Less burnoff: {kg(derived.get('landing'))} at destination.", f"ALTN FUEL {amount('altn_fuel')} · ALTN HOLD {amount('altn_hold')}"]
    switch = lambda key: "ON" if inputs.get(key) is True else "OFF" if inputs.get(key) is False else "not held"
    rtow = [f"RWY {text(inputs.get('runway'))} · {text(inputs.get('runway_condition'))} · FLAPS {text(inputs.get('flap_setting'))}", f"PACKS {switch('packs_on')} · ANTI-ICE {switch('anti_ice_on')}", f"TEMP {text(inputs.get('temperature_c'))} C · QNH {text(inputs.get('qnh_hpa'))} · WIND {text(inputs.get('wind'))}", *[f"{r.get('label')} {kg(r.get('limit_kg'))}" for r in perf.get("candidate_limits") or []], f"Selected RTOW {kg(perf.get('selected_rtow_kg'))}"]
    sensitivity = perf.get("planning_sensitivity") or {}
    margins = [f"RTOW - PTOW: {kg(perf.get('margin_kg'))} · MLGW {kg(inputs.get('maximum_landing_weight_kg'))}", f"MAX FUEL AVAILABLE {kg(inputs.get('maximum_fuel_available_kg'))}", f"ZFW +1,000 kg: ADD {kg(sensitivity.get('zfw_change_burn_add_kg_per_1000'))}", f"ZFW -1,000 kg: LESS {kg(sensitivity.get('zfw_change_burn_less_kg_per_1000'))}"]
    for row in fuel.get("excess_breakdown") or []:
        if row.get("fuel_kg") or str(row.get("label")).upper() == "MEL":
            margins.append(f"{text(row.get('label'))}: {kg(row.get('fuel_kg'))}")
    lower = sensitivity.get("lower_cruise_sensitivity") or {}
    if lower:
        margins.append(f"Cruise -{text(lower.get('offset_ft'))} ft: ADD {kg(lower.get('burn_add_kg'))}; TIME {text(lower.get('time_display'))}.")
    if fuel.get("tanker_return_sector_req_kg") is not None:
        dest_fuel.append(f"Return-sector requirement: {kg(fuel['tanker_return_sector_req_kg'])}.")
    sections["performance"] = plan_page("FUEL, MASS AND PERFORMANCE", "sec_performance", [
        (170, [Card("FUEL RECONCILIATION", fuel_lines, GREEN), Card("MASS RECONCILIATION", mass_equations, GREEN), Card("DESTINATION FUEL", dest_fuel)]),
        (160, [Card("RTOW", rtow), Card("MARGINS / SENSITIVITY", margins)]),
        (79, [Card("CONTROL", [f"EOSID: {text(inputs.get('eosid'))}", "Destination fuel arithmetic is not discretionary holding fuel. Protect alternate fuel and reserves under controlled policy."], AMBER)]),
    ])
    for analysed in airport_analysis:
        role = analysed["role"]
        runway_lines = [r["text"] for r in analysed["lines"] if r["family"] in {"runway", "approach"}]
        taxi_lines = [r["text"] for r in analysed["lines"] if r["family"] == "taxiway"]
        overlay = next((o for o in view.get("surface_overlays") or [] if o.get("icao") == analysed["icao"] and o.get("role") == role), None)
        overlay = analysed_airport_overlay(overlay, analysed)
        sections[role] = plan_page(f"{text(analysed['icao'])} {role.upper()} SURFACE", f"sec_{role}", [(184, [Card(f"PLANNED RWY {text(analysed['planned_runway'])} - FLIGHT-SPECIFIC CONSEQUENCES", runway_lines + taxi_lines or ["No supported closure consequence was established for the planned movement. No gate, exit or taxi route is inferred."], AMBER)])], surface_overlay=overlay, airport_role=role)
    alternates = view.get("alternate_assessment_rows") or []
    from .airport_pdf_analysis import alternate_pdf_analysis
    alternate_analysis = alternate_pdf_analysis(flight, view.get("airport_operational_panels") or [])
    alternate_lines = []
    for a in alternates:
        analysis = next((p for p in alternate_analysis if p["icao"] == a.get("airport")), {"lines": [], "unresolved_ids": []})
        alternate_lines.append(f"{text(a.get('airport'))}/{text(a.get('runway'))} {str(a.get('role') or 'alternate').upper()} · {text(a.get('approach'))} · MIN {text(a.get('minima'))} · {text(a.get('distance_nm'))} NM / {text(a.get('time_minutes'))} min / {kg(a.get('fuel_kg'))}.")
        alternate_lines.extend(r["text"] for r in analysis["lines"])
    deferred = [row["text"] for row in view["deferred_pdf_analysis"]]
    sections["alternates"] = plan_page("ALTERNATES AND AIRCRAFT TECHNICAL STATUS", "sec_alternates", [
        (223, [Card("ALTERNATE PLANS / FLIGHT-WINDOW CONSEQUENCES", alternate_lines or ["No alternate rows are held."])]),
        (204, [Card("CDDL / MEL ITEMS", deferred or ["No supported deferred declaration was parsed from OFP page 1."], AMBER, left_aligned=True)]),
    ])
    checks = {row["key"]: row for row in receipt["rows"]}
    completed = [f"{label}: {success if checks[key]['state'] == 'HELD' else 'incomplete'}."
                 for key, label, success in (("ofp_parse", "Flight / aircraft identity", "recorded"),
                                             ("flight_timing", "Scheduled departure / arrival UTC", "recorded"),
                                             ("fuel_performance", "Fuel arithmetic / performance", "verified"))]
    edto_result = {"NOT APPLICABLE": "not applicable", "HELD": "assessment recorded"}.get(checks["edto"]["state"], "assessment incomplete")
    completed.append(f"EDTO: {edto_result}.")
    from .governed_deferred_extract import governed_deferred_extracts
    extracts = governed_deferred_extracts(view.get("deferred_source_items"), references)
    conditions = release_condition_groups(flight, view, receipt, airport_analysis, alternate_analysis, extracts)
    source_lines = [f"OFP {text(identity.get('ofp'))} · {text(view.get('flight_number'))} · {text(view.get('flight_date'))}", f"Generated {text(view.get('generated_at_display'))}.", "Source checks and full NOTAMs: app / Show full NOTAM."]
    notes = [str(n.get("note_text")) for n in flight.get("personal_notes") or [] if (n.get("include_level1") or n.get("include_level2")) and n.get("note_text")]
    if notes:
        conditions["technical"].append("PILOT NOTES: " + " / ".join(notes))
    def review_card(title, paragraphs, accent=AMBER):
        return Card(title, paragraphs, accent, left_aligned=True, top_aligned=True, paragraph_gap=3)
    has_conditions = any(conditions.values())
    publication_state = "PUBLICATION STATE: Conditional briefing; the unresolved assessments above prevent an automated release conclusion."
    if not has_conditions:
        publication_state = "1. PUBLICATION STATE: No unresolved automated source condition; crew operational release remains separate."
    review_rows = [
        (119, [review_card("SOURCE / CALCULATION REVIEW", completed, CYAN), review_card("SOURCE CONTROL", source_lines, CYAN)]),
        (264, [review_card("WEATHER COVERAGE", conditions["weather"] or ["No unresolved weather-source condition is recorded."]),
               review_card("AIRPORT ASSESSMENTS", conditions["operations"] or ["No unresolved airport assessment is recorded."]),
               review_card("REMAINING RELEASE INPUTS", conditions["technical"] or ["No unresolved aircraft/route source condition is recorded."])]),
        (26, [review_card("", [publication_state])]),
    ]
    # Keep the reference's three review columns. A long source-bound manual
    # ambiguity or pilot note may need a wider column, never smaller type or
    # lost conditions. Try only a few bounded grids, then fail closed.
    grids = ((1, 1, 1), (1, .8, 1.4), (1.4, .8, 1), (.8, 1.4, 1), (1, .6, 1.6))
    for weights in grids:
        rows = list(review_rows)
        rows[1] = (264, [replace(card, width_weight=weight) for card, weight in zip(review_rows[1][1], weights)])
        try:
            sections["review"] = plan_page("REVIEW RECORD AND RELEASE CONDITIONS", "sec_coverage", rows)
            break
        except ValueError:
            if weights == grids[-1]:
                raise
    return sections


def render_analysed_briefing(flight, findings, warnings, path, *, weather_charts=None, company_briefing_references=None) -> None:
    from pathlib import Path
    from reportlab.pdfgen import canvas as pdf_canvas
    from .briefing import build_briefing_view
    from .airport_pdf_analysis import airport_pdf_analysis, alternate_pdf_analysis
    from .concise_pdf_gate import check_concise_pdf, PUBLICATION_FORMAT
    from .profile_chart_gate import validate_depressurisation_profile_charts, DepressurisationProfileChartPublicationError

    profile_violations = validate_depressurisation_profile_charts(flight, findings, 2)
    if profile_violations:
        raise DepressurisationProfileChartPublicationError(profile_violations)
    view = build_briefing_view(flight, findings, warnings, timing_view=flight.get("timing_view"), weather_charts=weather_charts)
    sections = build_sections(flight, view, findings, company_briefing_references)
    pages = [page for group in sections.values() for page in group]
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    canvas = pdf_canvas.Canvas(str(target), pagesize=SIZE)
    canvas.setTitle(f"Flight Briefing {text(view.get('flight_number'))} {text(view.get('flight_date'))}")
    canvas.setSubject(PUBLICATION_FORMAT)
    for number, page in enumerate(pages, 1):
        if page.airport_role == "departure":
            canvas.bookmarkPage("sec_airports")
        draw_page(canvas, flight, view, page, number, len(pages))
        canvas.showPage()
    canvas.save()
    closing_lines = [" ".join(box.lines) for page in sections["review"] for box in page.boxes]
    result = check_concise_pdf(target, flight=flight, view=view, airport_analysis=airport_pdf_analysis(flight, view.get("airport_operational_panels") or []), alternate_analysis=alternate_pdf_analysis(flight, view.get("airport_operational_panels") or []), closing_lines=closing_lines)
    if not result["valid"]:
        target.unlink(missing_ok=True)
        raise ValueError("Concise briefing publication failed: " + "; ".join(v["message"] for v in result["violations"]))
