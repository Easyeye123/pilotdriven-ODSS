"""Mandatory publication checks for the reference six-page briefing.

David's 9 Sep 2026 review sent four reference briefings and ruled: "This
format from beginning has always been this. Get this right, and then we talk
about tweaking from this." The published download is therefore six pages in
his order, each carrying the navigation ribbon and the footer triplet. These
checks are the answer to "how do you ensure that the standard does not
degenerate": the physical PDF is read back and rejected if the structure,
the ribbon, the footer or any source-bound line has drifted.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import fitz

from .pdf_printable import printable

MAX_BRIEFING_PAGES = 6
PUBLICATION_FORMAT = "analysed-briefing-2026-09-15"
PAGE_TITLES = (
    "OVERVIEW",
    "DECISION ANALYSIS",
    "PERFORMANCE, FUEL AND TECHNICAL STATUS",
    "AIRPORTS / ALTERNATES",
    "WEATHER / ROUTE HAZARDS",
    "ENROUTE / INTAM / ASSURANCE",
)
NAV_RIBBON = (
    "OVERVIEW",
    "ANALYSIS",
    "PERF / FUEL / TECH",
    "AIRPORTS",
    "WEATHER",
    "ENROUTE / INTAM",
)
# Which physical page owns each source-bound projection after the rebuild.
OVERVIEW_PAGE = 0
ANALYSIS_PAGE = 1
PERFORMANCE_PAGE = 2
AIRPORTS_PAGE = 3
WEATHER_PAGE = 4
ASSURANCE_PAGE = 5

# Read complete case-insensitive slash tokens before deciding what is a
# notice identity. A serial-ending left side with a two-digit year, a
# structurally valid producer numeric prefix,
# explicit NOTAM/AIC/SUP context, or a damaged declared ID establishes notice
# context. Other value syntaxes (TAF TX32/1006Z, FL330/350, TAS450/460) alone
# do not. Recognition never authorises an ID: the owning analysed view must.
_SOURCE_NOTICE_CANDIDATE = re.compile(
    r"(?<![A-Z0-9])(?=[A-Z0-9]*[A-Z])(?=[A-Z0-9]*\d)[A-Z0-9]+/\d+[A-Z0-9/]*(?![A-Z0-9/])", re.IGNORECASE)
_DECLARED_NOTICE_ID = re.compile(r"\d*[A-Z]{1,3}\d+/\d{2}", re.IGNORECASE)
_PRODUCER_NOTICE_SERIAL = re.compile(r"\d+[A-Z]{1,3}\d+", re.IGNORECASE)


def _declared_notice_ids(*payloads) -> set[str]:
    """Source/view IDs aid recognition of corruption, never publication permission."""
    found = set()
    def walk(value):
        if isinstance(value, list):
            for item in value:
                walk(item)
        elif isinstance(value, dict):
            for key, item in value.items():
                if key in {"notam_id", "notam_ids"}:
                    for identity in (item if isinstance(item, list) else [item]):
                        if isinstance(identity, str) and _DECLARED_NOTICE_ID.fullmatch(identity.strip()):
                            found.add(identity.strip().upper())
                walk(item)
    for payload in payloads:
        walk(payload)
    return found


def _source_notice_tokens(text: str, declared_ids: set[str]) -> list[str]:
    found = []
    for match in _SOURCE_NOTICE_CANDIDATE.finditer(text):
        token = match.group()
        upper = token.upper()
        serial, suffix = upper.split("/", 1)
        year = re.match(r"\d+", suffix).group()
        explicit = re.search(r"\b(?:NOTAM[NRC]?|AIC|AIP SUP(?:PLEMENT)?)\s*:?\s*$", text[:match.start()], re.IGNORECASE)
        if (serial[-1].isdigit() and len(year) == 2
                or _PRODUCER_NOTICE_SERIAL.fullmatch(serial)
                or explicit or any(identity in upper for identity in declared_ids)):
            found.append(token)
    return found


def normalized(value: Any) -> str:
    """The gate's word folding of the form the page prints: ``printable`` (a character outside the faces' repertoire
    is its [U+XXXX] escape, the renderer's own form), upper-cased, every run of other characters one space. A held
    line is compared in the form the page prints it, so a character the page cannot draw is neither dropped from the
    expected line nor read back as a look-alike."""
    return " ".join(re.sub(r"[^A-Z0-9]+", " ", printable(value).upper()).split())


def check_airport_figure_states(page, overlay, analysis) -> list[dict[str, str]]:
    """Check published runway label colours against evaluated flight effects.

    This reads the physical PDF, independently of the drawing's mark merge.
    Unknown geometry stays unresolved; it cannot justify invented strokes.
    """
    expected = {}
    for feature in (overlay.get("featureCollection") or {}).get("features") or []:
        props = feature.get("properties") or {}
        ref = str(props.get("ref") or "")
        if props.get("aeroway") != "runway" or not ref:
            continue
        ids = {feature.get("id"), props.get("featureId")}
        effects = [e for e in analysis.get("surface_effects") or []
                   if set(ref.split("/")) & set(e.get("runways") or [])]
        if not effects:
            continue
        evaluated_sources = {e.get("notam_id") for e in effects}
        effects += [e for e in overlay.get("mapped") or [] if ids & set(e.get("featureIds") or [])
                    and e.get("notamNumber") not in evaluated_sources]
        active = any(e.get("stateAtReference") == "active_at_reference"
                     and e.get("markClass") == "closure" and e.get("scope") == "whole_entity" for e in effects)
        upcoming = any(e.get("stateAtReference") == "begins_after_reference" for e in effects)
        if active or upcoming:
            expected[ref] = 0xFF5267 if active else 0xFFBC38
    spans = [span for block in page.get_text("dict")["blocks"] for line in block.get("lines", []) for span in line["spans"]]
    violations = []
    for ref, colour in expected.items():
        labels = [s for s in spans if s["text"].strip() == ref]
        if not labels or any(s["color"] != colour for s in labels):
            violations.append({"code": "RUNWAY_FIGURE_STATE", "message": f"{analysis.get('icao')} runway {ref} figure does not match its flight-time consequence."})
        rgb = tuple(((colour >> shift) & 255) / 255 for shift in (16, 8, 0))
        if not any(d.get("color") and abs(d.get("width", 0) - 3.2) < 0.05
                   and all(abs(a-b) < 0.01 for a,b in zip(d["color"], rgb)) for d in page.get_drawings()):
            violations.append({"code": "RUNWAY_FIGURE_STROKE", "message": f"{analysis.get('icao')} runway {ref} has no stroke matching its flight-time state."})
    return violations



def _bound_defect_subject_is_published(page_text, page_index, item, item_index, view) -> bool:
    """Recognise a defect-only continuation in its analysed subject position.

    A malformed description may leave the complete defect in company_remark.
    That is distinct from copying a maintenance instruction block. The gate
    independently binds the original item, typed segment, short defect grammar,
    source position and retained consequence; renderer text alone authorises
    nothing. Every other remark keeps the existing rejection.
    """
    if page_index not in {ANALYSIS_PAGE, PERFORMANCE_PAGE} or not view:
        return False
    description = str(item.get("description") or "").strip()
    raw = str(item.get("company_remark") or "").strip()
    # A source form fragment ending in an unmatched bracket cannot itself be
    # a defect. The continuation must be a single complete defect statement.
    if not (description.startswith("-") and description.count(")") > description.count("(")):
        return False
    if not raw or re.search(r"[\n\r;()]|\.\s", raw) or len(raw.split()) > 24:
        return False
    if re.search(r"\b(?:UPLIFT|APPLY|APPLIED|INSPECT|CHECK|PRIOR|BEFORE|PERMITTED|DISPATCH|SECTION|CHAPTER|MEL|CDL|REFER|WRT|MAINT|PERFORMANCE)\b", raw, re.I):
        return False
    defect = re.fullmatch(
        r"([A-Za-z0-9 /#'-]+)\s(?:MISSING|TORN|LOOSE|INOP|INOPERATIVE|UNSERVICEABLE|NOT WORKING|NOT COLD|NO POWER)[.]?",
        raw, re.I,
    )
    if not defect:
        return False
    # This exception understands a nominal equipment/location phrase only.
    # A free-text prefix ending in INOP can instead be a command conditional
    # on a different system's fault. Unknown grammar remains a rejected source
    # copy, including modals, imperatives and condition clauses; no renderer
    # assertion can widen the closed vocabulary below.
    equipment_words = {"GALLEY", "CABIN", "WASTE", "CONTAINER", "DOOR", "LATCH",
                       "PANEL", "ACCESS", "SEAL", "SEAT", "ARMREST", "FAN",
                       "LIGHT", "WING", "SLAT"}
    position_words = {"AFT", "FWD", "FORWARD", "REAR", "UPPER", "LOWER", "LEFT",
                      "RIGHT", "LH", "RH", "IN", "ON", "AT", "THE", "NO", "NUMBER"}
    subject_words = re.findall(r"[A-Z0-9]+", defect.group(1).upper())
    if (not subject_words or not any(word in equipment_words for word in subject_words)
            or any(word not in equipment_words | position_words and not word.isdigit()
                   for word in subject_words)):
        return False
    remark = normalized(raw)
    folded = normalized(page_text)
    # The proper subject is cased, present once in its section, and followed
    # by the analysed effect. Uppercase or repeated injections still fail.
    if folded.count(remark) != 1 or " ".join(raw.split()) in " ".join(page_text.split()):
        return False
    segments = [segment for gate in view.get("deferred_dispatch_gates") or []
                for segment in gate.get("source_segments") or []
                if segment.get("source_item_index") == item_index
                and normalized(segment.get("description")) == normalized(description)
                and normalized(segment.get("restriction")) == remark
                and normalized(segment.get("source_text")) == normalized(description + " " + raw)]
    rows = [row for row in view.get("deferred_pdf_analysis") or []
            if row.get("source_item_indices") == [item_index]
            and normalized(row.get("subject")) == remark]
    if len(segments) != 1 or len(rows) != 1:
        return False
    consequences = rows[0].get("consequences") or []
    if not consequences or any(not normalized(value) or normalized(value) in remark for value in consequences):
        return False
    effect = normalized(" ".join(consequences))
    if page_index == ANALYSIS_PAGE:
        declaration = normalized(segments[0].get("source_declaration"))
        # R2: the analysed row prints "<subject> <consequence> SOURCE ..." with no
        # "dispatch confirmation" suffix; the binding is the same adjacency.
        return bool(declaration and (remark + " " + effect
                    + " SOURCE UPLOADED OFP DEFERRED DECLARATION " + declaration) in folded)
    label = normalized(str(item.get("item_type") or "") + " " + str(item.get("reference") or ""))
    return bool(label and label + " " + remark + " " + effect in folded)


_INSTRUCTION_VOCABULARY = re.compile(
    r"\b(?:UPLIFT|APPLY|APPLIED|INSPECT|CHECK|PRIOR|BEFORE|PERMITTED|DISPATCH|SECTION|CHAPTER|MEL|CDL|REFER|WRT|MAINT|PERFORMANCE)\b",
    re.I,
)


def _wrapped_defect_statement_is_published(page_text, page_index, item, item_index, view) -> bool:
    """Recognise a wrapped description cell inside its own published statement.

    The OFP wraps a defect's description into the cell beneath it ("LH WING,
    AILERON TRAILING EDGE PANEL" / "573BB AND 573DB SEALS FOUND TORN"), so that
    second cell is part of what is wrong, not an instruction block. It may
    appear on the page only as the immediate continuation of its own
    description, once, re-cased, and only when it carries no instruction
    vocabulary at all. The binding is rebuilt here from the held item and its
    own source segment; the renderer's text authorises nothing.
    """
    if page_index not in {ANALYSIS_PAGE, PERFORMANCE_PAGE} or not view:
        return False
    description = str(item.get("description") or "").strip()
    raw = str(item.get("company_remark") or "").strip()
    # More than one sentence is still a statement ("INFO NOTED. APU REMAIN
    # SERVICEABLE TO START ON GND." - SQ482 14 Aug); what it may never be is an
    # instruction block, a list, or long enough to be the source reprinted.
    if not description or not raw or re.search(r"[\n\r;]", raw) or len(raw.split()) > 24:
        return False
    if _INSTRUCTION_VOCABULARY.search(raw):
        return False
    remark = normalized(raw)
    folded = normalized(page_text)
    # Present once, and never as the source's own block capitals.
    if folded.count(remark) != 1 or " ".join(raw.split()) in " ".join(page_text.split()):
        return False
    segments = [segment for gate in view.get("deferred_dispatch_gates") or []
                for segment in gate.get("source_segments") or []
                if segment.get("source_item_index") == item_index
                and normalized(segment.get("description")) == normalized(description)
                and normalized(segment.get("restriction")) == remark]
    if len(segments) != 1:
        return False
    opening = normalized(re.sub(r"^(?:MAINT(?:ENANCE)?\s+ENTRY\s*[.:]?\s*)+", "", description, flags=re.I))
    if opening and f"{opening} {remark}" in folded:
        return True
    # The label line can carry the manual item's title after a dash ("BB CDL
    # 38-05 - DRAINAGE PIPE"); the body beneath it is then the whole statement,
    # bound to the declaration's own identity instead of to a description.
    declaration = str(item.get("source_declaration") or "")
    if not re.search(r"\s-\s*" + re.escape(description) + r"\s*$", declaration, re.I):
        return False
    if page_index == ANALYSIS_PAGE:
        # R2: bound through the analysed row's own consequence instead of the
        # retired "dispatch confirmation" suffix.
        rows = [row for row in view.get("deferred_pdf_analysis") or []
                if item_index in (row.get("source_item_indices") or [])
                and remark in normalized(row.get("subject"))]
        return any(f"{remark} {normalized(' '.join(row.get('consequences') or []))}" in folded
                   for row in rows if row.get("consequences"))
    label = normalized(str(item.get("item_type") or "") + " " + str(item.get("reference") or ""))
    if label and f"{label} {remark}" in folded:
        return True
    # Declarations that share a consequence are published in one row ("CDL
    # 27-23; CDL 57-21: <statement>; <statement>. Reconcile ..."). The body is
    # then bound through its own analysed row: the row must own this item,
    # carry the body in its subject, and be on the page whole.
    return any(
        item_index in (row.get("source_item_indices") or [])
        and remark in normalized(row.get("subject"))
        and normalized(row.get("text")) in folded
        for row in view.get("deferred_pdf_analysis") or []
    )


def lines_after_stated_deferral(lines, folded_page: str, unit: str | None):
    """The lines a page must print once its own stated whole-unit deferral is honoured.

    F5 of the release-420 independent QA (24 Sep 2026): page 5 now defers
    whole trailing rows of a card to the dashboard when it cannot hold them,
    and prints "+N further <unit> on the dashboard." in their place. The gate
    accepts that statement only when exactly the last N rows are the ones
    missing - a deferral that hides a row it did not declare, or declares
    more than it defers, is still a violation.
    """
    if not unit:
        return list(lines)
    stated = re.search(r"(?:\+\s*)?(\d+) FURTHER " + re.escape(normalized(unit)) + r" ON THE DASHBOARD", folded_page)
    if not stated:
        return list(lines)
    count = int(stated.group(1))
    if count <= 0 or count >= len(lines):
        return list(lines)
    kept, deferred = lines[:-count], lines[-count:]
    if any(normalized(line) in folded_page for line in deferred):
        return list(lines)  # a "deferred" row that is printed anyway is not what the statement says
    return kept


def check_concise_pdf(path: Path, *, flight=None, view=None, airport_analysis=None, alternate_analysis=None, closing_lines=None) -> dict[str, Any]:
    declared_notice_ids = _declared_notice_ids(flight, view, airport_analysis, alternate_analysis)
    violations = []
    with fitz.open(path) as pdf:
        if pdf.embfile_count():
            violations.append({"code": "SOURCE_ATTACHMENT", "message": "The concise PDF must not embed source records or attachments."})
        pages = [page.get_text() for page in pdf]
        folded_pages = [normalized(page) for page in pages]
        body = " ".join(folded_pages)
        from .analysed_briefing_content import cyclone_content, deferred_consequences, level_profile_label
        profile = level_profile_label(flight or {})
        if profile != "Level profile not held" and (not pages or normalized(profile) not in folded_pages[OVERVIEW_PAGE]):
            violations.append({"code": "LEVEL_PROFILE_PARITY", "message": "The source-held level profile is missing from the overview route map."})
        if flight and flight.get("planned_level_profile") and "SEE OFP" in body:
            violations.append({"code": "LEVEL_PROFILE_PLACEHOLDER", "message": "A held level profile was replaced by See OFP."})
        if flight is not None and len(pages) > WEATHER_PAGE:
            for line in cyclone_content(flight)["lines"]:
                if normalized(line) not in folded_pages[WEATHER_PAGE]:
                    violations.append({"code": "CYCLONE_TIME_DISTANCE_PARITY", "message": "The weather page omits the flight-matched cyclone distance or its flight-window coverage condition."})
        if view is not None and len(pages) > ASSURANCE_PAGE:
            from .weather_publication import edto_window_lines, sigmet_lines, volcanic_ash_lines
            # VOLCANIC-CHECK-436: the card prints its live sources by name, as counts, or (beside held OFP records, at
            # the page's capacity step) leaves them to page 6; one of the three complete forms must be on the page.
            ash_forms = [volcanic_ash_lines(flight or {}, view, live) for live in ("whole", "compact", "omit")]
            ash_lines = next((form for form in ash_forms
                              if all(normalized(line) in folded_pages[WEATHER_PAGE] for line in form)), ash_forms[0])
            for index, code, lines, unit in (
                (WEATHER_PAGE, 'EDTO_WINDOW_PARITY', edto_window_lines(flight or {}, view), "EDTO airport window(s)"),
                (WEATHER_PAGE, 'SIGMET_SCREENING_PARITY', sigmet_lines(flight or {}, view), "SIGMET row(s)"),
                (WEATHER_PAGE, 'ASH_ASSESSMENT_PARITY', ash_lines, None),
            ):
                for line in lines_after_stated_deferral(lines, folded_pages[index], unit):
                    if normalized(line) not in folded_pages[index]:
                        violations.append({'code': code, 'message': f'Page {index + 1} omits a source-bound assessment: {line}'})
            # F8 (10 Oct 2026): the WEATHER page holds each departure / destination TAF whole, or - only when
            # the page cannot hold it - its largest whole-group prefix with the stated count of trailing groups
            # left to the dashboard. A cut inside a group, or a deferral that is not stated, matches neither.
            from .page_one_weather import page_one_taf_change_groups, weather_page_taf_field
            for role in ("departure", "destination"):
                station = view.get(role) or {}
                record = (station.get("weather") or {}).get("taf")
                if not page_one_taf_change_groups(record)[0] and not page_one_taf_change_groups(record)[1]:
                    continue
                forms = [weather_page_taf_field(record, drop) for drop in range(len(page_one_taf_change_groups(record)[1]) + 1)]
                if not any(normalized(f"{station.get('icao')} TAF: {form}") in folded_pages[WEATHER_PAGE] for form in forms):
                    violations.append({"code": "TERMINAL_TAF_PARITY", "message": f"The weather page holds {station.get('icao')}'s TAF neither whole nor as a whole-group prefix with its stated dashboard deferral."})
            from .analysed_briefing_map import build_publication_map, event_description, key_disposition
            for event in build_publication_map(flight or {}, view)["publication_events"]:
                if normalized(event_description(event)) not in folded_pages[WEATHER_PAGE]:
                    violations.append({"code": "ROUTE_HAZARD_KEY_PARITY", "message": f"The weather / route hazards page omits held hazard {event['id']}."})
                # The key's words and the SIGMET card's verdict are two
                # statements of one screening on one page; they must agree.
                if event.get("disposition") and key_disposition(event) != event["disposition"]:
                    violations.append({"code": "ROUTE_HAZARD_KEY_DISPOSITION_PARITY", "message": f"The route hazard key states {key_disposition(event)} for {event['id']} but its SIGMET card holds {event['disposition']}."})
            for line in deferred_consequences(view):
                if normalized(line) not in folded_pages[PERFORMANCE_PAGE]:
                    violations.append({"code": "DEFERRED_CONSEQUENCE_PARITY", "message": "The technical status card omits a source-bound consequence."})
        for index, page in enumerate(pages):
            folded = folded_pages[index]
            if "�" in page or "■" in page:
                violations.append({"code": "UNSUPPORTED_GLYPH", "message": f"Page {index + 1} contains a replacement glyph."})
            # reportlab draws a character its faces cannot print with ZapfDingbats' notdef, which extraction reads
            # back as a letter ("I"), so the text above cannot see it; the face can. The renderer prints only the
            # printable form, so a page in this face drew something outside it.
            if any(font[3] == "ZapfDingbats" for font in pdf[index].get_fonts()):
                violations.append({"code": "UNSUPPORTED_GLYPH", "message": f"Page {index + 1} draws a character its faces cannot print (notdef glyph)."})
            if index < MAX_BRIEFING_PAGES:
                for item in NAV_RIBBON:
                    if normalized(item) not in folded:
                        violations.append({"code": "MISSING_NAV_RIBBON", "message": f"Page {index + 1} does not carry the {item} ribbon entry."})
                if normalized(f"FLIGHT BRIEFING PAGE {index + 1} OF {MAX_BRIEFING_PAGES}") not in folded:
                    violations.append({"code": "WRONG_SECTION_FOOTER", "message": f"Page {index + 1} is not labelled as page {index + 1} of {MAX_BRIEFING_PAGES}."})
                if normalized(f"Page {index + 1} of {MAX_BRIEFING_PAGES}") not in folded:
                    violations.append({"code": "MISSING_PAGE_FOOTER", "message": f"Page {index + 1} has no footer page number."})
        if len(pages) == MAX_BRIEFING_PAGES and not re.search(r"\b1\.\s", pages[ASSURANCE_PAGE]):
            violations.append({"code": "RELEASE_ACTION_LIST", "message": "Closing release actions must be numbered."})
        if len(pages) == MAX_BRIEFING_PAGES:
            review = pdf[ASSURANCE_PAGE]
            for title in ("SOURCE / CALCULATION REVIEW", "SOURCE CONTROL", "WEATHER COVERAGE", "AIRPORT ASSESSMENTS", "REMAINING RELEASE INPUTS", "PUBLICATION STATE"):
                if normalized(title) not in folded_pages[ASSURANCE_PAGE]:
                    violations.append({"code": "REVIEW_RECORD_STRUCTURE", "message": f"Closing page omits its compact {title} section."})
            for line in closing_lines or []:
                if normalized(line) not in folded_pages[ASSURANCE_PAGE]:
                    violations.append({"code": "REVIEW_CONDITION_PARITY", "message": "A source-bound closing condition is missing from the PDF."})
            if re.search(r"\b[A-Z]{4}\s*\(\d+\)", pages[ASSURANCE_PAGE]):
                violations.append({"code": "UNEXPLAINED_AIRPORT_COUNT", "message": "Closing conditions must name the missing assessment, not airport record counts."})
            titles = review.search_for("WEATHER COVERAGE")
            if titles:
                title = titles[0]
                # The numbered conditions must sit under their own heading, in
                # their own column. A number elsewhere on the page is not this
                # card's first condition.
                below = [hit for hit in review.search_for("1.")
                         if hit.y0 > title.y1 and hit.x0 < title.x1 and hit.x1 > title.x0 - 12]
                nearest = min((hit.y0 - title.y1 for hit in below), default=None)
                if nearest is None or nearest > 35:
                    violations.append({"code": "REVIEW_BODY_ALIGNMENT", "message": "Closing conditions are detached from their section heading."})
        # Source instruction blocks belong in the app. A defect-only source
        # continuation may name its own analysed subject after independent
        # binding checks below. The ranked decision page prints deferred
        # items too, so a check bound to the technical page alone cannot see
        # the block-capital copy David objected to.
        for item_index, item in enumerate((flight or {}).get("deferred_items") or []):
            remark = normalized(item.get("company_remark"))
            if len(remark.split()) < 8:
                continue
            for index, folded in enumerate(folded_pages):
                if (remark in folded
                        and not _bound_defect_subject_is_published(pages[index], index, item, item_index, view)
                        and not _wrapped_defect_statement_is_published(pages[index], index, item, item_index, view)):
                    violations.append({"code": "COPIED_DEFERRED_REMARK", "message": f"Page {index + 1} repeats a deferred source remark instead of its consequence."})
        if len(pages) != MAX_BRIEFING_PAGES:
            violations.append({"code": "CONCISE_PAGE_CEILING", "message": f"Expected six analysed pages; found {len(pages)}. No source appendix is permitted."})
        for index, title in enumerate(PAGE_TITLES):
            if index >= len(pages) or normalized(title) not in folded_pages[index]:
                violations.append({"code": "CONCISE_SECTION_ORDER", "message": f"Page {index + 1} must contain {title}."})
        if re.search(r"\bITEM\s+E\b|\bALL SELECTED NOTAM DETAILS\b|\bSELECTED NOTAM EVIDENCE\b|\bSOURCE CONTINUATION\b", body):
            violations.append({"code": "RAW_NOTAM_PUBLICATION", "message": "Raw/source-detail labels appeared in the concise PDF."})
        # Compare complete source records, not short generic words such as
        # 'runway closed'. The normalizer catches whitespace/punctuation-only
        # repackaging. Longer source records are also checked for copied runs.
        raw_hits = []
        for record in (flight or {}).get("notams") or []:
            raw = normalized(record.get("item_e_text") or record.get("text") or "")
            words = raw.split()
            if len(words) >= 3 and raw in body:
                raw_hits.append(str(record.get("notam_id") or record.get("id") or "unnamed"))
            elif len(words) >= 18 and any(" ".join(words[i:i + 18]) in body for i in range(len(words) - 17)):
                raw_hits.append(str(record.get("notam_id") or record.get("id") or "unnamed"))
        if raw_hits:
            violations.append({"code": "RAW_ITEM_E_IN_BODY", "message": "Source Item E copied into PDF: " + ", ".join(sorted(set(raw_hits)))})
        for airport in [*(airport_analysis or []), *(alternate_analysis or [])]:
            index = AIRPORTS_PAGE
            if airport.get("role") in {"departure", "destination"} and index < len(pdf) and view is not None:
                overlay = next((o for o in view.get("surface_overlays") or []
                                if o.get("icao") == airport.get("icao") and o.get("role") == airport.get("role")), {})
                violations.extend(check_airport_figure_states(pdf[index], overlay, airport))
            page_text = folded_pages[index] if index < len(pages) else ""
            for line in airport.get("lines") or []:
                if normalized(line["text"]) not in page_text:
                    violations.append({"code": "ANALYSED_LINE_PARITY", "message": f"{airport.get('icao')} analysed consequence/IDs do not match its PDF page: {line.get('notam_ids')}"})
        if airport_analysis is not None:
            remaining = folded_pages.copy()
            for airport in [*airport_analysis, *(alternate_analysis or [])]:
                # The overview station columns publish the same analysed
                # consequence lines, so a notice named there is explained too.
                for index in (OVERVIEW_PAGE, AIRPORTS_PAGE):
                    if index < len(remaining):
                        for line in airport.get("lines") or []:
                            remaining[index] = remaining[index].replace(normalized(line["text"]), "")
            # A ranked decision finding is analysed text with its own source
            # tag, so the notice it names is explained where it is printed.
            ranked_ids = {
                normalized(found)
                for item in (view or {}).get("decision_findings") or []
                for field in ("title", "summary", "source_reference")
                for found in _source_notice_tokens(str(item.get(field) or ""), declared_notice_ids)
            }
            # ATC-FIR-BOBCAT-416 (24 Sep 2026): the FIR / COMMUNICATION rows on
            # the closing page are analysed consequences of the composed
            # enroute_contact record (each a source-held FIR notice with its
            # identity, page and "applicability not inferred"), so an identity
            # that record names is explained where it is printed; any other
            # identity on that page is still refused.
            # ATC-RADIO-SOURCE-418 (24 Sep 2026): the row also quotes the
            # notice's own instruction sentence verbatim, and an AIP
            # supplement or AIC names itself inside it in its long form
            # ("SX0033/26 AIP SUPPLEMENT ...", "AX0001/23 AIC RESTRICTION");
            # an identity the composed record itself prints is explained by
            # that record, exactly as its notam_ids are.
            enroute_lines = ((view or {}).get("enroute_contact") or {}).get("procedure_lines") or []
            enroute_ids = {
                normalized(identity)
                for line in enroute_lines
                for identity in [*(line.get("notam_ids") or []), *_source_notice_tokens(str(line.get("text") or ""), declared_notice_ids)]
            }
            for index, page in enumerate(pages):
                for notice_id in _source_notice_tokens(page, declared_notice_ids):
                    if index == ANALYSIS_PAGE and normalized(notice_id) in ranked_ids:
                        continue
                    if index == ASSURANCE_PAGE and normalized(notice_id) in enroute_ids:
                        continue
                    if re.search(r"\b" + re.escape(normalized(notice_id)) + r"\b", remaining[index]):
                        violations.append({"code": "NON_INLINE_NOTAM_ID", "message": f"Page {index + 1} contains a NOTAM ID outside an analysed consequence: {notice_id}."})
        for index, page in enumerate(pages[:ASSURANCE_PAGE]):
            # The single mandatory header is allowed; repeated item-level
            # review labels are not. Source gaps belong to the closing page.
            #
            # The badge this rejects is a block-capital label produced by the
            # renderers ("CDDL REVIEW REQUIRED", "DEFERRED ITEM - REVIEW
            # REQUIRED", "UNAVAILABLE - REVIEW REQUIRED"). Analysed engine
            # prose asks for the same thing in sentence case - "...could not
            # be resolved for the applicable departure window; review
            # required." - and is published, source-tagged, on the ranked
            # page. Matching the capitalised badge tells them apart on every
            # page, needs no analysis view, and never switches the check off.
            without_header = " ".join(
                page.replace("BRIEFING FOR CREW REVIEW - CURRENT SOURCE VERIFICATION REQUIRED", "").split())
            if re.search(r"\bREVIEW REQUIRED\b", without_header):
                violations.append({"code": "REPEATED_ITEM_WARNING", "message": f"Page {index + 1} repeats an item-level review warning."})
        for page in pdf:
            for link in page.get_links():
                if link["kind"] == fitz.LINK_GOTO and not 0 <= link.get("page", -1) < len(pdf):
                    violations.append({"code": "BROKEN_CONCISE_LINK", "message": "An internal report link has no page target."})
                elif link["kind"] == fitz.LINK_NAMED:
                    if not str(link.get("page", "")).isdigit() or not 1 <= int(link["page"]) <= len(pdf):
                        violations.append({"code": "BROKEN_CONCISE_LINK", "message": "An internal named link has no resolved page target."})
    return {"valid": not violations, "format": PUBLICATION_FORMAT, "page_count": len(pages), "raw_item_e_checked": flight is not None, "violations": violations}
