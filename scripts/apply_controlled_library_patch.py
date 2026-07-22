from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "pilotdriven_odss_dashboard/app/odss/engines.py"
CONTROLLED = ROOT / "pilotdriven_odss_dashboard/app/odss/controlled_library.py"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one literal match, found {count}")
    return text.replace(old, new, 1)


def regex_once(text: str, pattern: str, replacement: str, label: str) -> str:
    updated, count = re.subn(pattern, replacement, text, count=1, flags=re.DOTALL)
    if count != 1:
        raise RuntimeError(f"{label}: expected one regex match, found {count}")
    return updated


engine = ENGINE.read_text(encoding="utf-8")
engine = replace_once(
    engine,
    "    DEPRESS_PROFILES,\n",
    "",
    "remove sample depress import",
)
engine = replace_once(
    engine,
    ")\n\n_WEEKDAYS =",
    ")\n\nfrom .controlled_library import (\n"
    "    CDL_LIBRARY_METADATA,\n"
    "    CDL_REFERENCES,\n"
    "    DEPRESS_LIBRARY_METADATA,\n"
    "    DEPRESS_PROFILES,\n"
    "    aircraft_effectivity_tokens,\n"
    "    select_cdl_variants,\n"
    ")\n\n_WEEKDAYS =",
    "add controlled library imports",
)

profile_effectivity = '''def _profile_applies_to_aircraft(
    profile: dict[str, Any],
    registration: str | None,
    aircraft_type: str | None,
) -> bool:
    effectivity = {
        re.sub(r"[^A-Z0-9]", "", str(value).upper())
        for value in profile.get("effectivity", [])
        if value
    }
    if not effectivity or "ALL" in effectivity:
        return True
    return bool(effectivity & aircraft_effectivity_tokens(registration, aircraft_type))


'''
engine = regex_once(
    engine,
    r"def _profile_applies_to_aircraft\(.*?\n\n\ndef detect_terrain_events",
    profile_effectivity + "def detect_terrain_events",
    "replace aircraft effectivity",
)
engine = replace_once(
    engine,
    "        if msa > 100:\n",
    "        if waypoint.get(\"msa_asterisk\") or msa > 100:\n",
    "use Lido asterisk for high MSA",
)

profile_matching = '''def _route_waypoint_name(waypoint: dict[str, Any]) -> str:
    return str(waypoint.get("name") or "").lstrip("-").upper()


def _profile_aliases(profile: dict[str, Any], field: str) -> set[str]:
    fallback = str(profile.get(field) or "").upper()
    return {
        str(value).lstrip("-").upper()
        for value in profile.get(f"{field}_aliases", [fallback])
        if value
    }


def _route_airways_between(
    waypoints: list[dict[str, Any]],
    start_index: int,
    end_index: int,
) -> list[str]:
    return [
        str(waypoints[index].get("airway_in") or "").upper()
        for index in range(start_index + 1, end_index + 1)
        if waypoints[index].get("airway_in")
    ]


def _profile_route_spans(
    profile: dict[str, Any],
    waypoints: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    names = [_route_waypoint_name(item) for item in waypoints]
    from_aliases = _profile_aliases(profile, "from")
    to_aliases = _profile_aliases(profile, "to")
    published_airways = [str(value).upper() for value in profile.get("airways", [])]
    spans: list[dict[str, Any]] = []
    for from_index, name in enumerate(names):
        if name not in from_aliases:
            continue
        for to_index, to_name in enumerate(names):
            if to_name not in to_aliases or to_index == from_index:
                continue
            if from_index < to_index:
                start_index, end_index = from_index, to_index
                expected_airways = published_airways
                direction = "forward"
            else:
                start_index, end_index = to_index, from_index
                expected_airways = list(reversed(published_airways))
                direction = "reverse"
            route_airways = _route_airways_between(waypoints, start_index, end_index)
            if expected_airways and not _subsequence(route_airways, expected_airways):
                continue
            spans.append(
                {
                    "start_index": start_index,
                    "end_index": end_index,
                    "route_start": names[start_index],
                    "route_end": names[end_index],
                    "airways": expected_airways,
                    "route_airways": route_airways,
                    "direction": direction,
                }
            )
    return spans


def match_profiles(
    flight: dict[str, Any],
    terrain_events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    waypoints = flight["route_waypoints"]
    matches: list[dict[str, Any]] = []
    for event in terrain_events:
        event_start_wp = event.get("preceding") or event["first_high"]
        event_start_index = waypoints.index(event_start_wp)
        event_end_index = waypoints.index(event["last_high"])
        required_edges = set(range(event_start_index, event_end_index))
        if not required_edges:
            required_edges = {event_start_index}

        candidate_by_chart: dict[str, dict[str, Any]] = {}
        for profile in DEPRESS_PROFILES:
            if not _profile_applies_to_aircraft(
                profile,
                flight.get("registration"),
                flight.get("aircraft_type"),
            ):
                continue
            for span in _profile_route_spans(profile, waypoints):
                if event_end_index == event_start_index:
                    covered = (
                        {event_start_index}
                        if span["start_index"] <= event_start_index <= span["end_index"]
                        else set()
                    )
                else:
                    covered = set(
                        range(
                            max(span["start_index"], event_start_index),
                            min(span["end_index"], event_end_index),
                        )
                    )
                if not covered:
                    continue
                candidate = {
                    **span,
                    "event": event,
                    "profile": profile,
                    "covered_edges": covered,
                }
                chart = str(profile.get("chart") or "")
                current = candidate_by_chart.get(chart)
                candidate_score = (len(covered), -(span["end_index"] - span["start_index"]))
                current_score = (
                    (len(current["covered_edges"]), -(current["end_index"] - current["start_index"]))
                    if current
                    else (-1, 0)
                )
                if current is None or candidate_score > current_score:
                    candidate_by_chart[chart] = candidate

        uncovered = set(required_edges)
        available = list(candidate_by_chart.values())
        selected: list[dict[str, Any]] = []
        while uncovered:
            useful = [
                (len(item["covered_edges"] & uncovered), item)
                for item in available
            ]
            useful = [entry for entry in useful if entry[0] > 0]
            if not useful:
                break
            _, best = max(
                useful,
                key=lambda entry: (
                    entry[0],
                    len(entry[1]["covered_edges"]),
                    -(entry[1]["end_index"] - entry[1]["start_index"]),
                    str(entry[1]["profile"].get("chart") or ""),
                ),
            )
            selected.append(best)
            uncovered -= best["covered_edges"]
            available = [item for item in available if item is not best]

        coverage_complete = not uncovered
        selected.sort(key=lambda item: (item["start_index"], item["end_index"]))
        for item in selected:
            matches.append(
                {
                    "event": event,
                    "profile": item["profile"],
                    "names": [
                        _route_waypoint_name(value)
                        for value in waypoints[item["start_index"] : item["end_index"] + 1]
                    ],
                    "airways": item["airways"],
                    "route_start": item["route_start"],
                    "route_end": item["route_end"],
                    "direction": item["direction"],
                    "coverage_complete": coverage_complete,
                    "uncovered_edge_count": len(uncovered),
                    "start_index": item["start_index"],
                    "end_index": item["end_index"],
                }
            )

    deduplicated: dict[tuple[int, str], dict[str, Any]] = {}
    for match in matches:
        key = (match["event"]["first_high"]["actm_minutes"], match["profile"]["chart"])
        deduplicated[key] = match
    return sorted(
        deduplicated.values(),
        key=lambda item: (
            item["event"]["first_high"]["actm_minutes"],
            item["start_index"],
        ),
    )
'''
engine = regex_once(
    engine,
    r"def match_profiles\(.*?\n\n\ndef analyse",
    profile_matching + "\n\n\ndef analyse",
    "replace depressurisation matching",
)

cdl_analysis = '''    for item in flight["deferred_items"]:
        if item["item_type"] == "MEL":
            reference = MEL_REFERENCES.get(item["reference"])
            if reference:
                reference_library_used = True
                details = [
                    f"Repair interval {reference.get('repair_interval')}; "
                    f"installed {reference.get('installed')}; required {reference.get('required')}.",
                    f"Placard {'required' if reference.get('placard_required') else 'not required/none stated'}; "
                    f"operational procedure {'required' if reference.get('operational_procedure_required') else 'not stated'}.",
                    *reference.get("terms", []),
                ]
                if item.get("company_remark"):
                    details.append(f"Company remark: {item['company_remark']}.")
                findings.append(finding(
                    "mel",
                    "warning",
                    f"MEL {item['reference']} - {item['description']}",
                    "Candidate local-library match; verify the current approved MEL before use.",
                    details,
                    {
                        "reference_library_version": REFERENCE_LIBRARY_METADATA["version"],
                        "reference_status": REFERENCE_LIBRARY_METADATA["status"],
                    },
                ))
            else:
                findings.append(finding(
                    "mel",
                    "unknown",
                    f"MEL {item['reference']} not verified",
                    "The approved MEL reference is missing from the local library.",
                    [item["description"]],
                ))
        elif item["item_type"] == "CDL":
            reference_key = str(item.get("reference") or "").upper()
            record = CDL_REFERENCES.get(reference_key)
            if record is None:
                mounted = CDL_LIBRARY_METADATA.get("status") != "controlled-source-not-mounted"
                findings.append(finding(
                    "cdl",
                    "unknown",
                    f"CDL {reference_key} not resolved",
                    (
                        "Reference not found in the mounted controlled CDL index."
                        if mounted
                        else "The private controlled CDL index is not mounted."
                    ),
                    [
                        item.get("description") or "No Page 1 description parsed.",
                        item.get("company_remark") or "No Page 1 company remark parsed.",
                    ],
                    {
                        "controlled_document": CDL_LIBRARY_METADATA.get("title"),
                        "controlled_issue_date": CDL_LIBRARY_METADATA.get("issue_date"),
                        "reference_status": CDL_LIBRARY_METADATA.get("status"),
                    },
                ))
                continue

            variants = select_cdl_variants(record, flight.get("registration"))
            if not variants:
                findings.append(finding(
                    "cdl",
                    "critical",
                    f"CDL {reference_key} effectivity conflict",
                    f"No controlled variant applies to registration {flight.get('registration') or 'not parsed'}.",
                    [record.get("title") or "Title not available."],
                    {
                        "source_pages": record.get("source_pages", []),
                        "controlled_issue_date": CDL_LIBRARY_METADATA.get("issue_date"),
                    },
                ))
                continue

            details = [
                f"Page 1: {item.get('description') or 'description not parsed'}.",
            ]
            if item.get("company_remark"):
                details.append(f"Company remark: {item['company_remark']}.")
            takeoff_penalties: list[int] = []
            enroute_penalties: list[int] = []
            fuel_penalties: list[float] = []
            for number, variant in enumerate(variants, start=1):
                label = variant.get("component") or record.get("title") or reference_key
                quantity = variant.get("quantity_installed")
                details.append(
                    f"Applicable variant {number}: {label}"
                    + (f"; quantity installed {quantity}." if quantity is not None else ".")
                )
                for field, prefix in (
                    ("dispatch_conditions", "Dispatch"),
                    ("limitations", "Limitation"),
                ):
                    if variant.get(field):
                        details.append(f"{prefix}: {variant[field]}")
                details.extend(f"Note: {value}" for value in variant.get("notes", []) if value)
                if variant.get("maintenance_references"):
                    details.append(
                        "Maintenance reference: "
                        + ", ".join(variant["maintenance_references"])
                        + "."
                    )
                if variant.get("mel_references"):
                    details.append(
                        "MEL interface: " + ", ".join(variant["mel_references"]) + "."
                    )
                takeoff_penalties.extend(variant.get("takeoff_approach_penalty_kg_values", []))
                enroute_penalties.extend(variant.get("enroute_penalty_kg_values", []))
                fuel_penalties.extend(variant.get("fuel_penalty_percent_values", []))

            takeoff_penalties = list(dict.fromkeys(takeoff_penalties))
            enroute_penalties = list(dict.fromkeys(enroute_penalties))
            fuel_penalties = list(dict.fromkeys(fuel_penalties))
            if takeoff_penalties:
                details.append(
                    "Published take-off/approach penalty value(s): "
                    + ", ".join(f"{value:,} kg" for value in takeoff_penalties)
                    + "."
                )
            if enroute_penalties:
                details.append(
                    "Published enroute penalty value(s): "
                    + ", ".join(f"{value:,} kg" for value in enroute_penalties)
                    + "."
                )
            if fuel_penalties:
                details.append(
                    "Published fuel increase value(s): "
                    + ", ".join(f"{value:g}%" for value in fuel_penalties)
                    + "."
                )
            details.append(
                f"Controlled source issue {CDL_LIBRARY_METADATA.get('issue_date')}; "
                f"page(s) {', '.join(str(value) for value in record.get('source_pages', [])) or 'not indexed'}."
            )
            findings.append(finding(
                "cdl",
                "warning",
                f"CDL {reference_key} - {record.get('title') or item.get('description') or 'item'}",
                "Controlled registration-specific CDL match.",
                details,
                {
                    "reference": reference_key,
                    "source_pages": record.get("source_pages", []),
                    "controlled_document": CDL_LIBRARY_METADATA.get("title"),
                    "controlled_issue_date": CDL_LIBRARY_METADATA.get("issue_date"),
                    "reference_status": CDL_LIBRARY_METADATA.get("status"),
                    "takeoff_approach_penalty_kg_values": takeoff_penalties,
                    "enroute_penalty_kg_values": enroute_penalties,
                    "fuel_penalty_percent_values": fuel_penalties,
                    "applicable_variant_count": len(variants),
                },
            ))
        else:
            findings.append(finding(
                "cddl",
                "unknown",
                f"{item['item_type']} {item['reference']} not verified",
                "The approved configuration-deviation reference is missing.",
                [item["description"], item.get("company_remark") or "No company remark parsed."],
            ))

    candidates = ['''
engine = regex_once(
    engine,
    r"    for item in flight\[\"deferred_items\"\]:.*?\n    candidates = \[",
    cdl_analysis,
    "replace deferred MEL/CDL/CDDL analysis",
)

profile_reporting = '''    matches = sorted(
        match_profiles(flight, terrain_events),
        key=lambda x: (x["event"]["first_high"]["actm_minutes"], x["start_index"]),
    )
    for index, match in enumerate(matches, start=1):
        event = match["event"]
        profile = match["profile"]
        route_start = match["route_start"]
        route_end = match["route_end"]
        critical = profile["critical"]
        critical_aliases = _profile_aliases(profile, "critical")
        critical_wp = next(
            (
                waypoint
                for waypoint in flight["route_waypoints"]
                if _route_waypoint_name(waypoint) in critical_aliases
            ),
            None,
        )
        maximum = event["maximum"]
        end_wp = event["drop"] or event["last_high"]
        details = [
            f"High-MSA event ACTM {format_actm(event['first_high']['actm_minutes'])}-"
            f"{format_actm(end_wp['actm_minutes'])}.",
            f"Maximum MSA {maximum['msa_hundreds_ft']}* "
            f"({maximum['msa_hundreds_ft'] * 100:,} ft) at {maximum['name']}.",
            f"Published chart route {profile['from']}-{profile['to']}; "
            f"airways {', '.join(profile['airways']) or 'none listed'}.",
            f"Critical point {critical}"
            + (
                f", CFP ACTM {format_actm(critical_wp['actm_minutes'])}."
                if critical_wp
                else "; ACTM not found."
            ),
            f"Controlled profile issue {DEPRESS_LIBRARY_METADATA.get('issue_date')}; "
            f"effective {profile.get('effective_date') or 'not indexed'}.",
        ]
        if profile.get("chart_page"):
            details.append(f"Controlled chart page {profile['chart_page']}.")
        if not match["coverage_complete"]:
            details.append(
                f"Coverage incomplete: {match['uncovered_edge_count']} event route leg(s) remain unmatched."
            )
        findings.append(finding(
            "depressurisation",
            "warning" if match["coverage_complete"] else "unknown",
            f"Profile {index} - {route_start} to {route_end} "
            f"({' / '.join(match['airways']) or 'airway review required'})",
            f"Proposed depressurisation chart {profile['chart']}; critical point {critical}.",
            details,
            {
                "chart_number": profile["chart"],
                "critical_point": critical,
                "start_actm_minutes": event["first_high"]["actm_minutes"],
                "route_start": route_start,
                "route_end": route_end,
                "coverage_complete": match["coverage_complete"],
                "controlled_issue_date": DEPRESS_LIBRARY_METADATA.get("issue_date"),
                "reference_status": DEPRESS_LIBRARY_METADATA.get("status"),
                "chart_page": profile.get("chart_page"),
            },
        ))
    if terrain_events and not matches:
        findings.append(finding(
            "depressurisation",
            "unknown",
            "High terrain detected but no profile matched",
            "Manual chart-index review is required.",
        ))

    edto = flight["edto"]'''
engine = regex_once(
    engine,
    r"    matches = sorted\(.*?\n    edto = flight\[\"edto\"\]",
    profile_reporting,
    "replace depressurisation reporting",
)
engine = replace_once(
    engine,
    '        "Exactly 100* is excluded from high-MSA events; only values >100* qualify.",\n',
    '        "A starred MSA qualifies; without an asterisk only numeric values strictly above 100 qualify.",\n',
    "update MSA QA statement",
)
ENGINE.write_text(engine, encoding="utf-8")

controlled = CONTROLLED.read_text(encoding="utf-8")
controlled = controlled.replace(
    '"effectivity": ["LH", "ULR"],',
    '"effectivity": ["A350-941", "LH", "ULR"],',
)
CONTROLLED.write_text(controlled, encoding="utf-8")
