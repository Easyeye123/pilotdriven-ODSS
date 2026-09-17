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


def normalized(value: Any) -> str:
    return " ".join(re.sub(r"[^A-Z0-9]+", " ", str(value).upper()).split())


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
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 /#,'-]+\s(?:MISSING|TORN|LOOSE|INOP|INOPERATIVE|UNSERVICEABLE|NOT WORKING|NOT COLD|NO POWER)[.]?", raw, re.I):
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
        return bool(declaration and (remark + " DISPATCH CONFIRMATION " + effect
                    + " SOURCE UPLOADED OFP DEFERRED DECLARATION " + declaration) in folded)
    label = normalized(str(item.get("item_type") or "") + " " + str(item.get("reference") or ""))
    return bool(label and label + " " + remark + " " + effect in folded)


def check_concise_pdf(path: Path, *, flight=None, view=None, airport_analysis=None, alternate_analysis=None, closing_lines=None) -> dict[str, Any]:
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
            for index, code, lines in (
                (WEATHER_PAGE, 'EDTO_WINDOW_PARITY', edto_window_lines(flight or {}, view)),
                (WEATHER_PAGE, 'SIGMET_SCREENING_PARITY', sigmet_lines(flight or {}, view)),
                (WEATHER_PAGE, 'ASH_ASSESSMENT_PARITY', volcanic_ash_lines(flight or {}, view)),
            ):
                for line in lines:
                    if normalized(line) not in folded_pages[index]:
                        violations.append({'code': code, 'message': f'Page {index + 1} omits a source-bound assessment: {line}'})
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
                if remark in folded and not _bound_defect_subject_is_published(pages[index], index, item, item_index, view):
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
                for found in re.findall(r"\b[A-Z]{1,3}\d{2,5}/\d{2}\b", str(item.get(field) or ""))
            }
            for index, page in enumerate(pages):
                for notice_id in re.findall(r"\b[A-Z]{1,3}\d{2,5}/\d{2}\b", page):
                    if index == ANALYSIS_PAGE and normalized(notice_id) in ranked_ids:
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
