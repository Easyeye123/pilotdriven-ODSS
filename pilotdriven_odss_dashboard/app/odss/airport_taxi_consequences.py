"""Bounded taxiway subjects and extents for the PDF consequence projection.

The full app matcher still owns geometry. These rows describe routing scope;
they never promote a boundary or an explicitly normal taxiway to a closure.
Only identifiers and recognised relationships leave the source parser.

This module also owns the places a taxiway extent can start or end at, for
both publication paths: the PDF's routing scopes below, and the dashboard
subject ``engines._notam_subject`` publishes. Independent replay of two real
flights (22 Sep 2026) found the subject reader cutting VAAH A1134/26's end
point to "RAPID" and KJFK A3912/26's to "TERMINAL 5", while this reader could
not read two-letter taxiways at all and published an extent's END point as
the closed taxiway ("A/B" for KJFK A8688/25, "TWY KG BTN TWY A AND TWY B").
A place is now read whole or not at all.
"""
from __future__ import annotations

from dataclasses import dataclass
import re

_KIND = r"(?:TWY|TAXIWAY|TXL|TAXILANE)"
# Two-letter words a bare token can be that never name a taxiway.
_NOT_A_NAME = r"(?:AT|TO|OF|ON|IN|BY|OR|IS|BE|AS|NO|UP|FM|IF|IT|WI|NM|FT|HR)"
_PHONETIC = (
    r"(?:ALFA|ALPHA|BRAVO|CHARLIE|DELTA|ECHO|FOXTROT|GOLF|HOTEL|INDIA|JULIETT?|KILO|LIMA|MIKE|"
    r"NOVEMBER|OSCAR|PAPA|QUEBEC|ROMEO|SIERRA|TANGO|UNIFORM|VICTOR|WHISKEY|WHISKY|X-?RAY|YANKEE|ZULU)"
)
# A taxiway or taxilane name: one or two letters (A, KG), letters with a number
# (A4, DP2, B17, F1B), a hyphenated name (OUT-6) or a spelled letter (BRAVO).
# Three bare letters are words (AND, THE, DUE) - never a name.
_REF = (
    rf"(?:{_PHONETIC}|[A-Z]{{1,4}}-\d{{1,2}}|[A-Z]{{1,3}}\d{{1,3}}[A-Z]?"
    rf"|(?!{_NOT_A_NAME}(?![A-Z0-9]))[A-Z]{{1,2}})(?![A-Z0-9-])"
)
_SUBJECT = re.compile(rf"\b{_KIND}\s+({_REF})(?=\b)")


def is_prose_word(value: str) -> bool:
    """A plain word of three or more letters that is not a spelled taxiway letter: "GUIDANCE" in "TWY GUIDANCE SIGNS"."""
    return value.isalpha() and len(value) >= 3 and re.fullmatch(_PHONETIC, value) is None


_CLOSED = re.compile(r"\b(?:(?:WILL\s+BE|ARE|IS|TEMPO)\s+)?(?:CLSD|CLOSED)\b")
_DIRECTION = r"(?:NB|SB|EB|WB|NORTHBOUND|SOUTHBOUND|EASTBOUND|WESTBOUND)"
_RUNWAY_END = r"\d{2}[LCR]?"
_FACILITY_ID = r"[A-Z0-9]{1,5}(?![A-Z0-9])"


def _surface(kind: str | None) -> str:
    return "TXL" if kind in {"TXL", "TAXILANE"} else "TWY"


@dataclass(frozen=True)
class TaxiPlace:
    """One place an extent starts or ends at, read whole from the source."""

    form: str  # taxiway | runway | runway_end | threshold | junction | facility | stand
    label: str
    surface: str = ""
    ident: str = ""
    direction: str = ""
    qualifier: str = ""
    members: tuple[tuple[str, str], ...] = ()


_TAXIWAY_PLACE = re.compile(
    rf"(?:(?P<qualifier>(?:RAPID|HIGH[\s-]+SPEED)\s+EXIT)\s+)?(?P<kind>{_KIND})\s+(?P<ident>{_REF})"
    rf"(?:\s+(?P<direction>{_DIRECTION}))?"
)
_MEMBER = rf"(?:{_KIND}\s+)?{_REF}"
_JOIN = r"(?:\s*/\s*|\s*,\s*|\s+AND\s+)"
_RUNWAY_PLACE = re.compile(rf"(?:RWY|RUNWAY)\s*(?P<a>{_RUNWAY_END})(?:\s*/\s*(?P<b>{_RUNWAY_END}))?")


def read_taxi_place(text: str, inherit: TaxiPlace | None = None) -> TaxiPlace | None:
    """The whole place ``text`` names, or None - never a leading part of it.

    A bare identifier is a place only where the notice has already named its
    kind: the first bound of a taxiway's own extent ("TWY A BTN A5 AND A8"), or
    the second bound of a pair ("TXL R23 AND R24", "RWY 19R/01L AND 19L/01R").
    """
    value = " ".join(str(text or "").split())
    if not value:
        return None
    taxiway = _TAXIWAY_PLACE.fullmatch(value)
    if taxiway:
        qualifier = " ".join(taxiway["qualifier"].split()) if taxiway["qualifier"] else ""
        surface = _surface(taxiway["kind"])
        return TaxiPlace("taxiway", " ".join(part for part in (qualifier, surface, taxiway["ident"]) if part),
                         surface, taxiway["ident"], taxiway["direction"] or "", qualifier)
    end = re.fullmatch(rf"(?:APCH|APPROACH)\s+END\s+(?:OF\s+)?(?:RWY|RUNWAY)\s*(?P<end>{_RUNWAY_END})", value)
    if end:
        return TaxiPlace("runway_end", f"APCH END RWY {end['end']}")
    threshold = re.fullmatch(rf"(?:THR|THRESHOLD)\s+(?:(?:RWY|RUNWAY)\s*)?(?P<end>{_RUNWAY_END})", value)
    if threshold:
        return TaxiPlace("threshold", f"THR RWY {threshold['end']}")
    runway = _RUNWAY_PLACE.fullmatch(value)
    if runway:
        return TaxiPlace("runway", "RWY " + runway["a"] + (f"/{runway['b']}" if runway["b"] else ""))
    junction = re.fullmatch(
        rf"(?:THE\s+)?JUNCTION\s+(?:OF\s+)?(?P<members>{_MEMBER}(?:{_JOIN}{_MEMBER})+)", value,
    )
    if junction:
        members = []
        for part in re.split(_JOIN, junction["members"]):
            member = re.fullmatch(rf"(?:(?P<kind>{_KIND})\s+)?(?P<ident>{_REF})", part)
            if not member:
                return None
            members.append((_surface(member["kind"]) if member["kind"] else "", member["ident"]))
        return TaxiPlace("junction", value, members=tuple(members))
    if re.fullmatch(rf"(?:TERMINAL|HANGAR|CARGO)\s+{_FACILITY_ID}\s+(?:RAMP|APRON|APN)", value) \
            or re.fullmatch(rf"DE-?ICING\s+(?:PLATFORM|PAD|APRON|AREA)\s+{_FACILITY_ID}", value) \
            or re.fullmatch(rf"(?:GATE|APRON|APN|INT|INTERSECTION)\s+{_FACILITY_ID}", value):
        return TaxiPlace("facility", value)
    stand = re.fullmatch(rf"(?:ACFT\s+)?STAND\s+(?P<ident>{_FACILITY_ID})", value)
    if stand:
        return TaxiPlace("stand", value, ident=stand["ident"])
    if inherit is not None:
        if inherit.form == "taxiway" and not inherit.qualifier and re.fullmatch(_REF, value):
            return TaxiPlace("taxiway", f"{inherit.surface} {value}", inherit.surface, value)
        if inherit.form == "stand" and re.fullmatch(_FACILITY_ID, value):
            return TaxiPlace("stand", f"STAND {value}", ident=value)
        pair = re.fullmatch(rf"(?P<a>{_RUNWAY_END})(?:\s*/\s*(?P<b>{_RUNWAY_END}))?", value)
        if inherit.form == "runway" and pair:
            return TaxiPlace("runway", "RWY " + pair["a"] + (f"/{pair['b']}" if pair["b"] else ""))
    return None


def taxi_place_label(place: TaxiPlace, surface: str) -> str:
    """How a place reads beside a taxiway of kind ``surface``.

    A taxiway of the same kind prints by name alone ("between C and B1"); one of
    another kind keeps its kind, because TXL C3 is not TWY C3.
    """
    if place.form == "taxiway":
        if place.qualifier:
            return place.label
        core = place.ident if place.surface == surface else f"{place.surface} {place.ident}"
        return f"{core} {place.direction}".strip()
    if place.form == "junction":
        parts = [ident if kind in {"", surface} else f"{kind} {ident}" for kind, ident in place.members]
        return "/".join(parts) + " junction"
    return place.label


# What may follow an extent's END point: punctuation, a list marker, or a word
# that starts the predicate or a qualifier. Anything else makes the end point
# unreadable rather than shorter.
_END_BOUNDARY = re.compile(
    r"\s*[.,;:()]|\s+-(?=\s)|\s+\d{1,2}[.)](?=\s|[A-Z])|\s+(?:I{1,3}|IV|VI{0,3}|IX|X)[:)]"
    r"|\s+(?:CLSD|CLOSED|CLOSURE|DUE|INCLUDING|INCL|EXCLUDING|EXCL|EXCLUDED|INCLUDED|WIP|IS|ARE|WILL|"
    r"HAD|HAS|NOT|LGT|LGTD|LIGHTED|UNLGTD|CHANGED|DOWNGRADED|COMMISSIONED|DECOMMISSIONED|IRREGULAR|"
    r"ASPH|AVBL|AVAILABLE|U/S|UNSERVICEABLE|RESTRICTED|BARRICADED|MARKED|EXC|EXCEPT|FOR|WEF|UFN|TIL|"
    r"UNTIL|DLY|DAILY|RMK|TEMPO|DURING|ONLY|OPS|MAINT)(?![A-Z0-9])|\s*$"
)
_EXTENT_OPEN = re.compile(
    rf"\b(?:(?:PORTION|PART|SECTION)\s+OF\s+)?(?:(?:APN|APRON)\s+)?(?P<kind>{_KIND})\s+(?P<ident>{_REF})"
    rf"(?:\s+(?P<direction>{_DIRECTION}))?(?:\s*\((?P<side>[A-Z]+)\))?"
    # Codex QA of release 468 (F6): WSSS A2508/26 prints "TWY Q BTW TXL Q3 AND TWY P7" - BTW as between.
    r"\s+(?:(?:IS\s+|WILL\s+BE\s+)?(?:CLSD|CLOSED)\s+)?(?:BTN|BETWEEN|BTW)\s+"
)


def normalise_notice(text: str) -> str:
    upper = " ".join(str(text or "").upper().split())
    # 'Y' and '837' as printed name a taxiway and a stand, not a quotation.
    return re.sub(r"'([A-Z0-9]{1,6})'", r"\1", upper)


@dataclass(frozen=True)
class TaxiExtent:
    """A taxiway closed between two places, in source order."""

    surface: str
    name: str
    start: TaxiPlace | None
    end: TaxiPlace | None

    @property
    def complete(self) -> bool:
        return self.start is not None and self.end is not None

    def subject(self) -> str:
        if not self.complete:
            return f"part of {self.name}"
        return (f"{self.name} between {taxi_place_label(self.start, self.surface)} "
                f"and {taxi_place_label(self.end, self.surface)}")


def _extent_at(upper: str, opening: "re.Match[str]") -> tuple[TaxiExtent, int]:
    """The extent an opening starts, and where its text ends."""
    surface = _surface(opening["kind"])
    own = TaxiPlace("taxiway", f"{surface} {opening['ident']}", surface, opening["ident"])
    name = " ".join(part for part in (
        surface, opening["ident"], opening["direction"] or "",
        f"({opening['side']})" if opening["side"] else "",
    ) if part)
    rest = upper[opening.end():]
    split = re.search(r"\s+AND\s+", rest)
    if not split:
        return TaxiExtent(surface, name, None, None), len(upper)
    start = read_taxi_place(rest[:split.start()], inherit=own)
    after = rest[split.end():]
    boundary = _END_BOUNDARY.search(after)
    end_text = after[:boundary.start()] if boundary else after
    end = read_taxi_place(end_text, inherit=start)
    return TaxiExtent(surface, name, start, end), opening.end() + split.end() + len(end_text)


def bounded_taxiway_extents(text: str) -> list[TaxiExtent]:
    """Every "<taxiway> BTN <place> AND <place>" the notice states.

    Both places must be read whole, and the end point must be followed by a
    boundary. One that cannot be read leaves the extent incomplete - never a
    truncated place and never the whole taxiway.
    """
    upper = normalise_notice(text)
    return [_extent_at(upper, opening)[0] for opening in _EXTENT_OPEN.finditer(upper)]


_SCOPE_PREDICATE = re.compile(r"\s+(?:(?:IS|ARE|WILL\s+BE|TEMPO)\s+)?(?:CLSD|CLOSED)(?![A-Z0-9])")
_SCOPE_AFTER_PREDICATE = re.compile(
    r"\s+(?:BTN|BETWEEN|BTW|FM|FROM|AFTER|BEFORE|ABEAM|ADJ|EXC|EXCEPT|BEHIND|NORTH|SOUTH|EAST|WEST|"
    r"PORTION|PART|SECTION)(?![A-Z0-9])"
)
# WSSS SX83/24 "TXL R1 BEHIND ACFT STAND E5, TXL R2 BEHIND ...": a designation word is never a stand, so the next
# designation after a comma ends the stand list instead of joining it.
_STAND_LIST = rf"{_FACILITY_ID}(?:\s*(?:,|AND|TO)\s*(?!{_KIND}(?![A-Z0-9])){_FACILITY_ID})*"


def _designation_scope(upper: str, end: int, surface: str, ident: str) -> tuple[str | None, int]:
    """The partial scope of the designation ending at ``end`` (None if whole),
    and where the text that scope speaks for ends."""
    name = f"{surface} {ident}"
    position = end
    direction = re.match(rf"\s+({_DIRECTION})(?![A-Z0-9])", upper[position:])
    if direction:
        name, position = f"{name} {direction[1]}", position + direction.end()
    side = re.match(r"\s*\(([A-Z]+)\)", upper[position:])
    if side:
        name, position = f"{name} ({side[1]})", position + side.end()
    closed = _SCOPE_PREDICATE.match(upper[position:])
    after_at = position + (closed.end() if closed else 0)
    after = upper[after_at:]
    compass = re.match(r"\s+(?P<side>NORTH|SOUTH|EAST|WEST)\s+OF\s+", after)
    if compass:
        tail = after[compass.end():]
        boundary = _END_BOUNDARY.search(tail)
        place_text = tail[:boundary.start()] if boundary else tail
        place = read_taxi_place(place_text, inherit=TaxiPlace("taxiway", name, surface, ident))
        consumed = after_at + compass.end() + len(place_text)
        if place is None:
            return f"part of {name}", consumed
        return f"{name} {compass['side'].lower()} of {taxi_place_label(place, surface)}", consumed
    # Codex QA of release 468 (F6): WSSS A2757/26 "TXL N1 NB AFTER ACFT STAND 517L CLSD" bounds N1 by a stand as BEHIND does.
    behind = re.match(rf"\s+(?P<relation>BEHIND|AFTER)\s+(?:ACFT\s+)?(?P<stands>STANDS?)\s+(?P<ids>{_STAND_LIST})", after)
    # The stand list is whole when what follows cannot be another stand: a
    # boundary, a word (CLSD, VALIDITY) or the next taxiway's kind.
    if behind and (_END_BOUNDARY.match(after[behind.end():])
                   or re.match(rf"\s+(?:{_KIND}|AND|[A-Z]{{4,}})(?![A-Z0-9])", after[behind.end():])):
        ids = re.sub(r"\s*,\s*", ", ", behind["ids"])
        ids = re.sub(r"\s+(AND|TO)\s+", lambda word: f" {word[1].lower()} ", ids)
        return f"{name} {behind['relation'].lower()} {behind['stands'].lower()} {ids}", after_at + behind.end()
    # An unread qualifier speaks for its own list item only.
    item_end = re.search(rf",|;|\.\s|{_ITEM_MARKER}", upper[position:])
    unread_end = position + item_end.start() if item_end else len(upper)
    if closed:
        if _SCOPE_AFTER_PREDICATE.match(after):
            return f"part of {name}", unread_end
        return None, after_at
    if re.match(rf"\s*(?:,|AND(?![A-Z0-9]))\s*(?:{_KIND}\s+)?{_REF}", upper[position:]) \
            or re.match(r"\s*(?:[.;]|$)", upper[position:]):
        return None, position
    return f"part of {name}", unread_end


def taxiway_designation_scope(upper: str, end: int, surface: str, ident: str) -> str | None:
    """The partial scope of the designation ending at ``end``, or None if whole.

    A designation followed by its closure, by a list sibling or by the end of
    its statement is closed whole. A recognised qualifier gives the partial
    scope ("TWY W south of DP2", "TWY N2 behind stands 504 to 512"); any other
    qualifier gives "part of TWY Q" - a partial closure is never published as
    the whole taxiway.
    """
    return _designation_scope(upper, end, surface, ident)[0]


_ITEM_MARKER = r"(?:^|\s)(?:\d{1,2}[.)]|(?:I{1,3}|IV|VI{0,3}|IX|X)[:)])(?=\s|[A-Z])"
_DESIGNATION = re.compile(rf"(?<![A-Z0-9-])(?P<kind>{_KIND})\s+(?P<ident>{_REF})")
_CONTINUATION = re.compile(
    rf"\s*(?:,|AND(?![A-Z0-9]))\s*(?P<ident>{_REF})(?:\s+{_DIRECTION})?(?=\s*(?:,|AND(?![A-Z0-9])|[.;]|$))"
)
# Words that may lead a listed closure without being part of it: a schedule,
# an airport's three-letter code, "PORTION OF", "CLOSURE OF".
_LEADING_WORD = re.compile(
    r"(?:[A-Z]{3}|\d[\d/-]*|DLY|DAILY|H24|PORTION|PART|SECTION|OF|CLOSURE|APN|APRON|THE|FORMER|AND|TEMPO)"
)


def _segment_items(segment: str) -> tuple[list[tuple[str, str]], bool]:
    """The closed items one list segment names, each by its own read scope."""
    items: list[tuple[str, str]] = []
    covered = [False] * len(segment)
    position = 0
    for designation in _DESIGNATION.finditer(segment):
        if designation.start() < position:
            continue  # a bound or place of the item before it
        surface = _surface(designation["kind"])
        opening = _EXTENT_OPEN.match(segment, designation.start())
        if opening:
            extent, end = _extent_at(segment, opening)
            items.append(("extent", extent.subject()))
        else:
            scope, end = _designation_scope(segment, designation.end(), surface, designation["ident"])
            items.append(("partial" if scope else "surface", scope or f"{surface} {designation['ident']}"))
            if scope is None:
                # A whole closure may continue as a list: "TWY ZA, EA", "TWY C AND K".
                while continuation := _CONTINUATION.match(segment, end):
                    items.append(("surface", f"{surface} {continuation['ident']}"))
                    end = continuation.end()
        for index in range(designation.start(), min(end, len(segment))):
            covered[index] = True
        position = max(position, end)
    leftover = "".join(" " if covered[index] else character for index, character in enumerate(segment))
    exact = all(re.fullmatch(_LEADING_WORD, word) for word in re.findall(r"[A-Z0-9][A-Z0-9/-]*", leftover))
    return items, exact


# ITEM 4, VRMM SX5/26 (9 Oct 2026). Malé's supplement states its closures as two sentences: "A PORTION OF TWY C CLOSED
# TO ALL AIRCRAFT OPERATIONS FROM A POINT IMMEDIATELY SOUTH OF TWY D2 (EXCLUDING TWY D2) TO A DISTANCE OF
# APPROXIMATELY 1,440M." and "TWYS D3, D4, F, AND G ARE ALSO CLOSED DURING THIS PERIOD." The first read as "part of
# TWY C" with its stated side and length lost; the plural list was not read at all. Each statement is read whole by
# these two forms first; any other statement is read as before.
_SIDE_LENGTH_CLOSURE = re.compile(
    rf"(?:\b(?:A\s+)?(?:PORTION|PART|SECTION)\s+OF\s+)?(?<![A-Z0-9-])(?P<kind>{_KIND})\s+(?P<ident>{_REF})\s+"
    r"(?:IS\s+|WILL\s+BE\s+)?(?:CLSD|CLOSED)\s+"
    r"(?:TO\s+ALL\s+(?:ACFT|AIRCRAFT)(?:\s+(?:OPERATIONS|OPS))?\s+)?(?:(?:FROM|FM)\s+A\s+POINT\s+(?:IMMEDIATELY\s+)?)?"
    rf"(?P<side>NORTH|SOUTH|EAST|WEST)\s+OF\s+(?P<bound_kind>{_KIND})\s+(?P<bound>{_REF})\s+"
    r"(?:TO|FOR)\s+A\s+(?:DISTANCE|LENGTH)\s+OF\s+(?:APPROX(?:IMATELY|\.)?\s+|ABOUT\s+)?"
    r"(?P<length>\d{1,2},\d{3}|\d{2,5})\s*(?:M|METRES|METERS)\b"
)
_LISTED_PLURAL_CLOSURE = re.compile(
    rf"(?<![A-Z0-9-])(?P<kind>TWYS|TAXIWAYS|TXLS|TAXILANES)\s+(?P<refs>{_REF}(?:\s*(?:,\s*AND|,|AND)\s*{_REF})+)\s+"
    r"(?:(?:ARE|WILL\s+BE)\s+)?(?:ALSO\s+)?(?:CLSD|CLOSED)\b"
)


def _statement_closure_items(statement: str) -> list[tuple[str, str]] | None:
    """The items a statement closes when it is one of the two whole forms above, else None."""
    side = _SIDE_LENGTH_CLOSURE.search(statement)
    if side:
        surface = _surface(side["kind"])
        length = f"{int(side['length'].replace(',', '')):,}"
        return [("partial", f"{surface} {side['ident']} {side['side'].lower()} of {side['bound']} for about {length} m")]
    listed = _LISTED_PLURAL_CLOSURE.search(statement)
    if listed:
        surface = "TXL" if listed["kind"] in {"TXLS", "TAXILANES"} else "TWY"
        refs = re.split(r"\s*(?:,\s*AND|,|AND)\s*", listed["refs"].strip())
        return [("surface", f"{surface} {ref}") for ref in refs if ref]
    return None


def taxiway_closure_items(text: str) -> tuple[list[tuple[str, str]], bool]:
    """Every closed taxiway item the notice lists, and whether all were read.

    An item is a bounded extent, another partial scope or a whole taxiway,
    each named by the scope this module reads for it, so repeated mentions of
    one closure count once and a bound, a stand or a place never counts as an
    item. ``exact`` is False when the list holds text that is not one of its
    items, so a caller never states a count it does not have.
    """
    upper = normalise_notice(text)
    # Remarks describe what stays open; brackets qualify, they do not list.
    upper = re.split(r"\s*-?\s*\bRMK\b", upper, maxsplit=1)[0]
    upper = re.sub(r"\([^()]*\)", " ", upper)
    header = re.search(r"\b(?:CLSD|CLOSED)\b[^:.]*:", upper)
    read: list[tuple[str, str]] = []
    if header and re.search(rf"\b{_KIND}\b", upper[:header.end()]):
        segments = re.split(rf"{_ITEM_MARKER}|\.\s+|;\s*", upper[header.end():])
    else:
        segments = []
        for statement in re.split(r"\.\s+|;\s*", upper):
            whole = _statement_closure_items(statement)
            if whole is not None:
                read.extend(item for item in whole if item not in read)
                continue
            closed = _CLOSED.search(statement)
            if closed:
                segments.append(statement[:closed.start()])
    items: list[tuple[str, str]] = list(read)
    exact = True
    for segment in segments:
        # A marker left at the front when a sentence end split the list ("... Q3. II: TXL Q3").
        segment = re.sub(r"^\s*(?:\d{1,2}[.)]|(?:I{1,3}|IV|VI{0,3}|IX|X)[:)])\s*", "", segment or "")
        segment = re.split(r",?\s+(?:INCLUDING|INCL|EXCLUDING)\b", segment, maxsplit=1)[0].strip(" .,;")
        if not segment:
            continue
        found, clean = _segment_items(segment)
        exact = exact and clean
        for item in found:
            if item not in items:
                items.append(item)
    # Codex QA of release 468 (F5): a later mention of a designation whose scope is already stated ("TXL N4 behind stand
    # 604", then "THE CLSD SECTION OF TXL N4 ...") is the same closure, not a further item - WSSS SX168/26 was counted
    # twice, so its card claimed further closures and its PDF consequence stayed unresolved.
    stated = {" ".join(label.split(" ")[:2]) for _, label in items if not label.startswith("part of ")}
    items = [item for item in items if not (item[1].startswith("part of ") and item[1][len("part of "):] in stated)]
    return items, exact


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


def _endpoint(value: str, surface: str, inherit: TaxiPlace | None = None) -> tuple[TaxiPlace, str] | None:
    """One bound of an extent, read whole by the shared place grammar."""
    place = read_taxi_place(value.strip(), inherit=inherit)
    if place is None:
        return None
    return place, taxi_place_label(place, surface)


def _subject_extent(value: str) -> list[str]:
    match = _SUBJECT.match(value.strip())
    if not match:
        return []
    body = value.strip()[match.end():].strip()
    first = match[1]
    surface = _surface(value.strip().split(" ", 1)[0])
    if not body:
        return [first]
    if body.startswith((",", "AND ")):
        refs = _refs(first + " " + body)
        if refs:
            return [_compact_refs(refs)]
    bounds = re.fullmatch(r"(?:BTN|BETWEEN|BTW|FM|FROM)\s+(.+?)\s+(?:AND|TO)\s+(.+)", body)
    if bounds:
        left_text, right_text = bounds.groups()
        included = re.split(r",?\s+INCLUDING\s+", right_text, maxsplit=1)
        left = _endpoint(left_text, surface, inherit=TaxiPlace("taxiway", f"{surface} {first}", surface, first))
        right = _endpoint(included[0], surface, inherit=left[0] if left else None)
        if left and right:
            suffix = ""
            if len(included) == 2:
                if included[1] == "ALL JUNCTIONS WITHIN":
                    suffix = ", including intervening junctions"
                else:
                    junction = _endpoint(included[1], surface)
                    if not junction:
                        return []
                    suffix = f", including {junction[1]}"
            return [f"{first} between {left[1]} and {right[1]}{suffix}"]
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
            # "TAXIWAY TANGO CLOSED NORTH OF TAXIWAY JULIET": the scope follows
            # the closure, so the words before it are not the closed extent.
            if _SCOPE_AFTER_PREDICATE.match(clause[closed.end():]):
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
