"""QA514 generators (LABELLED SYNTHETIC; Codex's QA of release 514, 17 Oct 2026, output/pd-514-codex-qa-20261017).

The app carries the same generators (tests/helpers/notam-timing-qa514-generators.mjs): the same lists, the same seeded
PRNG (mulberry32, integer draws) and the same order, so both runtimes build byte-identical cases and pin the same
digests.

compositions(): every restriction x every component x both word orders x every joiner (none, period, comma,
  semicolon, line break, parentheses) x Item D (none, equal, other) - each with the outcome its SYNTAX gives: temporal
  content (well-formed or malformed) is a review unless it restates Item D; genuine non-temporal content (contact
  instructions, frequencies, altitudes, distances, designators, references) is the canonical decision; an office's
  hours are benign only when a contact verb governs them (the nearest verb before them is a contact verb, or they open
  a clause whose next verb is one).
fuzz_cases(): random digit tokens - letters glued before them or not (the time designators Z, L, LT, LCL, UTC, GMT, H,
  T, or S, TD, KHUTA), 1 to 3 groups of 1 to 6 digits (ASCII, or a script NFKC leaves alone: Arabic-
  Indic, Extended Arabic-Indic, Devanagari, Bengali, Thai, or mixed) joined by . : - / space H h Z L , - with
  connectives before and after, placed after, before, inside, beside or bracketed with a restriction, with and without
  Item D. fuzz_verdict() is the invariant: a digit no stated class masks makes the decision a review (unless the
  segment restates Item D exactly); a digit a class masks must fit that class's stated definition; the decision is
  always the canonical decision or a review.
"""
from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any, Callable

VALIDITIES = {
    "AUG": "01-AUG-26 0000 - 31-AUG-26 2359",
    "START_AT_0800": "16-AUG-26 0800 - 31-AUG-26 2359",
    "END_AT_1000": "01-AUG-26 0000 - 16-AUG-26 1000",
    "START_1200": "16-AUG-26 1200 - 31-AUG-26 2359",
    "END_1600": "01-AUG-26 0000 - 16-AUG-26 1600",
}


def _at(hour: int) -> dict[str, str]:
    return {"startsAt": f"2026-08-16T{hour - 2:02d}:00:00Z", "endsAt": f"2026-08-16T{hour + 2:02d}:00:00Z",
            "referenceAt": f"2026-08-16T{hour:02d}:00:00Z"}


# References on Item D's edges (0800, 1000, 1800, 2000) and off them (1300), each with a +-2h window.
WINDOWS = {"R0800": _at(8), "R1000": _at(10), "R1300": _at(13), "R1800": _at(18), "R2000": _at(20)}

ITEM_D: dict[str, list[str]] = {"NONE": [], "D0800": ["DLY 0800-1000"], "D1800": ["DLY 1800-2000"]}

RESTRICTIONS = ["TWY J CLSD", "RWY 09/27 CLSD", "AREA R123 ACT"]

# kind: temporal = always a review; equal = restates DLY 0800-1000 (that Item D: canonical or review; else review);
# contact = an hours phrase after its contact verb (canonical; 'CALL OPS ...' is temporal: OPS is a restriction word,
# so the nearest verb is not a contact verb); adverbial = an hours phrase opening its contact clause (canonical unless
# it directly follows the restriction verb in the same clause); benign = canonical.
# QA514 G3 (structure): opening = a label that is structure only where it opens a clause or a body line (canonical
# there, a review elsewhere); lineOpening = only where it opens a body line; listAfterVerb = a list label, a review only
# directly after the restriction verb in the same line; closing = a page that is structure only where it closes the
# reference (followed by the end, '.', ',', ';' or ')').
COMPONENTS = [
    ("temporal", "DURING THE OFFICE HOURS OF THE CAA"), ("temporal", "OUTSIDE THE OFFICE HOURS OF THE CAA"),
    ("temporal", "IN THE BUSINESS HOURS OF THE AIRPORT AUTHORITY"), ("temporal", "DURING NORMAL OFFICE HOURS"),
    ("temporal", "OFFICE HOURS APPLY"), ("temporal", "DURING: OFFICE HOURS OF THE CAA"),
    ("temporal", "08000-10000"), ("temporal", "8:3-9:3"), ("temporal", "8.3-9.3"), ("temporal", "FOR 1.5H"),
    ("temporal", "FOR TWO H"), ("temporal", "FROM EIGHT TO TEN"), ("temporal", "FROM EIGHT HUNDRED TO TEN HUNDRED"),
    ("temporal", "AT 1,200"), ("temporal", ".0800-.1000"), ("temporal", "#0800-#1000"), ("temporal", "08:0-10:0"),
    ("temporal", "O8OO-IOOO"), ("temporal", "FROM 08;00 TO 10;00"), ("temporal", "UNTIL 121.9"),
    ("temporal", "FROM 8 TO 10"), ("temporal", "FROM 8 TO 9"), ("benign", "YUKON 1-5"), ("temporal", "UNTIL 1000"), ("temporal", "1800-2000 LT"),
    ("equal", "0800-1000"), ("equal", "FROM 0800 TO 1000"), ("equal", "BTN 0800 AND 1000"),
    ("contact", "CONTACT CAA DURING NORMAL OFFICE HOURS"), ("contact", "FOR INFO CTC THE OFFICE HOURS OF THE CAA"),
    ("contact", "CALL THE DUTY OFFICER OUTSIDE OFFICE HOURS ON +65 6789 1234"),
    ("temporal", "CALL OPS OUTSIDE OFFICE HOURS"),
    ("adverbial", "AFTER HOURS CTC TEL +65 6789 1234"), ("adverbial", "OUTSIDE OFFICE HOURS CONTACT TWR ON 118.100 MHZ"),
    ("benign", "FREQ 122.850 MHZ"), ("benign", "NDB ABC 385 KHZ"), ("benign", "CRANE HGT 2350FT AMSL"),
    ("benign", "CRANE HGT 2400-2600FT AMSL"), ("benign", "TORA 3200M TODA 3400M"), ("benign", "VIS 1500M RVR 0650M"),
    ("benign", "STANDS 301-309"), ("benign", "TERMINAL 2"), ("benign", "REF A9876/26"), ("benign", "REF AIP AD 2.24-11"),
    ("benign", "ATS RTE Q907"), ("benign", "FL120-FL260"), ("benign", "OBST 1315N 12341E"), ("benign", "TEL +65 6789 1234"),
    ("benign", "PPR 36 HR"), ("benign", "NOTIFY TWR 3 HR IN ADVANCE"), ("benign", "MAX RECOVERY TIME 3 HOURS"),
    ("benign", "FICON 5/5/5"), ("benign", "ACFT B737-800"), ("benign", "OBST LGTD AT NIGHT"), ("benign", "FOR 90 MIN"),
    ("benign", "APAM-1620-AF-BRF-0032"), ("benign", "OBS AT 2608160830"), ("benign", "FIX AT 3.2 ISW DME"),
    # QA514 round 2 (G1-G4): traps that must stay timing, and genuine forms each rule makes benign by its context
    ("equal", "RWY 24 CLSD 0800-1000"), ("temporal", "TWY B 18H"), ("temporal", "FREQ 121.9 MHZ 18.00-20.00"),
    ("temporal", "CAT C 0800-1"), ("temporal", "RWY 24 UNTIL 1800"), ("temporal", "UNTIL S0840"), ("temporal", "AT S0840"),
    ("temporal", "CLSD-0800"), ("temporal", "8A-5P"), ("temporal", "AT 8A"), ("temporal", "FOR 8D"), ("temporal", "AT 24 HRS"), ("temporal", "BY 24 HRS"), ("temporal", "EVERY 24 HRS"), ("equal", "TWY K-0800-1000"),
    # G1 (coordinator): a time designator (Z, L, LT, LCL, UTC, GMT, H, T) glued to a VALID clock is a clock - with and
    # without a connective and inside ranges; on an invalid clock, or after other letters, an identifier (after a
    # connective a four-digit group glued to letters is still unreadable timing)
    ("temporal", "Z0800"), ("temporal", "LT0800"), ("temporal", "UTC0800-1000"), ("temporal", "H0800"), ("temporal", "L0800"),
    ("temporal", "LCL0800"), ("temporal", "GMT0800"), ("temporal", "T2400"), ("temporal", "UNTIL LT0800"), ("temporal", "FROM Z0800 TO Z1000"),
    ("temporal", "0800-T1000"), ("temporal", "LT2168-2200"), ("temporal", "UNTIL LT2168"), ("temporal", "TIL GMT5 24 HR"),
    ("benign", "FIX H2575"), ("benign", "POINT T0860"), ("benign", "WPT Z2460 AND KHUTA0800"),
    # QA516: a clock in digits NFKC leaves alone is never read as a value - an unaccounted digit, so a review
    ("temporal", "\u0660\u0668\u0660\u0660-\u0661\u0660\u0660\u0660"), ("temporal", "FROM \u06F0\u06F8\u06F0\u06F0 TO \u06F1\u06F0\u06F0\u06F0"),
    ("temporal", "\u0966\u096E\u0966\u0966-\u0967\u0966\u0966\u0966"), ("temporal", "08\u06600-1000"), ("temporal", "DLY \u0660\u0668\u0660\u0660-\u0661\u0660\u0660\u0660"),
    ("benign", "POINTS BEYOND ASSAD: S0840, S1040"), ("benign", "RAD LT2168"), ("benign", "REF AD2 LFAY.22.2"),
    ("benign", "REF AIP AD.2 UTDD-145,146"), ("benign", "RADAR (TRAC2000/RSM970)"), ("benign", "VIA NDB 'ZJ'-G345-OLRIS"),
    ("benign", "EKCHHOJ0001035/CRANE"), ("benign", "STAR BIBAX 9E 9D"), ("benign", "CRANE 439FT MSL (4A)"),
    ("benign", "THE ALTITUDE AT 4D IS AMENDED AS 1290FT"), ("benign", "BEYOND TORA RWY 24 AND 200M LEFT"),
    ("benign", "ONLY AT 25 THR"), ("benign", "HGT FT AMSL: 422.24"), ("benign", "LEAD RADIAL L.R.147"),
    ("benign", "HF 11297/11396/13300 KHZ"), ("benign", "VIS CAT B RVR 4000, C/D 1 7/8"), ("benign", "PROFILE ALT 770FT AT 2.2 TO SSYEM"),
    ("benign", "NO ACCESS TO 121.605 FREQUENCY"), ("benign", "MAX IAS 250KT BY 20 TAC"), ("benign", "COURSE 360(000.3)"),
    ("benign", "BTN 0.3 NM-(-0.5)NM"), ("benign", "MISSED APPROACH...473 FT"), ("benign", "LESS THAN 1/10TH INCH"),
    ("benign", "RWY TODA 09 2436(7992)(2.10) 27 2436(7992)(1.55)"), ("benign", "AOC TYPE B NR RF 4/7"),
    ("benign", "PURSUANT TO 49 USC 40103(B)(3)"), ("benign", "MARKED BY 90 X 90 CM FLAG"), ("benign", "SECTION 40103(B)(3)"),
    ("benign", "CONTACT THE FAA AT 9-ATOR-HQ-IFOS FAA.GOV"), ("benign", "QUESTIONS TO NCRCC AT 9-ATO-NCRCC(AT)FAA.GOV"),
    ("benign", "PHONE : +33 1 48 62 43 92"), ("benign", "BY CALLING +33 2 34 34 71 36"),
    ("opening", "(1)12MIN INTERVAL"), ("opening", "3.2.2 45.93 FT (14.47 M) AMSL"),
    ("opening", "1ST: 080651.12N 0981846.78E 2ND: 080651.92N 0981853.48E"), ("lineOpening", "2. 60MIN PN FOR NML OPS"),
    ("listAfterVerb", "3. EXPECT RADAR VECTORING"), ("closing", "REF AIP UATG AD 2.24.11 - 5"),
]

ORDERS = ["restrictionFirst", "componentFirst"]
JOINERS = ["none", "period", "comma", "semicolon", "linebreak", "parentheses"]
_BOUNDARY = {"period", "semicolon"}
_CLOSES = {"period", "comma", "semicolon", "parentheses"}


def compose_lines(restriction: str, component: str, order: str, joiner: str) -> list[str]:
    first, second = (restriction, component) if order == "restrictionFirst" else (component, restriction)
    if joiner == "none":
        return [f"{first} {second}."]
    if joiner == "period":
        return [f"{first}. {second}."]
    if joiner == "comma":
        return [f"{first}, {second}."]
    if joiner == "semicolon":
        return [f"{first}; {second}."]
    if joiner == "linebreak":
        return [first, f"{second}."]
    return [f"{restriction} ({component})." if order == "restrictionFirst" else f"({component}) {restriction}."]


def composition_expectation(kind: str, order: str, joiner: str, item_d: str) -> str:
    """'review', 'canonical' or 'canonicalOrReview' - from the component's syntax, never from the implementation."""
    if kind == "temporal":
        return "review"
    if kind == "equal":
        return "canonicalOrReview" if item_d == "D0800" else "review"
    if kind == "adverbial":
        return "canonical" if order == "componentFirst" or joiner in _BOUNDARY else "review"
    opens_line = (order == "componentFirst" and joiner != "parentheses") or (order == "restrictionFirst" and joiner == "linebreak")
    if kind == "opening":
        return "canonical" if opens_line or (order == "restrictionFirst" and joiner in _BOUNDARY) else "review"
    if kind == "lineOpening":
        return "canonical" if opens_line else "review"
    if kind == "listAfterVerb":
        return "review" if order == "restrictionFirst" and joiner == "none" else "canonical"
    if kind == "closing":
        return "canonical" if order == "restrictionFirst" or joiner in _CLOSES else "review"
    return "canonical"


def compositions() -> Iterator[dict[str, Any]]:
    for item_d in ITEM_D:
        for restriction in RESTRICTIONS:
            for kind, component in COMPONENTS:
                for order in ORDERS:
                    for joiner in JOINERS:
                        # A leading line made only of schedule tokens is Item D by the LIDO layout, not free text.
                        if kind == "equal" and order == "componentFirst" and joiner == "linebreak":
                            continue
                        yield {"itemD": item_d, "restriction": restriction, "kind": kind, "component": component,
                               "order": order, "joiner": joiner,
                               "lines": compose_lines(restriction, component, order, joiner),
                               "base": [f"{restriction}."],
                               "expect": composition_expectation(kind, order, joiner, item_d)}


class Mulberry32:
    """mulberry32: a 32-bit seeded PRNG; draws are integers, so both runtimes draw the same sequence."""

    def __init__(self, seed: int) -> None:
        self.state = seed & 0xFFFFFFFF

    def next(self) -> int:
        self.state = (self.state + 0x6D2B79F5) & 0xFFFFFFFF
        t = self.state
        t = ((t ^ (t >> 15)) * (t | 1)) & 0xFFFFFFFF
        t = (((t + (((t ^ (t >> 7)) * (t | 61)) & 0xFFFFFFFF)) & 0xFFFFFFFF) ^ t) & 0xFFFFFFFF
        return (t ^ (t >> 14)) & 0xFFFFFFFF

    def below(self, n: int) -> int:
        return (self.next() * n) >> 32

    def pick(self, items: list[Any]) -> Any:
        return items[self.below(len(items))]


FUZZ: dict[str, list[Any]] = {
    "separators": [".", ":", "-", "/", " ", "H", "h", "Z", "L", ","],
    "leads": ["", "", "", "", "", "", ".", "#", "0", "+"],
    # QA516: the script a token's digits are written in - ASCII mostly, else a script NFKC leaves alone (Arabic-Indic,
    # Extended Arabic-Indic, Devanagari, Bengali, Thai) or ASCII and Arabic-Indic mixed digit by digit
    "digitScripts": ["ascii", "ascii", "ascii", "ascii", "ascii", "ascii", "arabicIndic", "extendedArabicIndic", "devanagari",
                     "bengali", "thai", "mixed"],
    # G1: letters glued before a token's digits - the time designators, and letters that are no time designator
    "letters": ["", "", "", "", "", "", "", "", "", "", "Z", "L", "LT", "LCL", "UTC", "GMT", "H", "T", "S", "TD", "KHUTA"],
    "prefixes": ["", "", "", "FROM ", "UNTIL ", "TILL ", "TIL ", "AT ", "BY ", "BTN ", "BETWEEN ", "TO ", "DURING ",
                 "AFTER ", "BEFORE ", "WEF ", "THRU ", "OUTSIDE ", "FOR ", "ON ", "EVERY ", "DLY ", "SINCE ",
                 "TERMINAL ", "STAND "],
    "suffixes": ["", "", "", " UTC", "Z", " LT", " HR", " HRS", "H", " H", " MIN", " TO #", " AND #", "-#", "/#",
                 " DAILY", " DAYS", " TWY K", " OPEN"],
    "placements": ["end", "sentence", "before", "middle", "bracket"],
    "tails": ["", "", " TWY K OPEN", " DUE WIP", " REF A1234/26"],
    "restrictions": [["TWY J", "CLSD"], ["RWY 09/27", "CLSD"], ["TWY B", "CLSD DUE WIP"], ["STAND 12", "U/S"],
                     ["AREA R123", "ACT"]],
    "itemD": ["NONE", "D0800", "D1800"],
    "validities": list(VALIDITIES),
}


# The zero of each decimal-digit script (Unicode category Nd) the fuzzer writes digits in.
DIGIT_ZERO = {"arabicIndic": 0x0660, "extendedArabicIndic": 0x06F0, "devanagari": 0x0966, "bengali": 0x09E6, "thai": 0x0E50}


def _fuzz_digit(rng: Mulberry32, script: str) -> str:
    digit = rng.below(10)
    written = ("ascii" if rng.below(2) else "arabicIndic") if script == "mixed" else script
    return str(digit) if written == "ascii" else chr(DIGIT_ZERO[written] + digit)


def _fuzz_token(rng: Mulberry32) -> str:
    script = rng.pick(FUZZ["digitScripts"])
    groups = 1 + rng.below(3)
    token = rng.pick(FUZZ["leads"]) + rng.pick(FUZZ["letters"])
    for g in range(groups):
        if g > 0:
            token += rng.pick(FUZZ["separators"])
        for _ in range(1 + rng.below(6)):
            token += _fuzz_digit(rng, script)
    return token


def fuzz_case(rng: Mulberry32) -> dict[str, Any]:
    """One fuzz case: the body line, the same line without the fuzz segment (the canonical base), and where it sits."""
    item_d = rng.pick(FUZZ["itemD"])
    validity = rng.pick(FUZZ["validities"])
    subject, verb = rng.pick(FUZZ["restrictions"])
    placement = rng.pick(FUZZ["placements"])
    tail = rng.pick(FUZZ["tails"])
    prefix = rng.pick(FUZZ["prefixes"])
    suffix = rng.pick(FUZZ["suffixes"])
    token = _fuzz_token(rng)
    segment = f"{prefix}{token}{suffix.replace('#', _fuzz_token(rng), 1) if '#' in suffix else suffix}"
    if placement == "end":
        head, rest, base = f"{subject} {verb} ", f"{tail}.", f"{subject} {verb}{tail}."
    elif placement == "sentence":
        head, rest, base = f"{subject} {verb}. ", f"{tail}.", f"{subject} {verb}.{tail}." if tail else f"{subject} {verb}."
    elif placement == "before":
        head, rest, base = "", f" {subject} {verb}{tail}.", f"{subject} {verb}{tail}."
    elif placement == "middle":
        head, rest, base = f"{subject} ", f" {verb}{tail}.", f"{subject} {verb}{tail}."
    else:
        head, rest, base = f"{subject} {verb} (", f"){tail}.", f"{subject} {verb}{tail}."
    return {"itemD": item_d, "validity": validity, "line": f"{head}{segment}{rest}", "base": base,
            "segmentStart": len(head), "segmentEnd": len(head) + len(segment), "segment": segment}


def fuzz_cases(seed: int, count: int) -> Iterator[dict[str, Any]]:
    rng = Mulberry32(seed)
    for _ in range(count):
        yield fuzz_case(rng)


# ---- the independent class definitions a fuzz digit may be masked by (QA514 fuzz oracle) ----------------------------
_A = re.ASCII
_TEMPORAL_CONNECTIVE = re.compile(r"(?:^|[^A-Z0-9])(?:DURING|DRG|OUTSIDE|UNTIL|TILL|TIL|FROM|FM|BEFORE|BFR|AFTER|BTN|"
                                  r"BETWEEN|AT|BY|WEF|TO|THRU|THROUGH|SINCE)(?: (?:THE|A|AN))?:? ?[(+#.]? ?$", _A)
_RESTRICTION_BEFORE = re.compile(r"(?:^|[^A-Z])(?:CLSD|CLOSED|U/S|WIP|ACT|OPEN|AVBL|OPR|LTD|LIMITED|SUSPENDED|RESTRICTED|"
                                 r"PROHIBITED) $", _A)
_TIME_WORD = re.compile(r"^(?:H|HR|HRS|HOURS?|MIN|MINS|MINUTES?|SEC|SECS|UTC|GMT|Z|L|LT|LCL|LOCAL|AM|PM|DLY|DAILY|DAYS?|"
                        r"NIGHTS?|WEEKS?|MONTHS?|YEARS?|H24|HJ|HN|SR|SS|[A-Z]{3}DAYS?)$", _A)
_NOT_NOUN = re.compile(r"^(?:FROM|FM|TO|TIL|TILL|UNTIL|THRU|THROUGH|BTN|BETWEEN|AND|OR|DURING|DRG|AT|ON|BY|BEFORE|BFR|"
                       r"AFTER|SINCE|WEF|EFF|EV|EVERY|EACH|OUTSIDE|FOR|THE|A|AN|OF|IN|WITH|DUE|CLSD|CLOSED|U/S|WIP|ACT|"
                       r"OPEN|AVBL|OPR|DLY|DAILY|DAYS?|HR|HRS|H|MIN|UTC|LT|Z)$", _A)
_DESIGNATOR_KEYWORD = re.compile(
    r"^(?:RWY|RWYS|RY|RUNWAY|RUNWAYS|TWY|TWYS|TAXIWAY|TAXIWAYS|TXY|TXL|TL|STAND|STANDS|STD|STDS|PRKG|PARKING|GATE|GATES|"
    r"BAY|BAYS|APN|APRON|SPOT|SPOTS|HP|EXIT|LINK|LINKS|PSN|POS|CL|THR|THRESHOLD|SECTOR|SECTORS|ZONE|AREA|AREAS|"
    r"ORIENTATION|ALS|ALSF|MALSR|SALS|SSALR|ODALS|PAPI|VASIS?|REIL|REDL|RCLL|TDZL|HIRL|MIRL|LIRL|RTIL|ILS|LOC|GP|RVR|TMI|"
    r"CRANE|CRANES|NR|NO|NUMBER|CODE|SSR|SQUAWK|SQ|CHANNEL|CH|PAGE|PARA|PARAGRAPH|ITEM|PHASE|STAGE|SECTION|SEC|AIRAC|"
    r"CYCLE|VERSION|VER|EDITION|ED|AMDT|AMENDMENT|ISSUE|SERIAL|ID|IDENT|FLT|FLIGHT|PIER|HANGAR|BLOCK|BUILDING|BLDG|POINT|"
    r"WPT|SHEET|FIGURE|FIG|TABLE|ANNEX|DOC|ROUTE|RTE|AWY|AIRWAY|LANE|TRACK|AC|FAR|CFR|ARTICLE|ART|REGULATIONS?|RULES?|"
    r"ORDER|PARTS?|SUBPART|CHAPTER|CHAP|APPENDIX)\b", _A)


_MEASURE_OR_DESIGNATION = re.compile(
    r"^(?:(?:HGT|HEIGHT|ALT|ALTITUDE|ELEV|ELEVATION|AMSL|AGL|MSL|FT|NM|RADIAL|RDL|QDM|QDR|CRS|COURSE|TRK|TRACK|BRG|BEARING|"
    r"HDG|HEADING|FREQ|FREQUENCY|MHZ|KHZ|HF|VHF|UHF|CH|CHANNEL|VIS|VISIBILITY|RVR|MDA|MDH|DA|DH|OCA|OCH|IAS|TAS|KT|SPEED|"
    r"DIST|DISTANCE|LEN|LENGTH|WIDTH|RWY|RWYS|RUNWAY|THR|THRESHOLD|TWY|TAXIWAY|STAND|STANDS|GATE|CAT|PAGE|PARA|"
    r"PARAGRAPH|CHAPTER|SECTION|REF|AIP|AMDT|SUP|EDITION|SHEET|CHART|NR|NO|NUMBER|TEL|FAX)[ /.]*)+:? ?\d{1,5}"
    r"(?:\.\d{1,3})?(?:\(\d{1,5}(?:\.\d{1,3})?\))?[LRC]?$|^(?:NR|NO|NUMBER|PAGE|SHEET|CHART)\.? [A-Z]{1,3} \d{1,3}/\d{1,3}$"
    r"|^L\.R\. ?\d{3}$", _A)


_TIME_DESIGNATOR = re.compile(r"(?:Z|L|LT|LCL|UTC|GMT|H|T)", _A)
_VALID_CLOCK = re.compile(r"(?:(?:[01][0-9]|2[0-3])[0-5][0-9]|2400)", _A)


def _identifier_part(part: str) -> bool:
    match = re.match(r"([A-Z]+)([0-9]+)", part)
    return match is None or (not (_TIME_DESIGNATOR.fullmatch(match.group(1)) and _VALID_CLOCK.fullmatch(match.group(2)))
                             and re.fullmatch(r"[OI]+", match.group(1)) is None)


def _next_word(text: str, end: int) -> str:
    match = re.match(r" ?\(?([A-Z][A-Z0-9/]*)", text[end:], _A)
    return match.group(1) if match else ""


def _full(pattern: str, span: str) -> bool:
    return re.fullmatch(pattern, span, _A) is not None


def _not_governed(text: str, start: int) -> bool:
    return not _TEMPORAL_CONNECTIVE.search(text[:start])


FUZZ_CLASS_DEFINITIONS: dict[str, Callable[[str, str, int, int], bool]] = {
    # a VHF/UHF frequency by its band and decimals, never the object of a temporal connective
    "frequency": lambda span, text, start, end: _full(r"(?:1[0-3]\d|[23]\d\d)[.,]\d{1,3}", span) and _not_governed(text, start),
    # a runway end (01-36 and L/R/C), never the object of a temporal connective
    "runwayEnd": lambda span, text, start, end: _full(r"(?:0?[1-9]|[12]\d|3[0-6])[LRC](?:/(?:0?[1-9]|[12]\d|3[0-6])[LRC])*", span)
    and _not_governed(text, start),
    # digit, letter, digit or one/two digits and a letter that is never a time letter or a letter for a digit
    "locationIdentifier": lambda span, text, start, end: _full(r"\d[A-GJKMNP-Y]\d|\d{1,2}[BCEFGJKNQRTUVX]", span)
    and not _full(r"\d[HLZ]\d", span) and _not_governed(text, start),
    # a list label before a word that is not a time word, never after a restriction verb or a temporal connective
    "listNumber": lambda span, text, start, end: _full(r"\(\d{1,2}\)|\d{1,2}(?:\.\d{1,2}){0,3}(?:[.)]-?|-)|[1-9](?:\.\d{1,2}){1,3}|[1-9]", span)
    and not _RESTRICTION_BEFORE.search(text[:start]) and _not_governed(text, start)
    and (_full(r"\(\d{1,2}\)", span) or (len(_next_word(text, end)) >= 2 and not _TIME_WORD.search(_next_word(text, end)))),
    # a small number counting the noun after it, never after a restriction verb or a temporal connective
    "numberCount": lambda span, text, start, end: _full(r"\d{1,2}|\d{1,3}(?:ST|ND|RD|TH)", span) and text[end:end + 1] == " "
    and not _NOT_NOUN.search(_next_word(text, end)) and not _TIME_WORD.search(_next_word(text, end))
    and not _RESTRICTION_BEFORE.search(text[:start]) and _not_governed(text, start),
    # a small number labelling the noun before it, never followed by a time word or a range
    "numberLabel": lambda span, text, start, end: _full(
        r"[A-Z]{2,15}\)?[.:-]? ?(?:\(\d{1,2}[A-Z]?\)|\d(?:\.\d)?|\d{1,2}[A-Z]?(?:(?:, ?| AND | ?& ?)\d{1,2}[A-Z]?)*"
        r"|\d{1,2}[A-Z]?-\d{1,2}[A-Z]?|\d{1,2}[A-Z]?(?:[-/]\d{1,2}[A-Z]?){2,})", span)
    and not _NOT_NOUN.search(re.match(r"[A-Z]+", span).group(0)) and not _TIME_WORD.search(_next_word(text, end))
    and not re.match(r" ?(?:-|/|TO|AND|OR) ?\d", text[end:], _A),
    # a runway, taxiway, stand ... designator after its keyword
    "designator": lambda span, text, start, end: bool(_DESIGNATOR_KEYWORD.search(span))
    and not re.search(r"\d(?:Z|UTC|GMT|H|HRS?|LT|AM|PM)(?![A-Z])", span, _A),
    # a DME distance and altitude pair, never the object of a temporal connective
    "declaredDistance": lambda span, text, start, end: _full(r"\d{1,2}\.\d/\d{3,5}", span) and _not_governed(text, start),
    # an approach minimum and its visibility in brackets
    "minimaPair": lambda span, text, start, end: _full(r"\(\d{3,4}-\d\.\d\)", span),
    # minutes and seconds are intervals (David's decision), with the unit
    "minuteQuantity": lambda span, text, start, end: _full(r"\d{1,3}(?: ?(?:-|TO|AND|OR) ?\d{1,3})? ?-?(?:MIN|MINS|MINUTES?)", span),
    # a NOTAM reference with series letters and year
    "noticeReference": lambda span, text, start, end: _full(r"[A-Z]{1,4}\d{1,5}/(?:19|20)?\d{2}", span),
    # a fixed national telephone shape or a case number, whole
    "phoneFormat": lambda span, text, start, end: _full(
        r"(?:AT )?(?:\d{3}-\d{3}-\d{4}|0\d{3,4} \d{6}|\d{2}-\d{3}-\d{4}|0\d{1,3}-\d{6,8}|0\d-\d{4}-\d{4}|0\d \d{4} \d{4}"
        r"|04\d{2} \d{3} \d{3})", span),
    "caseNumber": lambda span, text, start, end: _full(r"\d{2}-\d{6}", span),
    "phone": lambda span, text, start, end: re.match(r"\(?\+ ?\d", span, _A) is not None,
    # QA514 G1: one or two digits and letters that are never a time letter or word, a letter for a digit, a unit or an
    # ordinal; never after a temporal connective unless a DME fix (4D), never a range side, never before a time word
    "digitLedIdentifier": lambda span, text, start, end: _full(r"\d{1,2}[A-GKMNP-Y][A-Z]{0,2}\d{0,2}", span)
    and not _full(r"\d{1,2}(?:ST|ND|RD|TH|AM|PM|HR|UTC|GMT|LT|MIN|SEC|DAY|WK|FT|NM|KM|KT|MB|DEG|DME)", span)
    and (_not_governed(text, start) or _full(r"\d{1,2}D", span))
    and not re.search(r"(?:^|[^A-Z])(?:FOR|MAX|WITHIN|WI|LASTING) $", text[:start], _A) and not _TIME_WORD.search(_next_word(text, end))
    and not re.match(r" ?(?:-|TO|UNTIL|THRU) ?\d", text[end:], _A),
    # QA514 G2: a number governed by a measurement or designation noun directly before it, or by a head after it
    "headedNumber": lambda span, text, start, end: (
        (_MEASURE_OR_DESIGNATION.search(span) is not None and not re.search(r"(?:^|\s)(?:\d{3,4}|\d{1,2}[.:]\d{2})(?:[LRC])?$", span, _A)
         and not _TIME_WORD.search(_next_word(text, end)))
        or _full(r"(?:0?[1-9]|[12]\d|3[0-6])[LRC]? (?:THR|THRESHOLD)|\d{2,3}[.,]\d{1,3}(?: ?(?:MHZ|KHZ))? (?:FREQ|FREQUENCY)"
                 r"|\d{1,2} (?:CFR|FAR|USC|CODE OF FEDERAL REGULATIONS|UNITED STATES CODE)|\d{1,3}(?:\.\d{1,2})?(?: ?NM)? TO [A-Z]{5}", span)),
    # QA514 G3: a label opening a clause ('(1)', a section number of three levels), a statute's bracketed sub-paragraphs
    "enumerationLabel": lambda span, text, start, end: (
        (_full(r"\(\d{1,2}\)|[1-9](?:\.\d{1,2}){2,3}", span) and re.search(r"(?:^|[.:;] ?)$", text[:start], _A) is not None)
        or _full(r"\d{1,6}\([A-Z]{1,3}\)(?:\([A-Z0-9]{1,3}\))*", span))
    and not re.match(r" ?(?:-|/|TO|AND|OR) ?\d", text[end:], _A) and not _TIME_WORD.search(_next_word(text, end)),
    # QA514 G3: a list label opening the body line (offset 0 of a single fuzz line)
    "lineEnumeration": lambda span, text, start, end: start == 0
    and _full(r"\(\d{1,2}\)|\d{1,2}[.)]|[1-9](?:\.\d{1,2}){1,3}", span)
    and not re.match(r"[0-9]", text[end:], _A) and not re.match(r" ?(?:-|/|TO|AND|OR) ?\d", text[end:], _A) and not _TIME_WORD.search(_next_word(text, end)),
    # QA514 G1: a letter-led glued alphanumeric is an identifier - never a time designator glued to a valid clock, never
    # letters for digits, and after a temporal connective never a four-digit group glued to letters
    "alphanumericDesignator": lambda span, text, start, end: re.match(r"[A-Z]", span) is not None and re.search(r"[0-9]", span) is not None
    and all(_identifier_part(part) for part in re.split(r"[-/]", span))
    and not (not _not_governed(text, start) and re.search(r"[A-Z]-?[0-9]{4}(?![0-9]|/(?:19|20)?[0-9]{2}(?![0-9]))", span) is not None),
    # a procedure named by its five-letter point, a number and a letter (OBOKA 3H, ATRIN-7E/7F)
    "procedureName": lambda span, text, start, end: _full(r"[A-Z]{5}(?: ?- ?| )?[0-9][A-Z](?:/[0-9][A-Z])*", span),
    # a latitude or longitude prefixed by its hemisphere (S DDMMSS, E DDDMMSS)
    "coordinates": lambda span, text, start, end: _full(r"(?:[NS][0-9]{6}|[EW][0-9]{7})(?:\.[0-9]{1,4})?", span),
    # QA514 G4: an e-mail address after AT, its mailbox holding a letter, its domain ending in a top-level domain
    "emailAddress": lambda span, text, start, end: _full(
        r"(?:AT )?[A-Z0-9._-]*[A-Z][A-Z0-9._-]*(?:@|\(AT\)| )[A-Z0-9-]+(?:\.[A-Z0-9-]+)*\.[A-Z]{2,4}", span),
}

_ITEM_D_RANGE = {"NONE": ["0000-2400", "0000-2359", "H24"], "D0800": ["0800-1000"], "D1800": ["1800-2000"]}


def restates_item_d(segment: str, item_d: str) -> bool:
    """The segment restates Item D exactly (or, with no Item D, the whole day: 24 HR, H24): its words are only range
    words."""
    text = re.sub(r"\b(?:FROM|FM|BTN|BETWEEN|DLY|DAILY|EVERY|EV)\b", " ", segment, flags=_A)
    text = re.sub(r"(\d{4}) ?(?:UTC|Z)\b", r"\1", text, flags=_A)
    text = re.sub(r" (?:TO|AND|TIL|TILL|UNTIL|THRU) ", "-", text, flags=_A)
    text = re.sub(r"^-|-$", "", re.sub(r"\s+", "", text))
    return ("H24" if re.fullmatch(r"24-?(?:HR|HRS|HOURS)|H24", text, _A) else text) in _ITEM_D_RANGE[item_d]


_KEYS = ("status", "stateAtReference", "minutesDelta", "outsideBy")


def fuzz_verdict(case: dict[str, Any], line: str, spans: list[dict[str, Any]], got: dict, canonical: dict) -> str | None:
    """The fuzz invariant for one decision. ``line`` is the body line as the grammar reads it (upper case), ``spans``
    the benign spans kept in it, ``got``/``canonical`` the decisions with and without the fuzz segment."""
    same = all(got.get(key) == canonical.get(key) for key in _KEYS)
    if canonical.get("status") == "outside_window" and canonical.get("outsideBy") == "validity":
        if got.get("status") == "outside_window" and got.get("outsideBy") == "validity":
            return None
        return "outside the validity, yet decided otherwise"
    if not same and got.get("status") != "review":
        return f"neither canonical nor a review ({got.get('status')})"
    start, end = case["segmentStart"], case["segmentEnd"]
    digits = [index for index in range(start, end) if line[index].isdecimal()]
    for span in spans:
        if not any(span["start"] <= index < span["end"] for index in digits):
            continue
        definition = FUZZ_CLASS_DEFINITIONS.get(span["class"])
        text = line[span["start"]:span["end"]]
        if definition is None or not definition(text, line, span["start"], span["end"]):
            return f'{span["class"]} masked "{text}" outside its stated definition'
    unmasked = any(not any(span["start"] <= index < span["end"] for span in spans) for index in digits)
    if unmasked and got.get("status") != "review" and not restates_item_d(line[start:end], case["itemD"]):
        return "an unmasked digit, yet not a review"
    return None
