"""Bounded taxiway subjects and extents for the PDF consequence projection.

The full app matcher still owns geometry. These rows describe routing scope;
they never promote a boundary or an explicitly normal taxiway to a closure.
Only identifiers and recognised relationships leave the source parser.
"""
from __future__ import annotations

import re

_REF = r"[A-Z](?:\d{1,2}[A-Z]?)?"
_KIND = r"(?:TWY|TAXIWAY|TXL|TAXILANE)"
_SUBJECT = re.compile(rf"\b{_KIND}\s+({_REF})(?=\b)")
_CLOSED = re.compile(r"\b(?:(?:WILL\s+BE|ARE|IS|TEMPO)\s+)?(?:CLSD|CLOSED)\b")


def _refs(value: str) -> list[str]:
    """Read only a complete designator list; prose cannot become a taxiway."""
    cleaned = re.sub(rf"\b{_KIND}\s+", "", value).strip()
    if not re.fullmatch(rf"{_REF}(?:(?:\s*,\s*|\s+AND\s+|\s*/\s*){_REF})*", cleaned):
        return []
    return re.split(r"\s*(?:,|/|\bAND\b)\s*", cleaned)


def _compact_refs(refs: list[str]) -> str:
    result = []
    index = 0
    while index < len(refs):
        end = index
        first = re.fullmatch(r"([A-Z])(\d+)", refs[index])
        while first and end + 1 < len(refs):
            following = re.fullmatch(r"([A-Z])(\d+)", refs[end + 1])
            if not following or following[1] != first[1] or int(following[2]) != int(first[2]) + end + 1 - index:
                break
            end += 1
        result.append(f"{refs[index]}-{refs[end]}" if end - index >= 2 else "/".join(refs[index:end + 1]))
        index = end + 1
    return "/".join(result)


def _endpoint(value: str) -> str | None:
    value = value.strip()
    junction = bool(re.match(r"(?:THE\s+)?JUNCTION(?:\s+OF)?\s+", value))
    value = re.sub(r"^(?:THE\s+)?JUNCTION(?:\s+OF)?\s+", "", value)
    direction = re.search(r"\s+(NB|SB|EB|WB)$", value)
    if direction:
        value = value[:direction.start()]
    refs = _refs(value)
    if not refs:
        return None
    return "/".join(refs) + (f" {direction[1]}" if direction else "") + (" junction" if junction else "")


def _subject_extent(value: str) -> list[str]:
    match = _SUBJECT.match(value.strip())
    if not match:
        return []
    body = value.strip()[match.end():].strip()
    first = match[1]
    if not body:
        return [first]
    if body.startswith((",", "AND ")):
        refs = _refs(first + " " + body)
        if refs:
            return [_compact_refs(refs)]
    bounds = re.fullmatch(r"(?:BTN|BETWEEN|FM|FROM)\s+(.+?)\s+(?:AND|TO)\s+(.+)", body)
    if bounds:
        left, right = bounds.groups()
        included = re.split(r",?\s+INCLUDING\s+", right, maxsplit=1)
        left, right = _endpoint(left), _endpoint(included[0])
        if left and right:
            suffix = ""
            if len(included) == 2:
                if included[1] == "ALL JUNCTIONS WITHIN":
                    suffix = ", including intervening junctions"
                else:
                    junction = _endpoint(included[1])
                    if not junction:
                        return []
                    suffix = f", including {junction}"
            return [f"{first} between {left} and {right}{suffix}"]
    behind = re.fullmatch(r"BEHIND\s+(?:ACFT\s+)?STANDS?\s+(.+)", body)
    if behind:
        ids = re.sub(r"\s+TO\s+", "/", behind[1])
        refs = _refs(ids)
        if refs:
            return [f"{first} behind stands {_compact_refs(refs)}"]
    junction = re.fullmatch(r"AND\s+(?:THE\s+)?JUNCTION(?:\s+OF)?\s+(.+)", body)
    if junction:
        refs = _refs(junction[1])
        if refs:
            return [f"{first} and {'/'.join(refs)} junction"]
    return []


def taxi_routing_scopes(raw: str) -> list[str]:
    text = " ".join(str(raw or "").upper().split())
    # Remarks describe boundaries that remain open, not additional subjects.
    body = re.split(r"\s*-?\s*RMK\s*:", text, maxsplit=1)[0]
    scopes = []
    header = re.search(r"\bFLW\s+TWY\s+CLSD\b[^:]*:\s*", body)
    if header:
        clauses = re.split(r"\s+\d+\)\s*", body[header.end():])
        for clause in clauses:
            clause = re.sub(r"^\d+\)\s*", "", clause).strip().rstrip(".")
            scopes.extend(_subject_extent(clause))
    else:
        # A source closure table establishes the state for each listed row.
        table = re.search(r"\bTWY CLOSURE PERIOD:\s*", body)
        if table:
            rows = body[table.end():].split("ALL MARKINGS", 1)[0]
            first = _SUBJECT.search(rows)
            if first:
                rows = rows[first.start():]
                # Boundary subjects stay with their owning row.
                starts = [m.start() for m in _SUBJECT.finditer(rows)
                          if not re.search(r"\b(?:BTN|BETWEEN|AND|TO|FM|FROM)\s*$", rows[:m.start()])]
                for i, start in enumerate(starts):
                    row = rows[start:starts[i+1] if i+1 < len(starts) else len(rows)].strip()
                    # Some published tables omit AND between two bound refs.
                    row = re.sub(rf"(\bBTN\s+{_KIND}\s+{_REF})\s+({_REF})$", r"\1 AND \2", row)
                    scopes.extend(_subject_extent(row))
        for clause in re.split(r"(?<=[.;])\s+|\s+\d+\.\d+\s+|\s+-\s+", body):
            closed = _CLOSED.search(clause)
            if not closed:
                continue
            prefix = clause[:closed.start()].strip()
            first = _SUBJECT.search(prefix)
            if first:
                scopes.extend(_subject_extent(prefix[first.start():]))
                # Stand-access lists can have a state after several rows.
                if "BEHIND" in prefix:
                    starts = [m.start() for m in _SUBJECT.finditer(prefix)]
                    for i, start in enumerate(starts):
                        row = prefix[start:starts[i+1] if i+1 < len(starts) else len(prefix)].strip().rstrip(",")
                        if re.match(rf"{_KIND}\s+{_REF}\s+BEHIND\b", row):
                            scopes.extend(_subject_extent(row))
        # A following TEMPO CLSD closes a complete stand-access list, even
        # when the source separates its common state with a printed dash.
        stand_list = re.search(r"\bCLOSURE OF TXL AND ACFT STANDS:\s*(.+?)\s*-\s*TEMPO CLSD\b", body)
        if stand_list:
            rows = stand_list[1]
            starts = [m.start() for m in _SUBJECT.finditer(rows)]
            for i, start in enumerate(starts):
                row = rows[start:starts[i+1] if i+1 < len(starts) else len(rows)].strip().rstrip(",")
                if re.match(rf"{_KIND}\s+{_REF}\s+BEHIND\b", row):
                    scopes.extend(_subject_extent(row))
    return list(dict.fromkeys(scopes))
