"""Semantic validity of the numeric and coded cells the OFP table readers promote (QA512, 16 Oct 2026).

Codex's QA of release 512: the table readers checked a cell's shape only. "1960-2327" is four digits, a dash and four
digits, so the EDTO row was read and ODSS threw on minute 60 while building its period - the whole analysis failed -
and "YMML/99" or EDTO runway "99" is two digits, so an impossible runway was published as a plan. Every numeric or
coded cell a reader promotes now has a validity rule here, read from table_cell_rules.json (byte-identical to the app's
table-cell-rules.json); both runtimes run tests/fixtures/table-cell-vectors.json. A row with an invalid cell keeps its
airport and printed text and is held unread naming the invalid field; no value is chosen, repaired or inferred.
Runway numbering follows FAA AIM 2-3-3 (01-36, L/C/R for parallels) - a range rule, never an airport's runway inventory.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

RULES_PATH = Path(__file__).with_name("table_cell_rules.json")
RULES: dict[str, Any] = json.loads(RULES_PATH.read_text(encoding="utf-8"))
CELLS: dict[str, dict[str, Any]] = RULES["cells"]

_MINIMA = re.compile(r"(?:(?P<feet>\d{1,5})FT)?(?P<slash>/)?(?:(?P<metres>\d{1,5})M)?")


def cell_problem(kind: str, value: Any) -> str | None:
    """None when ``value`` is a valid ``kind`` cell, else the rule it breaks (the rules file's wording)."""
    rule = CELLS[kind]
    text = "" if value is None else str(value)
    if _valid(kind, rule, text):
        return None
    return str(rule["rule"])


def _valid(kind: str, rule: dict[str, Any], text: str) -> bool:
    if kind in {"icao", "iata"}:
        return re.fullmatch(rf"[A-Z]{{{int(rule['letters'])}}}", text) is not None
    if kind == "runway":
        match = re.fullmatch(r"(\d{2})([A-Z]?)", text)
        return bool(
            match
            and int(rule["number_min"]) <= int(match.group(1)) <= int(rule["number_max"])
            and (not match.group(2) or match.group(2) in rule["suffixes"])
        )
    if kind == "clock":
        match = re.fullmatch(r"(\d{2})(\d{2})", text)
        if not match:
            return False
        if text == "2400":
            return bool(rule["allow_2400"])
        return int(match.group(1)) <= int(rule["hour_max"]) and int(match.group(2)) <= int(rule["minute_max"])
    if kind == "duration":
        match = re.fullmatch(r"(\d{2})(\d{2})", text)
        if not match or int(match.group(2)) > int(rule["minute_max"]):
            return False
        total = int(match.group(1)) * 60 + int(match.group(2))
        return int(rule["total_minutes_min"]) <= total <= int(rule["total_minutes_max"])
    if kind == "distance_nm":
        return re.fullmatch(r"\d{4}", text) is not None and int(rule["min"]) <= int(text) <= int(rule["max"])
    if kind == "flight_level":
        return re.fullmatch(r"\d{3}", text) is not None and int(rule["min"]) <= int(text) <= int(rule["max"])
    if kind == "wind_component_kt":
        match = re.fullmatch(r"[MP](\d{3})", text)
        return bool(match) and int(match.group(1)) <= int(rule["max"])
    if kind == "fuel_kg":
        return re.fullmatch(r"\d{5}", text) is not None and int(rule["min"]) <= int(text) <= int(rule["max"])
    if kind == "minima":
        match = _MINIMA.fullmatch(text)
        if not match or not (match.group("feet") or match.group("metres")):
            return False
        if match.group("slash") and not (match.group("feet") and match.group("metres")):
            return False
        return (
            (not match.group("feet") or int(match.group("feet")) <= int(rule["feet_max"]))
            and (not match.group("metres") or int(match.group("metres")) <= int(rule["metres_max"]))
        )
    raise KeyError(f"no table-cell rule for {kind!r}")


def row_problems(cells: list[tuple[str, Any]]) -> list[dict[str, str]]:
    """The invalid cells of one printed row, in printed order: ``[(kind, value[, field]), ...]`` -> problems naming
    each field (the rules file's field name unless the row names the cell itself, as "period start").

    A blank optional cell (``None`` or "") is not a cell and is never judged here; the row grammar owns presence."""
    problems = []
    for kind, value, *field in cells:
        if value is None or value == "":
            continue
        rule = cell_problem(kind, value)
        if rule is not None:
            name = field[0] if field else CELLS[kind]["field"]
            problems.append({"field": str(name), "value": str(value), "rule": rule})
    return problems


def problems_text(problems: list[dict[str, str]]) -> str:
    """'its runway cell "99" is not valid (a runway designator is ...)' for each problem, joined."""
    return "; ".join(f'its {item["field"]} cell "{item["value"]}" is not valid ({item["rule"]})' for item in problems)
