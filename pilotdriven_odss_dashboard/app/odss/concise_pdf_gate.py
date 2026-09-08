"""Mandatory publication checks for the analysed nine-page briefing."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import fitz

MAX_BRIEFING_PAGES = 9
PUBLICATION_FORMAT = "analysed-briefing-2026-09-09"
PAGE_TITLES = (
    "FLIGHT BRIEFING - MASTER SUMMARY",
    "ROUTE HAZARD OVERLAY",
    "VWS, CAT AND TERRAIN",
    "WEATHER, SIGMET, TROPICAL CYCLONE AND VOLCANIC ASH",
    "FUEL, MASS AND PERFORMANCE",
    "DEPARTURE SURFACE",
    "DESTINATION SURFACE",
    "ALTERNATES AND AIRCRAFT TECHNICAL STATUS",
    "REVIEW RECORD AND RELEASE CONDITIONS",
)


def normalized(value: Any) -> str:
    return " ".join(re.sub(r"[^A-Z0-9]+", " ", str(value).upper()).split())


def check_concise_pdf(path: Path, *, flight=None, view=None, airport_analysis=None, alternate_analysis=None) -> dict[str, Any]:
    violations = []
    with fitz.open(path) as pdf:
        if pdf.embfile_count():
            violations.append({"code": "SOURCE_ATTACHMENT", "message": "The concise PDF must not embed source records or attachments."})
        pages = [page.get_text() for page in pdf]
        folded_pages = [normalized(page) for page in pages]
        body = " ".join(folded_pages)
        from .analysed_briefing_content import cyclone_content, deferred_consequences, level_profile_label
        profile = level_profile_label(flight or {})
        if profile != "Level profile not held" and (len(pages) < 2 or normalized(profile) not in folded_pages[1]):
            violations.append({"code": "LEVEL_PROFILE_PARITY", "message": "The source-held level profile is missing from the route page."})
        if flight and flight.get("planned_level_profile") and "SEE OFP" in body:
            violations.append({"code": "LEVEL_PROFILE_PLACEHOLDER", "message": "A held level profile was replaced by See OFP."})
        if flight is not None and len(pages) > 3:
            for line in cyclone_content(flight)["lines"]:
                if normalized(line) not in folded_pages[3]:
                    violations.append({"code": "CYCLONE_TIME_DISTANCE_PARITY", "message": "The weather page omits the flight-matched cyclone distance or its flight-window coverage condition."})
        if view is not None and len(pages) > 7:
            from .analysed_briefing_map import build_publication_map
            for event in build_publication_map(flight or {}, view)["publication_events"]:
                if not re.search(r"\b" + re.escape(event["id"]) + r"\b", pages[1]):
                    violations.append({"code": "ROUTE_HAZARD_KEY_PARITY", "message": f"The route page omits held hazard {event['id']}."})
            for line in deferred_consequences(view):
                if normalized(line) not in folded_pages[7]:
                    violations.append({"code": "DEFERRED_CONSEQUENCE_PARITY", "message": "The aircraft status page omits a source-bound consequence."})
        for index, page in enumerate(pages):
            if "\ufffd" in page or "\u25a0" in page:
                violations.append({"code": "UNSUPPORTED_GLYPH", "message": f"Page {index + 1} contains a replacement glyph."})
            if index and "MASTER SUMMARY" in page:
                violations.append({"code": "WRONG_SECTION_FOOTER", "message": f"Page {index + 1} is labelled as the master summary."})
        if len(pages) == MAX_BRIEFING_PAGES and not re.search(r"\b1\.\s", pages[8]):
            violations.append({"code": "RELEASE_ACTION_LIST", "message": "Closing release actions must be numbered."})
        if len(pages) > 7:
            for item in (flight or {}).get("deferred_items") or []:
                remark = normalized(item.get("company_remark"))
                if len(remark.split()) >= 8 and remark in folded_pages[7]:
                    violations.append({"code": "COPIED_DEFERRED_REMARK", "message": "Technical status repeats a source remark instead of its consequence."})
        if len(pages) != MAX_BRIEFING_PAGES:
            violations.append({"code": "CONCISE_PAGE_CEILING", "message": f"Expected nine analysed pages; found {len(pages)}. No source appendix is permitted."})
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
            index = 5 if airport.get("role") == "departure" else 6 if airport.get("role") == "destination" else 7
            page_text = folded_pages[index] if index < len(pages) else ""
            for line in airport.get("lines") or []:
                if normalized(line["text"]) not in page_text:
                    violations.append({"code": "ANALYSED_LINE_PARITY", "message": f"{airport.get('icao')} analysed consequence/IDs do not match its PDF page: {line.get('notam_ids')}"})
        if airport_analysis is not None:
            remaining = folded_pages.copy()
            for airport in [*airport_analysis, *(alternate_analysis or [])]:
                index = 5 if airport.get("role") == "departure" else 6 if airport.get("role") == "destination" else 7
                if index < len(remaining):
                    for line in airport.get("lines") or []:
                        remaining[index] = remaining[index].replace(normalized(line["text"]), "")
            for index, page in enumerate(pages):
                for notice_id in re.findall(r"\b[A-Z]{1,3}\d{2,5}/\d{2}\b", page):
                    if re.search(r"\b" + re.escape(normalized(notice_id)) + r"\b", remaining[index]):
                        violations.append({"code": "NON_INLINE_NOTAM_ID", "message": f"Page {index + 1} contains a NOTAM ID outside an analysed consequence: {notice_id}."})
        for index, page in enumerate(pages[:8]):
            # The single mandatory header is allowed; repeated item-level
            # review labels are not. Source gaps belong to closing page 9.
            without_header = page.replace("BRIEFING FOR CREW REVIEW - CURRENT SOURCE VERIFICATION REQUIRED", "")
            if re.search(r"\bREVIEW REQUIRED\b", without_header, re.I):
                violations.append({"code": "REPEATED_ITEM_WARNING", "message": f"Page {index + 1} repeats an item-level review warning."})
        for page in pdf:
            for link in page.get_links():
                if link["kind"] == fitz.LINK_GOTO and not 0 <= link.get("page", -1) < len(pdf):
                    violations.append({"code": "BROKEN_CONCISE_LINK", "message": "An internal report link has no page target."})
                elif link["kind"] == fitz.LINK_NAMED:
                    if not str(link.get("page", "")).isdigit() or not 1 <= int(link["page"]) <= len(pdf):
                        violations.append({"code": "BROKEN_CONCISE_LINK", "message": "An internal named link has no resolved page target."})
    return {"valid": not violations, "format": PUBLICATION_FORMAT, "page_count": len(pages), "raw_item_e_checked": flight is not None, "violations": violations}
