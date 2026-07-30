#!/usr/bin/env python3
"""Build a private deterministic profile index from an authorised PDF.

The generated JSON contains list-of-effective-pages metadata only. It does not
copy profile chart bodies into the repository. Run this script only against a
document the tenant is authorised to process, and keep its output in private
storage.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any


_ROW = re.compile(r"^\s*(\d+-\d+)\s+")
_DATE = re.compile(r"^\d{2}\s+[A-Z]{3}\s+\d{4}$")
_DASH = re.compile(r"\s+[\-\u2013\u2014]\s+")


def _pdftotext(pdf_path: Path, first_page: int, last_page: int) -> str:
    completed = subprocess.run(
        [
            "pdftotext",
            "-f",
            str(first_page),
            "-l",
            str(last_page),
            "-layout",
            str(pdf_path),
            "-",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout


def _field(line: str, start: int, end: int | None = None) -> str:
    return " ".join(line[start:end].split())


def _continuation_airway(line: str) -> str:
    if _ROW.match(line):
        return ""
    value = _field(line, 34, 60)
    if not value or value in {"Airway(s)", "Effective Date", "(CP)"}:
        return ""
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9/, \-]*", value):
        return ""
    return value


def _continuation_route(line: str) -> str:
    if _ROW.match(line):
        return ""
    value = _field(line, 12, 34)
    if not value or value in {
        "From \u2013 To",
        "From - To",
        "(Waypoints)",
        "Preamble P1 \u2013 P2",
        "Legend L1 \u2013 L3",
    }:
        return ""
    if value.startswith("Page "):
        return ""
    if "OF 15" in value.upper() or value in {"A350", "Depressurization"}:
        return ""
    return value


def _assign_continuations(
    lines: list[str],
    row_positions: list[int],
    main_values: dict[int, str],
    extractor=_continuation_airway,
) -> dict[int, list[tuple[int, str]]]:
    assigned: dict[int, list[tuple[int, str]]] = {
        position: [] for position in row_positions
    }
    for position, line in enumerate(lines):
        value = extractor(line)
        if not value or position in assigned:
            continue
        neighbours = sorted(
            row_positions,
            key=lambda row_position: (abs(row_position - position), row_position),
        )
        if not neighbours:
            continue
        nearest_distance = abs(neighbours[0] - position)
        if nearest_distance > 2:
            continue
        nearest = [
            row_position
            for row_position in neighbours
            if abs(row_position - position) == nearest_distance
        ]
        if len(nearest) == 1:
            target = nearest[0]
        else:
            before, after = min(nearest), max(nearest)
            if not main_values.get(after) and main_values.get(before):
                target = after
            elif not main_values.get(before) and main_values.get(after):
                target = before
            else:
                target = before
        assigned[target].append((position, value))
    return assigned


def parse_effective_pages(text: str, *, first_chart_page: int = 22) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    ordinal = 0
    for page in text.split("\f"):
        lines = page.splitlines()
        row_positions = [
            position for position, line in enumerate(lines) if _ROW.match(line)
        ]
        main_records: dict[int, dict[str, str]] = {}
        for position in row_positions:
            line = lines[position]
            row_match = _ROW.match(line)
            date_match = re.search(r"\b\d{2}\s+[A-Z]{3}\s+\d{4}\b", line)
            if row_match is None or date_match is None:
                raise ValueError(f"Malformed effective-pages row: {line!r}")
            before_date = line[: date_match.start()].rstrip()
            critical = before_date.split()[-1] if before_date.split() else ""
            critical_start = before_date.rfind(critical)
            body = line[row_match.end() : critical_start].strip()
            direct_route = re.match(
                r"^([A-Z0-9]+)\s+[\-\u2013\u2014]\s+([A-Z0-9]+)"
                r"(?:\s+(.*))?$",
                body,
            )
            if direct_route:
                route = f"{direct_route.group(1)} - {direct_route.group(2)}"
                airway = (direct_route.group(3) or "").strip()
            else:
                route = _field(line, 12, 34)
                airway = _field(line, 34, critical_start)
            main_records[position] = {
                "route": route,
                "airway": airway,
                "critical": critical,
                "effective_date": " ".join(date_match.group(0).split()),
                "effectivity": _field(line, date_match.end()),
            }
        main_airways = {
            position: main_records[position]["airway"]
            for position in row_positions
        }
        airway_continuations = _assign_continuations(
            lines,
            row_positions,
            main_airways,
        )
        main_routes = {
            position: main_records[position]["route"]
            for position in row_positions
        }
        route_continuations = _assign_continuations(
            lines,
            row_positions,
            main_routes,
            _continuation_route,
        )
        for position in row_positions:
            ordinal += 1
            line = lines[position]
            match = _ROW.match(line)
            if match is None:  # pragma: no cover - row_positions is the gate
                continue
            chart = match.group(1)
            route_parts = [(position, main_routes[position])]
            if not _DASH.search(main_routes[position]):
                route_parts += route_continuations[position]
            route = " ".join(
                value
                for _, value in sorted(route_parts)
                if value
            )
            effective_date = main_records[position]["effective_date"]
            critical = main_records[position]["critical"]
            effectivity = main_records[position]["effectivity"]
            deleted = route.upper() == "DELETED"
            airway_parts = [
                (position, main_airways[position])
            ] + airway_continuations[position]
            airway_text = ", ".join(
                value.strip(" ,")
                for _, value in sorted(airway_parts)
                if value.strip(" ,")
            )
            if deleted:
                rows.append(
                    {
                        "chart": chart,
                        "deleted": True,
                        "chart_page": first_chart_page + ordinal - 1,
                    }
                )
                continue
            endpoints = _DASH.split(route, maxsplit=1)
            if len(endpoints) != 2:
                raise ValueError(f"Could not parse route for profile {chart}: {route!r}")
            if not _DATE.match(effective_date):  # pragma: no cover - regex gate
                raise ValueError(f"Invalid effective date for profile {chart}")
            if not critical:
                raise ValueError(f"Missing critical point for profile {chart}")
            airways = [
                value.strip()
                for value in airway_text.split(",")
                if value.strip()
            ]
            rows.append(
                {
                    "chart": chart,
                    "from": endpoints[0].strip().upper(),
                    "to": endpoints[1].strip().upper(),
                    "from_aliases": [endpoints[0].strip().upper()],
                    "to_aliases": [endpoints[1].strip().upper()],
                    "airways": airways,
                    "critical": critical.upper(),
                    "critical_aliases": [critical.upper()],
                    "effective_date": effective_date,
                    "effectivity": [
                        value.strip().upper()
                        for value in effectivity.split(",")
                        if value.strip()
                    ],
                    "chart_page": first_chart_page + ordinal - 1,
                }
            )

    charts = [row["chart"] for row in rows]
    if not rows:
        raise ValueError("No profile rows were extracted")
    if len(charts) != len(set(charts)):
        duplicates = sorted(
            chart for chart in set(charts) if charts.count(chart) > 1
        )
        raise ValueError(f"Duplicate profile identifiers: {', '.join(duplicates)}")
    return {
        "rows": rows,
        "profiles": [row for row in rows if not row.get("deleted")],
        "deleted_count": sum(bool(row.get("deleted")) for row in rows),
    }


_ALTITUDE = re.compile(r"\b(\d{1,2}),000\s*(?:FT|ft)\b")
_DISTANCE = re.compile(r"\b(\d{1,3})\s*(?:NM|nm)\b")


def parse_chart_page(text: str, profile: dict[str, Any]) -> dict[str, Any] | None:
    """Extract drawable schematic facts from one profile chart page.

    Returns None (fail closed) unless the page can be validated against the
    profile's own LOEP row: the corridor header must name both endpoints and
    the critical point must appear on the page. Only a validated page may
    drive the Level 1 analysis card; anything else falls back to the
    index-only card.
    """
    upper = text.upper()
    endpoints = [str(profile.get("from") or "").upper(), str(profile.get("to") or "").upper()]
    critical = str(profile.get("critical") or "").upper()
    if not all(value and value in upper for value in endpoints + [critical]):
        return None
    header = None
    for line in upper.splitlines():
        if "DEPRESSURIZATION ALONG" in line:
            header = " ".join(line.split())
            break
    if header is None or not all(value in header for value in endpoints):
        return None

    body = upper.split("DEPRESSURIZATION ALONG", 1)[1]
    body = body.split("IF DEPRESSURIZATION OCCURS", 1)[0]

    # Chart points in reading order: both endpoints, the critical point and
    # any intermediate fixes that carry a leg distance next to them.
    ordered: list[str] = []
    for line in body.splitlines():
        for token in re.findall(r"\b[A-Z]{4,5}\b", line):
            if token in ordered:
                continue
            if token in endpoints or token == critical:
                ordered.append(token)
            elif _DISTANCE.search(line) and token not in {
                "ALONG", "LEVEL", "FIRST", "POINT",
            }:
                ordered.append(token)
    if not (set(endpoints) <= set(ordered) and critical in ordered):
        return None

    altitudes = [f"{value},000 ft" for value in _ALTITUDE.findall(body)]
    distances = [int(value) for value in _DISTANCE.findall(body)]
    note = None
    if "IF DEPRESSURIZATION OCCURS" in upper:
        tail = upper.split("IF DEPRESSURIZATION OCCURS", 1)[1]
        note = " ".join(
            ("IF DEPRESSURIZATION OCCURS" + tail.split("\n\n", 1)[0]).split()
        )
    return {
        "header": header,
        "points": ordered,
        "critical": critical,
        "level_off_altitudes": altitudes,
        "segment_distances_nm": distances,
        "turn_note": note,
    }


def extract_chart_artifacts(
    pdf_path: Path,
    profiles: list[dict[str, Any]],
    charts_dir: Path,
) -> None:
    """Write one single-page PDF per profile chart and pin its sha256.

    Each profile gains ``chart_artifact_key`` + ``chart_sha256`` and a parsed
    ``schematic`` (or ``schematic_status: unavailable``). Artifact files live
    beside the index in private storage, never inside a repository.
    """
    from pypdf import PdfReader, PdfWriter

    reader = PdfReader(str(pdf_path))
    charts_dir.mkdir(parents=True, exist_ok=True)
    for profile in profiles:
        page_number = profile.get("chart_page")
        chart = str(profile.get("chart") or "")
        if not chart or not isinstance(page_number, int):
            continue
        if page_number < 1 or page_number > len(reader.pages):
            raise ValueError(
                f"Chart {chart} points at page {page_number}, outside the source document"
            )
        writer = PdfWriter()
        writer.add_page(reader.pages[page_number - 1])
        artifact_path = charts_dir / f"profile-{chart}.pdf"
        with artifact_path.open("wb") as handle:
            writer.write(handle)
        profile["chart_artifact_key"] = f"charts/profile-{chart}.pdf"
        profile["chart_sha256"] = hashlib.sha256(
            artifact_path.read_bytes()
        ).hexdigest()
        schematic = parse_chart_page(
            _pdftotext(pdf_path, page_number, page_number),
            profile,
        )
        if schematic is None:
            profile["schematic_status"] = "unavailable"
        else:
            profile["schematic_status"] = "parsed"
            profile["schematic"] = schematic


def build_index(
    pdf_path: Path,
    *,
    tenant_id: str,
    title: str,
    issue_date: str,
    coverage_scope: str,
    charts_dir: Path | None = None,
) -> dict[str, Any]:
    first_page = _pdftotext(pdf_path, 1, 1).lower()
    if "partial issue" in first_page and coverage_scope == "complete":
        raise ValueError(
            "The source declares itself a partial issue; it cannot be indexed as complete"
        )
    parsed = parse_effective_pages(_pdftotext(pdf_path, 7, 21))
    if charts_dir is not None:
        extract_chart_artifacts(pdf_path, parsed["profiles"], charts_dir)
    source_sha256 = hashlib.sha256(pdf_path.read_bytes()).hexdigest()
    return {
        "schema_version": 1,
        "document": {
            "tenant_id": tenant_id,
            "title": title,
            "issue_date": issue_date,
            "governance_state": "approved",
            "is_current": True,
            "coverage_scope": coverage_scope,
            "source_document_sha256": source_sha256,
            "source_row_count": len(parsed["rows"]),
            "deleted_count": parsed["deleted_count"],
        },
        "profiles": parsed["profiles"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument(
        "--title",
        default="A350 Depressurization Profiles",
    )
    parser.add_argument("--issue-date", required=True)
    parser.add_argument(
        "--coverage-scope",
        choices=("partial_issue", "complete"),
        default="partial_issue",
    )
    parser.add_argument(
        "--charts-dir",
        type=Path,
        default=None,
        help=(
            "Also extract one single-page chart PDF per profile into this "
            "private directory and pin each artifact's sha256 in the index"
        ),
    )
    args = parser.parse_args()
    index = build_index(
        args.pdf,
        tenant_id=args.tenant_id,
        title=args.title,
        issue_date=args.issue_date,
        coverage_scope=args.coverage_scope,
        charts_dir=args.charts_dir,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(index, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
                "profiles": len(index["profiles"]),
                "source_rows": index["document"]["source_row_count"],
                "deleted": index["document"]["deleted_count"],
                "coverage_scope": index["document"]["coverage_scope"],
                "source_document_sha256": index["document"][
                    "source_document_sha256"
                ],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
