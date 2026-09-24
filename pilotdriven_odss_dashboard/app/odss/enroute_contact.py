"""Early ATC / FIR calls - the concise, source-governed record (PDF side).

The dashboard rule is web/src/lib/enroute-contact.mjs; this is the same rule
in Python, pinned to it token for token by the app's
tests/fixtures/enroute-contact-vectors.json and by the genuine-source
fixtures under tests/fixtures/enroute-contact/. Read that file's header for
the boss's words (27 Jul, 30 Jul, 24 Sep 2026) and the non-inference contract.

ATC-RADIO-SOURCE-418 (24 Sep 2026). Release 418 admitted only FIR-headed
CPDLC / ADS-C notices and then asserted a blanket "lead times and frequencies
are not held" over the genuine SQ366 and SQ23 OFPs, whose pages print TIBA,
contact and voice instructions with frequencies and lead times. The parser
now holds every printed communication instruction under a FIR or airway-
segment heading (parser._parse_notam_procedure_records), and this
composition derives, from each uploaded source alone:
  association  the crossing a record belongs to - its FIR heading; an
               ICAO/NAME FIR pair its body prints; the FIR in effect at its
               segment's waypoints on the parsed route (the last boundary row
               before them); else the association is stated unresolved;
  conditions   the notice's own printed conditions against the OFP's own
               facts - the validity window against the crossing instant,
               overflight / aerodrome / FIR-exit scope against the route's
               boundary rows, the direction between two named FIRs against
               the order of their crossings, named route segments against
               the filed route, a printed level band against the planned
               level profile; temporary-purpose and similar markers stay
               unresolved;
  quotation    the scope-compatible instruction sentence, verbatim, with the
               source's own printed frequencies, lead and interval; the only
               arithmetic is a printed lead before a printed boundary ACTM;
  details      approved-library findings keep their details (action /
               frequency / backup / lead / notes) - none is approved today;
  repeats      a consecutive duplicate boundary row is a repeated row; a
               repeat after a different FIR is a re-entry.
No flight, FIR, notice, frequency or expected string is special-cased.

ATC-CONDITIONS-CLOCK-EXTRACTION-420 (24 Sep 2026, rule v3). The release-420
independent QA showed a valid date promoting the rest of a notice to "held":
  actions      every communication sentence of a notice is kept as an action
               with its own conditions; the headline is the directive sentence
               with printed values (frequency, lead, interval, logon address),
               never an introductory statement; the rest are exposed;
  subjects     an action's conditions come from its own subject's qualifiers
               or, when the sentence has no crew subject of its own
               ("NOTIFICATION SHOULD BE VIA CPDLC"), from the sentence that
               governs it ("FLIGHTS THAT EXPERIENCE OR SUSPECT GNSS
               INTERFERENCE ... MUST NOTIFY"); a departure / arrival aerodrome
               restriction is evaluated against this flight's own airports (a
               negative match is not applicable); every other qualifier - a
               trigger, an equipment or flight-rules prefix, a WHEN / IF
               clause, an "as requested by ATC" marker - is an explicit
               unresolved condition; nothing unparsed defaults to met;
  timing       one effective basis - the actual take-off when held, else the
               scheduled departure - gives the displayed crossing clocks AND
               every validity decision, and is named on each validity;
  extraction   the extraction rules the parser stamped on the analysis are
               compared with the value in service; an older extraction is
               stated, never presented as the current parser's.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

from .extraction_rules import EXTRACTION_RULES

ENROUTE_CONTACT_RULE = "enroute-contact-v5"

JAKARTA_AFN_NOTE = "CPDLC limited trial: pilot initiates AFN logon only when requested by ATC; address WIIF."
_JAKARTA_TOKENS = ("ADS-C/CPDLC", "REQUESTED BY ATC", "AFN LOGON", "ADDRESS FOR JAKARTA FIR IS WIIF")

# OCR / line-wrap splits joined for classification and evaluation only; every
# quotation keeps the source spelling. CALL SIGN is joined so that a bare CALL
# is an instruction and a call sign is not.
_OCR_JOINS = (
    ("CON TACT", "CONTACT"), ("BROAD CAST", "BROADCAST"), ("LOG ON", "LOGON"), ("LOG-ON", "LOGON"),
    ("TRANS MISSION", "TRANSMISSION"), ("FREQ UENCY", "FREQUENCY"), ("CALL SIGN", "CALLSIGN"), ("CALLSIGNS", "CALLSIGN"),
)
_UNIT = r"(?:ACC|ACCS|CTL|CONTROL|RADAR|RADIO|APP|APPROACH|TWR|TOWER|CENTER|CENTRE|ATC|ATS|FIR|INFORMATION|UNIT|SECTOR|CTR|OCC|ARTCC|ATSU)"
# A communication instruction, by its own printed verb and object: contact /
# CTC / call a unit or a frequency as an obligation or imperative (a state
# such as "in positive contact with" is not), establish or maintain contact,
# report a position, monitor a frequency; comply with TIBA, broadcast (as an
# obligation) or transmit; logon; CPDLC / ADS-C. A reference to TIBA
# procedures, a broadcast made by the ground, a phone number to call, a
# report "to ATC" of an occurrence or monitoring a selection are not.
_KIND_RULES = (
    ("contact_logon", re.compile(r"\bAFN LOGON\b|\bLOGON\b")),
    ("voice_contact", re.compile(
        r"\b(?:ESTABLISH(?:ED|ING)?|MAINTAIN(?:ING)?|MAKE|MAKING|REGAIN)\s+(?:RADIO\s+|TWO-WAY\s+|INITIAL\s+|VOICE\s+|DIRECT\s+)?(?:CONTACT|COMMUNICATIONS?)\b"
        r"|(?:^|[.;:]\s+|\b(?:SHALL|MUST|SHOULD|WILL|TO|IMMEDIATELY|THEN)\s+(?:[A-Z]+\s+)?)(?:CONTACT(?:ED|ING)?|CTC)\s+(?:THE\s+|WITH\s+)?(?:RELEVANT\s+|APPROPRIATE\s+|NEXT\s+|RESPECTIVE\s+)?(?:[A-Z][A-Z,/-]*\s+){0,4}?" + _UNIT + r"\b"
        r"|\b(?:SHALL|MUST|WILL|SHOULD|TO|AND)\s+CALL\s+(?:[A-Z][A-Z/-]*\s+){0,2}?(?:" + _UNIT + r"\b|ON\s+(?:FREQ(?:UENCY)?\s+)?\d{2,3}\.\d)"
        r"|\bREPORT(?:ING)?\s+(?:POSITION|PASSING|REACHING|ENTERING|CROSSING|ABEAM)\b"
        r"|\bMONITOR(?:ING)?\s+(?:CONTINUOUSLY\s+)?(?:THE\s+)?(?:VHF|UHF|HF|FREQ|FREQUENCY|GUARD|EMERGENCY|\d{2,3}\.\d)"
        r"|\b(?:HF|VHF|UHF)(?:\s+OR\s+(?:HF|VHF|UHF))?\s+MONITORING\b"
        r"|\b(?:REQUESTS?|POSITION REPORTS?|COMMUNICATIONS?|CALLS?)\s+(?:TO ATC\s+)?(?:SHOULD|SHALL|MUST|MAY|WILL|ARE TO|IS TO)\s+BE\s+(?:MADE|SENT|PASSED|TRANSMITTED|CONDUCTED)\s+(?:OVER|ON|VIA|BY)\s+(?:VHF|HF|UHF|CPDLC|SATCOM|RADIO|\d{2,3}\.\d)",
    )),
    ("tiba_broadcast", re.compile(
        r"\bCOMPLY WITH (?:THE )?TIBA\b|\bTIBA (?:FREQ(?:UENCY|UENCIES)?|BROADCASTS?|PROCEDURES? (?:FOR|ON|DEFINED|AS))\b|\bON (?:THE )?(?:RELEVANT |APPROPRIATE )?TIBA\b"
        r"|\b(?:SHALL|MUST|WILL|SHOULD|ARE REQUIRED TO|IS REQUIRED TO|ARE TO|IS TO|TO)\s+(?:[A-Z-]+\s+){0,3}?BROADCAST(?:ING)?\b|\bBROADCAST(?:ING)? (?:THEIR |YOUR )?INTENTIONS\b"
        r"|\bTRANSMISSIONS? SHALL\b",
    )),
    ("datalink_other", re.compile(r"\bCPDLC\b|\bADS-C\b")),
)
_KIND_RANK = {"voice_contact": 0, "tiba_broadcast": 1, "contact_logon": 2, "datalink_other": 3}
_STATE_RANK = {"conditions_held": 0, "conditions_unresolved": 1, "not_applicable": 2}
# A sentence ends at "." or ";" after a word of two or more characters; a list
# marker ("A.", "1.") and a unit abbreviation ("MIN.", "HRS.") do not end one.
_SENTENCE_SPLIT = re.compile(r"(?<=\S\S[.;])\s+")
_ABBREVIATION = re.compile(r"\b(?:MIN|MINS|HR|HRS|NM|FT|SEC|SECS|KT|KTS|DEG|APPROX)\.$")
_FREQUENCY = re.compile(r"\b\d{2,3}\.\d{1,3} ?MHZ\b")
_LEAD_NOUN = r"(?:FIR|FIRS|BOUNDARY|POINT|ENTRY|ENTRANCE|TAKEOFF|TAKE-OFF|DEPARTURE|AIRSPACE|SECTOR|TMA|CTA|UTA|CROSSING)"
# The lead as printed: an amount, up to two words, a relation word and the
# anchor noun phrase it names (the FIR, the boundary point, the entry, the
# take-off), never a following proper name or clause.
_LEAD = re.compile(
    r"\b((?:(?:NOT LESS THAN|NOT LATER THAN|NOT EARLIER THAN|AT LEAST|WI|WITHIN|MINIMUM|MIN|MAXIMUM|MAX|APPROX(?:IMATELY)?|BETWEEN \d{1,3} AND) )?\d{1,3} ?MIN(?:S|UTES)?\.?"
    r"(?: [A-Z-]+){0,2}? (?:PRIOR|BEFORE|TO THE ENTRANCE|OF ENTRY|AHEAD OF|IN ADVANCE OF)"
    r"(?:(?: [A-Z][A-Z'-]*){0,5}? " + _LEAD_NOUN + r"(?: " + _LEAD_NOUN + r")*)?)",
)
_INTERVAL = re.compile(r"\bEVERY \d{1,3} ?MIN(?:S|UTES)?\b")
_VALIDITY = re.compile(r"^(\d{2})-([A-Z]{3})-(\d{2}) (\d{4})\s*-\s*(?:(\d{2})-([A-Z]{3})-(\d{2}) (\d{4})(?:\s*EST)?|(UFN|PERM))\s*$")
_MONTHS = {m: i + 1 for i, m in enumerate(("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"))}
_NAME = r"[A-Z][A-Z-]*(?: [A-Z][A-Z-]*)*?"
_NAMES = _NAME + r"(?:(?:, | AND | OR |, AND |, OR )" + _NAME + r")*?"
# "FM A FIR TO B FIR" / "ENTERING B AND C FIRS FM A FIR": the notice's own direction between named FIRs.
_DIRECTIONS = (
    re.compile(r"\bF(?:RO)?M (?:THE )?(?P<from>" + _NAMES + r") FIRS? (?:TO|INTO) (?:THE )?(?P<to>" + _NAMES + r") FIRS?\b"),
    re.compile(r"\bENTERING (?:THE )?(?P<to>" + _NAMES + r") FIRS? F(?:RO)?M (?:THE )?(?P<from>" + _NAMES + r") FIRS?\b"),
)
_BODY_FIR = re.compile(r"\b([A-Z]{4})/([A-Z][A-Z -]*?) FIR\b")
_ROUTE_LIST = re.compile(r"\b([A-Z]{5})-([A-Z]{1,2}\d{1,3})-([A-Z]{5})(?:-([A-Z]{1,2}\d{1,3})-([A-Z]{5}))?\s*(?:\(FL(\d{3})-FL(\d{3})\))?")
_ROUTE_PAIR = re.compile(r"(?:\(|, )([A-Z]{1,2}\d{1,3}) ([A-Z]{5})(?=[,)])")
# A printed contact table row: airway, transfer point, the unit, its primary and secondary frequency.
_ROUTE_FREQ_ROW = re.compile(r"\b([A-Z]{1,2}\d{1,3}) ([A-Z]{5}) ((?:[A-Z]+ ){1,4}?)(\d{2,3}\.\d{1,3} MHZ)(?: (\d{2,3}\.\d{1,3} MHZ))?")
# Printed logon addresses: "USE LOGON ADDRESS PAZN", "THE AFN LOGON ADDRESS FOR JAKARTA FIR IS WIIF", "LOGON TO KZAK".
_ADDRESS = re.compile(r"\bLOGON ADDRESS(?:ES)?(?: FOR [A-Z][A-Z ]*? FIR)?(?: IS| ARE)? ([A-Z]{4})\b|\bLOG ?ON TO ([A-Z]{4})\b")
_ADDRESS_STOPWORDS = {"WHEN", "WITH", "THAT", "THIS", "FROM", "INTO", "OVER", "ONLY", "ALSO", "THEN", "THEM", "THEY", "WILL", "BASED", "UPON", "EACH", "BOTH", "SAME", "MUST", "SHALL"}
# A sentence's own crew subject, its qualifiers and the modal that ends them:
# "IFR AFCT FLT PLANNED TO DEP CYMM/OILSANDS UNABLE TO CTC ... SHOULD CTC ...".
_LIST_MARKER = r"(?:\(?[A-Z]\)?[.)]\s+|\d{1,2}[.)]\s+|-\s*)?"
_SUBJECT_PREFIX = r"(?:(?:ALL|ANY|EVERY|IFR|VFR|MILITARY|CIVIL|NON-RVSM|RVSM|FANS[- ]?1/A|DATA[- ]?LINK\s*-?\s*EQUIPPED|ADS-[BC][- ]EQUIPPED|APPROPRIATELY EQUIPPED|SUITABLY EQUIPPED|EQUIPPED)\s+)*"
_SUBJECT_NOUN = r"(?:FLIGHT CREWS?|THE PILOTS?|THE CREWS?|FLIGHTS?|FLTS?|ACFT|AIRCRAFT|AFCT|TFC|TRAFFIC|OVERFLIGHTS?|PILOTS?|CREWS?|OPERATORS?|AIRLINES?|PERSONS?|USERS?)(?:\s+(?:FLT|FLIGHTS?|OPERATIONS?|OPERATORS?))?"
_SUBJECT = re.compile(r"^" + _LIST_MARKER + r"(?P<prefix>" + _SUBJECT_PREFIX + r")(?P<noun>" + _SUBJECT_NOUN + r")\b(?P<qualifier>.*?)\s*\b(?P<modal>SHALL|MUST|SHOULD|WILL|MAY|CAN|ARE|IS|NEED|HAVE|HAS)\b")
_IMPERATIVE = re.compile(r"^" + _LIST_MARKER + r"(?:USE|SELECT|CONTACT|CTC|CALL|MONITOR|LOGON|LOG ON|BROADCAST|REPORT|MAINTAIN|ESTABLISH|COMPLY|SQUAWK|TRANSMIT|NOTIFY|REFER|ADVISE|REQUEST|EXPECT|FILE|OPERATE|AVOID|DO NOT|CONTINUE|PROCEED|REMAIN)\b")
_LEADING_CLAUSE = re.compile(r"^" + _LIST_MARKER + r"(?P<clause>(?:WHEN|IF|WHILE|UNLESS|IN CASE OF|IN THE EVENT OF|AFTER|BEFORE|DURING|PROVIDED|WHERE)\b[^,]{3,120}),\s*")
# "PROVIDED" is a condition only as a conjunction ("PROVIDED THAT ...", "PROVIDED THE CREW ..."), never the passive
# participle of a service ("WILL BE PROVIDED BY TOKYO CONTROL", "PROVIDED TO THE BORDER").
_TRAILING_CLAUSE = re.compile(r"\s\b(?P<clause>(?:WHEN|IF|WHILE|UNLESS|WHERE|EXCEPT WHEN|ONLY WHEN|ONLY IF|PROVIDED(?!\s+(?:BY|TO|FOR|ON|VIA|FROM|WITH|AT|IN|UNTIL|THROUGH)\b))\b.{3,200}?)(?:[.;:]|$)")
# A sentence whose subject is not the crew but has one of its own ("THE PROCEDURES IN ICAO DOC 4444 ... APPLY",
# "ARTCC AUTOMATION WILL PROVIDE ...", "THE SERVICE WILL BE PROVIDED ..."): the shortest noun phrase before its first
# modal / finite verb. It keeps its own clauses and borrows nothing (F1 of the release-422 independent QA, 24 Sep 2026).
_OTHER_SUBJECT = re.compile(r"^" + _LIST_MARKER + r"(?P<noun>(?:THE\s+|AN?\s+)?[A-Z0-9][A-Z0-9/().'-]*(?:\s+[A-Z0-9][A-Z0-9/().'-]*){0,9}?)\s+\b(?P<modal>SHALL|MUST|SHOULD|WILL|MAY|CAN|ARE|IS|NEED|HAVE|HAS|APPLY|APPLIES|DOES|DO)\b")
# A subject naming the crew's own communication act continues the governing crew sentence ("FLIGHTS THAT EXPERIENCE
# GNSS INTERFERENCE MUST NOTIFY ATC. NOTIFICATION SHOULD BE VIA CPDLC ..."): it inherits that sentence's qualifiers.
# The crew's act as a sentence subject before a modal ("CONTACT SHALL BE ATTEMPTED ...", "LOGON SHALL BE COMPLETED
# ...", "REQUESTS TO ATC SHOULD BE MADE ..."): a noun, not an instruction, although the word can also open an imperative.
_CREW_ACT_SUBJECT = re.compile(r"^" + _LIST_MARKER + r"(?P<noun>(?:THE\s+)?(?:NOTIFICATIONS?|CONTACTS?|LOG-?ONS?|POSITION REPORTS?|REPORTS?|REQUESTS?|CALLS?|BROADCASTS?|MESSAGES?|TRANSMISSIONS?|COMMUNICATIONS?|READ-?BACKS?)(?:\s+(?:TO|WITH|OF|FOR|VIA|ON)\s+[A-Z0-9/-]+)?)\s+\b(?:SHALL|MUST|SHOULD|WILL|MAY|CAN|ARE|IS|NEED|HAVE|HAS)\b")
_CREW_ACT_NOUN = re.compile(r"^(?:THE\s+)?(?:NOTIFICATIONS?|CONTACTS?|LOG-?ONS?|POSITION REPORTS?|REPORTS?|REQUESTS?|CALLS?|BROADCASTS?|MESSAGES?|TRANSMISSIONS?|COMMUNICATIONS?|READ-?BACKS?)\b")
# A qualification of the aircraft population anywhere in a sentence's body (F1 of the release-424 independent QA,
# 24 Sep 2026): a crew noun introduced by a population connector and followed by a restrictive modifier - "BTN ADS-B
# EQUIPPED ACFT THAT ARE CORRELATED WITH CPL ...", "FOR ACFT DEPARTING RJTT", "TO FLIGHTS UNABLE TO LOGON". It is
# evaluated exactly like a subject qualifier; an object mention without a modifier ("REPORT ANY ACFT") is not one.
_POPULATION_MODIFIER = r"(?:THAT|WHICH|WHO|EQUIPPED|CORRELATED|OPERATING|OPERATED|PLANNED|PLANNING|FLYING|ENTERING|LEAVING|DEPARTING|ARRIVING|TRANSITING|OVERFLYING|CROSSING|HAVING|CAPABLE|ABLE|UNABLE|NOT|IN POSITIVE|IN CONTACT|IN CTC|WITH|WITHOUT|USING|CONDUCTING|MAINTAINING|EXPERIENCING|LOGGED|BOUND|INBOUND|OUTBOUND|REQUESTING|INTENDING|EXPECTING|CLEARED|APPROACHING|HOLDING|PROCEEDING|ROUTING|CARRYING)"
_POPULATION = re.compile(
    r"\b(?:BTN|BETWEEN|FOR|TO|OF|BY|APPLICABLE TO|APPLIES TO|APPLY TO|ONLY (?:TO|FOR)|AVAILABLE TO|PROVIDED TO)\s+"
    r"(?:(?:ALL|ANY|EVERY|THE|THOSE|SUCH)\s+)?(?P<prefix>" + _SUBJECT_PREFIX + r")(?P<noun>" + _SUBJECT_NOUN + r")\s+"
    r"(?P<modifier>" + _POPULATION_MODIFIER + r"\b[^.;]*?)(?=\s+\b(?:SHALL|MUST|SHOULD|WILL|MAY|ARE TO|IS TO)\b|[.;]|$)")
_RELATIVE_OPENING = re.compile(r"^(?:THAT|WHICH|WHO)\s+(?:ARE|IS|WERE|WAS)?\s*")
# Who acts. A sentence directing the crew (a crew subject with a modal, an imperative, a continuation of one) is a
# crew action. A sentence whose actor is ATC - a service, a separation, a procedure applied or provided, a centre or
# its automation - is an ATC provision: still held with its conditions, never presented as a required crew call.
_CREW_DIRECTIVE = re.compile(r"\b(?:" + _SUBJECT_NOUN + r")\b[^.;]*?\b(?:SHALL|MUST|SHOULD|ARE (?:REQUESTED|REQUIRED|EXPECTED) TO|IS (?:REQUESTED|REQUIRED|EXPECTED) TO|ARE TO|IS TO|NEED TO)\b")
# The HEAD of the subject noun phrase (its last word before the first preposition) names the actor: "OPPORTUNITY BASED
# APPLICATION OF ..." → APPLICATION, "ARTCC AUTOMATION" → AUTOMATION, "THE CALL SIGN TO BE USED ..." → SIGN (the crew's).
_HEAD_STOP = re.compile(r"\b(?:OF|ON|IN|FOR|TO|WITH|AT|BY|FROM|WITHIN|BETWEEN|BTN|VIA|UNDER|OVER)\b")
_ATC_HEADS = {"ATC", "ATS", "ACC", "ARTCC", "ATSU", "CENTRE", "CENTER", "CONTROL", "CTL", "AUTOMATION", "SERVICE", "SERVICES",
              "SEPARATION", "APPLICATION", "PROVISION", "SURVEILLANCE", "RADAR", "UNIT", "STATION", "FACILITY", "TOWER", "APP",
              "APPROACH", "FIS", "AFTN"}
# A service applied or provided (the strict passive), or an agent phrase naming ATC ("... ENDEAVOURED BY ATC", "... BY THE ATSU").
_SERVICE_PASSIVE = re.compile(r"\b(?:SHALL|WILL|MAY|IS|ARE)\s+BE\s+(?:APPLIED|PROVIDED|AVAILABLE|OFFERED|IMPLEMENTED|CONDUCTED|ESTABLISHED|MAINTAINED|EXERCISED|ENDEAVOURED)\b|\bIS\s+(?:AVAILABLE|PROVIDED)\b")
_ATC_AGENT = re.compile(r"\bBY (?:THE )?(?:ATC|ATS|ACC|ARTCC|ATSU|GROUND SYSTEM|(?:[A-Z]+ ){0,2}(?:CENTRE|CENTER|CONTROL|CTL|OCEANIC|RADIO|APPROACH|TOWER))\b")
_DIRECTIVE = re.compile(r"\b(?:SHALL|MUST|SHOULD|WILL|MAY|ARE REQUESTED TO|IS REQUESTED TO|ARE REQUIRED TO|IS REQUIRED TO|ARE TO|IS TO|NEED TO|EXPECTED TO)\b")
# Aerodrome restrictions inside a qualifier: "PLANNED TO DEP CYMM/OILSANDS", "ARR KJFK", "OPERATING TO/FROM WSSS".
_AIRPORT_CONDITION = re.compile(r"\b(?P<kind>DEP(?:ARTING|ARTURE)?(?: FROM)?|ARR(?:IVING|IVAL)?(?: AT| TO)?|LANDING AT|OPERATING (?:TO/FROM|TO OR FROM|TO|FROM|AT)|TO OR FROM|BOUND FOR)\s+(?P<icao>[A-Z]{4})\b(?:/[A-Z-]+)?")
_ICAO_STOPWORDS = {"FROM", "WITH", "THAT", "THIS", "INTO", "OVER", "WHEN", "ONLY", "ALSO", "THEN", "THEM", "THEY", "WILL", "SHALL", "MUST", "AREA", "ZONE", "SAME", "EACH", "BOTH", "NEXT", "LAST", "FIRS", "AIRP"}
# The scope / direction qualifiers other rules already evaluate: a qualifier made only of these adds nothing.
_EVALUATED_QUALIFIER = re.compile(
    r"^(?:(?:DEPARTING|LEAVING|ENTERING|TRANSITING|OPERATING (?:IN|WITHIN)|WITHIN|IN|OVERFLYING)\s+(?:THE\s+)?(?:[A-Z][A-Z-]*\s+){0,4}?FIRS?"
    r"|FLW\s+F(?:RO)?M\s+.+?\s+FIRS?\s+(?:TO|INTO)\s+.+?\s+FIRS?(?:\s+\(.*\))?"
    r"|ENTERING\s+.+?\s+FIRS?\s+F(?:RO)?M\s+.+?\s+FIRS?"
    r"|ARRIVING OR DEPARTING(?: FROM)? AERODROMES(?: IN (?:THE )?[A-Z]+ FIR)?"
    r"|DEPARTING(?: FROM)? AERODROMES(?: IN (?:THE )?[A-Z]+ FIR)?)$"
)
_EQUIPMENT_PREFIX = re.compile(r"\b(?:FANS[- ]?1/A|DATA[- ]?LINK\s*-?\s*EQUIPPED|ADS-[BC][- ]EQUIPPED|APPROPRIATELY EQUIPPED|SUITABLY EQUIPPED|EQUIPPED)\b")
_RULES_PREFIX = re.compile(r"\b(?:IFR|VFR)\b")
_ATC_REQUEST = re.compile(r"\b(?:AS|WHEN|IF|WHERE) (?:SO )?REQUESTED BY ATC\b|\bON (?:ATC |CONTROLLER )?REQUEST\b|\bAT (?:ATC|CONTROLLER)(?:'S)? DISCRETION\b|\b(?:WHEN|IF|AS|UNLESS OTHERWISE) INSTRUCTED(?: BY ATC)?\b")
_OVERFLIGHT = re.compile(r"\bOVERFLIGHTS?\b|\bOVERFLYING\b|\bTRANSIT(?:ING)?\b")
_AERODROME = re.compile(r"\bAERODROMES?\b|\bTAKE-?OFF\b|\bLANDING\b|\bARRIVAL AND DEPARTURE\b|\bARRIVING OR DEPARTING\b|\bAPPROACH\b")
_FIR_EXIT = re.compile(r"\bDEPARTING (?:THE )?(?:[A-Z]+ )?FIR\b|\bLEAVING (?:THE )?(?:[A-Z]+ )?FIR\b|\bNEXT FIR\b")
_FIR_ENTRY = re.compile(r"\bENTERING\b|\bENTRY\b|\bENTRANCE\b")
_UNRESOLVED = re.compile(r"\bTEMPORARY PURPOSE\b|\bAS REQUIRED\b|\bUNLESS OTHERWISE\b|\bSUBJECT TO\b|\bWHEN INSTRUCTED\b")

STATE_SENTENCES = {
    "no_fir_rows_held": "No FIR boundary row is held in the parsed OFP; early-contact requirements are not established from this source.",
    "no_procedure_held": "No early-contact requirement is held in this OFP's FIR notices or in an approved reference; lead times and frequencies are not held and are not inferred from crossing times.",
}
NO_ALLOCATION_SENTENCE = "No slot-control allocation is printed in this OFP."


def _normalise(value: Any) -> str:
    return " ".join(str(value if value is not None else "").split())


def _integer(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def actm_text(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def classify_text(text: Any) -> str:
    """Upper-cased, whitespace-collapsed, OCR / wrap splits joined - for classification and evaluation, never for a quotation."""
    upper = _normalise(text).upper()
    for split, joined in _OCR_JOINS:
        upper = upper.replace(split, joined)
    return upper


def procedure_kind(text: Any) -> str | None:
    """The notice's own instruction decides the kind; its FIR or region never does. None: not a communication instruction."""
    upper = classify_text(text)
    for kind, pattern in _KIND_RULES:
        if pattern.search(upper):
            return kind
    return None


def sentences(text: Any) -> list[str]:
    clean = _normalise(text)
    if not clean:
        return []
    parts: list[str] = []
    for fragment in _SENTENCE_SPLIT.split(clean):
        if parts and _ABBREVIATION.search(parts[-1]):
            parts[-1] = f"{parts[-1]} {fragment}"
        else:
            parts.append(fragment)
    return [part.strip() for part in parts if part.strip()]


def contact_instruction(text: Any) -> str:
    """The first printed sentence carrying a communication instruction (a verbatim substring of the source)."""
    parts = sentences(text)
    if not parts:
        return ""
    return next((s for s in parts if procedure_kind(s)), parts[0])


def shorten(text: Any, limit: int = 200) -> str:
    """A whole-word prefix of at most ``limit`` characters, "…" when cut."""
    clean = _normalise(text)
    if len(clean) <= limit:
        return clean
    cut = clean[: limit - 1]
    space = cut.rfind(" ")
    return (cut[:space] if space > 40 else cut).strip() + "…"


def _governed_note(record: dict[str, Any]) -> str | None:
    heading = _normalise(record.get("heading")).upper()
    text = _normalise(record.get("text")).upper()
    if "JAKARTA FIR" in heading and all(token in text for token in _JAKARTA_TOKENS):
        return JAKARTA_AFN_NOTE
    return None


def _page_range(pages: list[int]) -> str:
    """His provenance style: "p12"; a contiguous run "pp8-14"; runs listed "p67, p85, pp88-89"."""
    runs: list[list[int]] = []
    for page in pages:
        if runs and page == runs[-1][-1] + 1:
            runs[-1].append(page)
        else:
            runs.append([page])
    return ", ".join(f"pp{run[0]}-{run[-1]}" if len(run) > 1 else f"p{run[0]}" for run in runs)


def _utc(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _hhmm_z(value: datetime | None) -> str | None:
    return f"{value:%H%M}Z" if value else None


def validity_window(validity: Any) -> tuple[datetime | None, datetime | None] | None:
    """The printed VALID window as UTC instants; an open end (UFN / PERM) is None; unreadable text is None."""
    match = _VALIDITY.match(_normalise(validity).upper())
    if not match:
        return None

    def stamp(day: str, mon: str, year: str, hhmm: str) -> datetime | None:
        month = _MONTHS.get(mon)
        if not month:
            return None
        try:
            return datetime(2000 + int(year), month, int(day), int(hhmm[:2]), int(hhmm[2:]), tzinfo=timezone.utc)
        except ValueError:
            return None

    start = stamp(match.group(1), match.group(2), match.group(3), match.group(4))
    if start is None:
        return None
    if match.group(9):
        return start, None
    end = stamp(match.group(5), match.group(6), match.group(7), match.group(8))
    return (start, end) if end is not None else None


# ---------------------------------------------------------------- the route the OFP prints


def _route(flight: dict[str, Any]) -> dict[str, Any]:
    names: list[str] = []
    fir_in_effect: list[str | None] = []
    current: str | None = None
    for waypoint in flight.get("route_waypoints") or []:
        if not isinstance(waypoint, dict):
            continue
        boundary = _normalise(waypoint.get("fir_boundary")).upper() or None
        if boundary:
            current = boundary
        names.append(_normalise(waypoint.get("name")).upper().lstrip("-"))
        fir_in_effect.append(current)
    profile: list[tuple[str, int]] = []
    tokens = [t for t in _normalise(flight.get("planned_level_profile")).upper().split("/") if t]
    for index in range(0, len(tokens) - 1, 2):
        if tokens[index + 1].isdigit():
            profile.append((tokens[index], int(tokens[index + 1])))
    return {"names": names, "fir_in_effect": fir_in_effect, "profile": profile}


def _planned_level_at(route: dict[str, Any], waypoint: str) -> int | None:
    """The FL in effect at a route waypoint: the last profile step at or before it in route order (the departure step first)."""
    if not route["profile"] or waypoint not in route["names"]:
        return None
    target = route["names"].index(waypoint)
    level = route["profile"][0][1]
    for name, flight_level in route["profile"][1:]:
        if name in route["names"] and route["names"].index(name) <= target:
            level = flight_level
    return level


def _fir_names(flight: dict[str, Any], records: list[dict[str, Any]]) -> dict[str, str]:
    """ICAO -> name from the OFP's own FIR headings and from ICAO/NAME FIR pairs the notices print."""
    names: dict[str, str] = {}
    held = flight.get("notam_fir_names")
    if isinstance(held, dict):
        for icao, name in held.items():
            if isinstance(icao, str) and isinstance(name, str) and len(icao) == 4:
                names[icao.upper()] = _normalise(name).upper()
    for record in records:
        match = re.match(r"^([A-Z]{4}) (.+?) FIR$", classify_text(record.get("heading")))
        if match:
            names.setdefault(match.group(1), match.group(2).strip())
        for icao, name in _BODY_FIR.findall(classify_text(record.get("text"))):
            names.setdefault(icao, name.strip())
    return names


# ---------------------------------------------------------------- crossings


def _clock(takeoff: datetime | None, minutes: int) -> tuple[str | None, str]:
    """HHMMZ and the day rollover ("D+1") of take-off + ACTM; nothing without an actual take-off (never a guessed clock)."""
    if takeoff is None:
        return None, ""
    instant = takeoff + timedelta(minutes=minutes)
    days = (instant.date() - takeoff.date()).days
    return f"{instant:%H%M}Z", f"D+{days}" if days > 0 else ""


def _crossings(flight: dict[str, Any], takeoff: datetime | None = None) -> list[dict[str, Any]]:
    crossings: list[dict[str, Any]] = []
    seen: set[str] = set()
    previous: str | None = None
    for waypoint in flight.get("route_waypoints") or []:
        if not isinstance(waypoint, dict):
            continue
        fir = _normalise(waypoint.get("fir_boundary")).upper()
        minutes = _integer(waypoint.get("actm_minutes"))
        if not fir or minutes is None:
            continue
        repeated = fir == previous
        utc, day = _clock(takeoff, minutes)
        crossings.append({
            "sequence": len(crossings) + 1,
            "fir": fir,
            "actm": actm_text(minutes),
            "actm_minutes": minutes,
            "source_page": _integer(waypoint.get("source_page")),
            "reentry": fir in seen and not repeated,
            "repeated": repeated,
            "utc": utc,
            "day": day,
        })
        seen.add(fir)
        previous = fir
    return crossings


def _relation(crossings: list[dict[str, Any]], fir: str) -> str:
    """overflight: the route enters the FIR and later crosses into another; arrival: it is the last FIR entered; else unresolved."""
    entries = [row for row in crossings if row["fir"] == fir]
    if not entries:
        return "unresolved"
    if any(row["sequence"] > entries[0]["sequence"] and row["fir"] != fir for row in crossings):
        return "overflight"
    return "arrival" if crossings[-1]["fir"] == fir else "unresolved"


def _next_fir(crossings: list[dict[str, Any]], fir: str) -> dict[str, Any] | None:
    entries = [row for row in crossings if row["fir"] == fir]
    if not entries:
        return None
    for row in crossings:
        if row["sequence"] > entries[0]["sequence"] and row["fir"] != fir:
            return {"fir": row["fir"], "actm": row["actm"]}
    return None


# ---------------------------------------------------------------- one notice against the OFP


def sentence_scope(sentence: Any) -> str:
    upper = classify_text(sentence)
    if _OVERFLIGHT.search(upper):
        return "overflight"
    if _FIR_EXIT.search(upper):
        return "fir_exit"
    if _AERODROME.search(upper):
        return "aerodrome"
    if _FIR_ENTRY.search(upper):
        return "fir_entry"
    return "unscoped"


def _scope_compatible(scope: str, relation: str) -> bool:
    if scope in ("unscoped", "fir_entry"):
        return True
    if scope in ("overflight", "fir_exit"):
        return relation == "overflight"
    return relation == "arrival"


def printed_details(sentence: Any) -> dict[str, Any]:
    """The frequencies, lead, interval and logon addresses a sentence prints, in the source's own words."""
    upper = classify_text(sentence)
    frequencies: list[str] = []
    for match in _FREQUENCY.findall(upper):
        if match not in frequencies:
            frequencies.append(match)
    lead = _LEAD.search(upper)
    interval = _INTERVAL.search(upper)
    addresses: list[str] = []
    for match in _ADDRESS.finditer(upper):
        address = match.group(1) or match.group(2)
        if address and address not in _ADDRESS_STOPWORDS and address not in addresses:
            addresses.append(address)
    return {"frequencies": frequencies, "lead": lead.group(1).strip() if lead else None, "interval": interval.group(0) if interval else None, "addresses": addresses}


def _has_values(details: dict[str, Any]) -> bool:
    return bool(details.get("frequencies") or details.get("lead") or details.get("interval") or details.get("addresses"))


def _lead_minutes(lead: str | None) -> int | None:
    """The latest lead the phrase allows: its smallest printed amount ("BETWEEN 15 AND 30 MINUTES" -> 15)."""
    amounts = [int(n) for n in re.findall(r"\b(\d{1,3})\b", lead or "")]
    return min(amounts) if amounts else None


def _route_tokens(text: str) -> list[dict[str, Any]]:
    """Waypoint / airway tokens the notice prints, each with any level band printed beside it."""
    upper = classify_text(text)
    tokens: list[dict[str, Any]] = []
    for match in _ROUTE_LIST.finditer(upper):
        band = (int(match.group(6)), int(match.group(7))) if match.group(6) else None
        pairs = ((match.group(1), match.group(2)), (match.group(3), match.group(2)), (match.group(3), match.group(4)), (match.group(5), match.group(4)))
        for waypoint, airway in pairs:
            if waypoint and airway:
                tokens.append({"waypoint": waypoint, "airway": airway, "band": band, "text": match.group(0).strip()})
    for airway, waypoint in _ROUTE_PAIR.findall(upper):
        tokens.append({"waypoint": waypoint, "airway": airway, "band": None, "text": f"{airway} {waypoint}"})
    for airway, waypoint, unit, primary, secondary in _ROUTE_FREQ_ROW.findall(upper):
        frequencies = [f for f in (primary, secondary) if f]
        tokens.append({"waypoint": waypoint, "airway": airway, "band": None, "frequencies": frequencies,
                       "text": f"{airway} {waypoint} {unit.strip()} {' '.join(frequencies)}"})
    return tokens


def _resolve_names(printed: str, names: dict[str, str]) -> list[tuple[str, str | None]]:
    """The FIR names a direction phrase lists, each with the ICAO the OFP's own headings or bodies give it."""
    by_name = {name: icao for icao, name in names.items()}
    return [(name, by_name.get(name)) for name in re.split(r", AND | AND |, OR | OR |, ", printed.strip()) if name.strip()]


# ---- a sentence's subject and the conditions it carries


def _subject_of(sentence: str) -> dict[str, Any]:
    """What a sentence says about who acts, and the clauses it carries itself.

    kind "stated": a crew subject ("IFR AFCT FLT PLANNED TO DEP CYMM/OILSANDS UNABLE TO CTC ... SHOULD"), with its
    prefix and qualifier; "imperative": the crew addressed directly ("USE LOGON ADDRESS ..."); "other": a subject of its
    own that is not the crew ("THE PROCEDURES ... APPLY", "ARTCC AUTOMATION WILL PROVIDE"); "fragment": no subject at
    all. A sentence's own leading clause always belongs to it. Only a continuation - a fragment, or an "other" subject
    naming the crew's own communication act - takes the governing crew sentence's qualifiers (release-422 QA, F1).
    """
    upper = classify_text(sentence)
    leading = _LEADING_CLAUSE.match(upper)
    body = upper[leading.end():] if leading else upper
    clause = leading.group("clause").strip() if leading else None
    match = _SUBJECT.match(body)
    if match:
        return {"kind": "stated", "prefix": match.group("prefix").strip(), "qualifier": match.group("qualifier").strip(), "leading": clause, "continuation": False}
    act = _CREW_ACT_SUBJECT.match(body)
    if act:
        return {"kind": "other", "prefix": "", "qualifier": "", "leading": clause, "noun": act.group("noun").strip(), "continuation": True}
    if _IMPERATIVE.match(body):
        return {"kind": "imperative", "prefix": "", "qualifier": "", "leading": clause, "continuation": False}
    other = _OTHER_SUBJECT.match(body)
    if other:
        noun = other.group("noun").strip()
        return {"kind": "other", "prefix": "", "qualifier": "", "leading": clause, "noun": noun, "continuation": bool(_CREW_ACT_NOUN.match(noun))}
    return {"kind": "fragment", "prefix": "", "qualifier": "", "leading": clause, "continuation": True}


def _airport_conditions(text: str, flight: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
    """Departure / arrival aerodrome restrictions in a qualifier, evaluated against this flight's own airports; the qualifier with them removed."""
    conditions: list[dict[str, Any]] = []
    remainder = text
    for match in _AIRPORT_CONDITION.finditer(text):
        icao = match.group("icao")
        if icao in _ICAO_STOPWORDS:
            continue
        arrival = match.group("kind").startswith(("ARR", "LANDING", "BOUND"))
        both = match.group("kind").startswith(("OPERATING TO/FROM", "OPERATING TO OR FROM", "TO OR FROM"))
        own = [str(flight.get("destination") or "").upper()] if arrival else [str(flight.get("departure") or "").upper()]
        if both:
            own = [str(flight.get("departure") or "").upper(), str(flight.get("destination") or "").upper()]
        own = [o for o in own if o]
        kind = "arrival" if arrival else "departure"
        if not own:
            result, note = "unresolved", "this flight's airports are not held"
        elif icao in own:
            result, note = "met", f"this flight {'arrives at' if arrival else 'departs'} {icao}"
        else:
            result, note = "not_met", f"this flight {'arrives at' if arrival else 'departs'} {'/'.join(own)}"
        conditions.append({"kind": kind, "text": f"{match.group('kind')} {icao} ({note})", "result": result})
        remainder = remainder.replace(match.group(0), " ")
    remainder = re.sub(r"\b(?:PLANNED TO|PLANNING TO|INTENDING TO)\s*$", "", remainder)
    remainder = re.sub(r"\s+", " ", remainder).strip(" ,;")
    return conditions, remainder


def _subject_conditions(subject: dict[str, Any], flight: dict[str, Any]) -> list[dict[str, Any]]:
    """The conditions a stated subject carries: aerodrome restrictions evaluated, every other qualifier explicit and unresolved."""
    conditions: list[dict[str, Any]] = []
    prefix = subject.get("prefix") or ""
    equipment = _EQUIPMENT_PREFIX.search(prefix)
    if equipment:
        conditions.append({"kind": "equipment", "text": equipment.group(0), "result": "unresolved"})
    rules = _RULES_PREFIX.search(prefix)
    if rules:
        conditions.append({"kind": "flight_rules", "text": rules.group(0), "result": "unresolved"})
    qualifier = (subject.get("qualifier") or "").strip(" ,;")
    if qualifier and not _EVALUATED_QUALIFIER.match(qualifier):
        airports, remainder = _airport_conditions(qualifier, flight)
        conditions.extend(airports)
        if len(remainder.split()) >= 2 and not _EVALUATED_QUALIFIER.match(remainder):
            conditions.append({"kind": "qualifier", "text": qualifier if airports else remainder, "result": "unresolved"})
    if subject.get("leading"):
        clause = subject["leading"]
        if not _EVALUATED_QUALIFIER.match(re.sub(r"^(?:WHEN|IF|WHILE|UNLESS|AFTER|BEFORE|DURING|PROVIDED|WHERE)\s+", "", clause)):
            conditions.append({"kind": "qualifier", "text": clause, "result": "unresolved"})
    return conditions


def _population_conditions(sentence: str, flight: dict[str, Any]) -> list[dict[str, Any]]:
    """Qualifications of the aircraft population inside a sentence's body, evaluated like a subject's (F1, 424 QA)."""
    upper = classify_text(sentence)
    conditions: list[dict[str, Any]] = []
    for match in _POPULATION.finditer(upper):
        modifier = _RELATIVE_OPENING.sub("", match.group("modifier").strip(" ,;"))
        pseudo = {"kind": "population", "prefix": match.group("prefix").strip(), "qualifier": modifier, "leading": None}
        conditions.extend(_subject_conditions(pseudo, flight))
    return conditions


def _head_noun(noun: str) -> str:
    chunk = _HEAD_STOP.split(noun)[0].strip(" ,.;:-")
    words = chunk.split()
    return words[-1] if words else ""


def _actor_of(sentence: str, subject: dict[str, Any]) -> str:
    """"crew" for a sentence that directs the crew; "atc" for a provision, service or separation ATC applies or provides."""
    if subject["kind"] in ("stated", "imperative") or subject.get("continuation"):
        return "crew"
    upper = classify_text(sentence)
    if _CREW_DIRECTIVE.search(upper) or _IMPERATIVE.match(upper):
        return "crew"
    if _head_noun(subject.get("noun") or "") in _ATC_HEADS or _SERVICE_PASSIVE.search(upper) or _ATC_AGENT.search(upper):
        return "atc"
    return "crew"


def _trailing_conditions(sentence: str) -> list[dict[str, Any]]:
    """A WHEN / IF / UNLESS clause after the action ("USE LOGON ADDRESS PAZN WHEN OPERATING IN ...") stays an explicit unresolved condition."""
    upper = classify_text(sentence)
    match = _TRAILING_CLAUSE.search(upper)
    if not match:
        return []
    clause = match.group("clause").strip(" ,;")
    if _EVALUATED_QUALIFIER.match(re.sub(r"^(?:WHEN|IF|WHILE|UNLESS|PROVIDED|WHERE|EXCEPT WHEN|ONLY WHEN|ONLY IF)\s+", "", clause)):
        return []
    return [{"kind": "qualifier", "text": clause, "result": "unresolved"}]


def _governing_index(parts: list[str], subjects: list[dict[str, Any]], index: int) -> int | None:
    """The nearest earlier sentence with a stated crew subject, for a sentence that continues it (a fragment, or a
    subject naming the crew's own act); a sentence with a subject of its own - crew or another actor - borrows nothing."""
    if not subjects[index]["continuation"]:
        return None
    for j in range(index - 1, -1, -1):
        if subjects[j]["kind"] == "stated":
            return j
    return None


def _state_of(conditions: list[dict[str, Any]]) -> str:
    results = [c["result"] for c in conditions]
    return "not_applicable" if "not_met" in results else "conditions_unresolved" if "unresolved" in results else "conditions_held"


def _dedupe(conditions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str]] = set()
    kept: list[dict[str, Any]] = []
    for condition in conditions:
        key = (condition["kind"], condition["text"])
        if key not in seen:
            seen.add(key)
            kept.append(condition)
    return kept


def _compose_procedure(record: dict[str, Any], flight: dict[str, Any], route: dict[str, Any], crossings: list[dict[str, Any]],
                       names: dict[str, str], basis: dict[str, Any]) -> dict[str, Any] | None:
    """One source-held notice against this flight's OFP; None when the notice's airspace is not on the parsed route."""
    text = _normalise(record.get("text"))
    kind = procedure_kind(text)
    if kind is None:
        return None
    heading = classify_text(record.get("heading"))
    heading_kind = _normalise(record.get("heading_kind")) or ("fir" if re.match(r"^[A-Z]{4}\b", heading) else "segment")
    crossed = {row["fir"] for row in crossings}
    first_by_fir: dict[str, dict[str, Any]] = {}
    for row in crossings:
        first_by_fir.setdefault(row["fir"], row)
    segment = record.get("segment") if isinstance(record.get("segment"), dict) else None
    segment_waypoints = [str(w).upper() for w in ((segment or {}).get("from"), (segment or {}).get("to")) if isinstance(w, str)]

    association, fir = "unresolved", ""
    if heading_kind == "fir":
        heading_fir = _normalise(record.get("fir")).upper() or heading.split(" ")[0]
        if heading_fir not in crossed:
            return None
        association, fir = "fir_heading", heading_fir
    else:
        body_firs = [icao for icao, _ in _BODY_FIR.findall(classify_text(text)) if icao in crossed]
        on_route = [w for w in segment_waypoints if w in route["names"]]
        if body_firs:
            association, fir = "body_fir", body_firs[0]
        elif on_route:
            in_effect = route["fir_in_effect"][route["names"].index(on_route[0])]
            if in_effect and in_effect in crossed:
                association, fir = "segment_on_route", in_effect
        elif segment_waypoints:
            return None
    entry = first_by_fir.get(fir) if fir else None
    relation = _relation(crossings, fir) if fir else "unresolved"

    # ---- notice-level conditions: validity at the effective timing basis, the notice's route / level tokens, ATC's request
    notice_conditions: list[dict[str, Any]] = []
    validity = _normalise(record.get("validity"))
    window = validity_window(validity)
    basis_utc = _utc(basis.get("utc")) if basis.get("utc") else None
    instant = basis_utc + timedelta(minutes=entry["actm_minutes"]) if basis_utc and entry else None
    basis_text = (
        f"ATOT {basis_utc:%H%M}Z + ACTM" if basis["kind"] == "actual_takeoff" and basis_utc
        else f"scheduled departure {basis_utc:%H%M}Z + ACTM" if basis["kind"] == "scheduled_departure" and basis_utc
        else "no departure time held"
    )
    if window is None or instant is None:
        notice_conditions.append({"kind": "validity", "text": validity, "result": "unresolved", "basis": basis_text})
    else:
        start, end = window
        notice_conditions.append({"kind": "validity", "text": validity, "result": "met" if start <= instant and (end is None or instant <= end) else "not_met", "basis": basis_text})
    tokens = _route_tokens(text)
    if segment is not None and heading_kind == "segment":
        tokens = [{"waypoint": w, "airway": segment.get("airway"), "band": None, "text": _normalise(record.get("heading"))} for w in segment_waypoints] + tokens
    route_frequencies: list[str] | None = None
    if tokens:
        on_route_tokens = [t for t in tokens if t["waypoint"] in route["names"]]
        matched = on_route_tokens[0] if on_route_tokens else None
        notice_conditions.append({"kind": "route", "text": matched["text"] if matched else tokens[0]["text"], "result": "met" if matched else "not_met"})
        if matched and matched.get("frequencies"):
            route_frequencies = list(matched["frequencies"])
        band_token = next((t for t in on_route_tokens if t["band"]), None)
        if band_token:
            level = _planned_level_at(route, band_token["waypoint"])
            low, high = band_token["band"]
            notice_conditions.append({
                "kind": "level", "text": f"FL{low}-FL{high} at {band_token['waypoint']}",
                "result": "unresolved" if level is None else "met" if low <= level <= high else "not_met",
                "note": f"planned FL{level}" if level is not None else "planned level not held",
            })
    atc_request = _ATC_REQUEST.search(classify_text(text))
    if atc_request:
        notice_conditions.append({"kind": "atc_request", "text": atc_request.group(0), "result": "unresolved"})
    if association == "unresolved":
        notice_conditions.append({"kind": "association", "text": "FIR in effect at the segment not derivable from the boundary rows", "result": "unresolved"})

    # ---- every communication sentence is an action with its own conditions (its subject's, or its governing sentence's)
    parts = sentences(text)
    subjects = [_subject_of(part) for part in parts]
    scopes = [sentence_scope(part) for part in parts]
    actions: list[dict[str, Any]] = []
    for index, part in enumerate(parts):
        part_kind = procedure_kind(part)
        if part_kind is None:
            continue
        governing = _governing_index(parts, subjects, index)
        scope = scopes[index] if scopes[index] != "unscoped" or governing is None else scopes[governing]
        conditions = list(notice_conditions)
        if scope == "overflight":
            conditions.append({"kind": "scope", "text": "overflight", "result": "met" if relation == "overflight" else "not_met" if relation == "arrival" else "unresolved"})
        elif scope == "aerodrome":
            conditions.append({"kind": "scope", "text": "arrival/departure operations at aerodromes in the FIR", "result": "met" if relation == "arrival" else "not_met" if relation == "overflight" else "unresolved"})
        elif scope == "fir_exit":
            conditions.append({"kind": "scope", "text": "departing the FIR", "result": "met" if relation == "overflight" else "not_met" if relation == "arrival" else "unresolved"})
        direction = next((m for m in (pattern.search(classify_text(part)) for pattern in _DIRECTIONS) if m), None)
        if direction:
            origins = _resolve_names(direction.group("from"), names)
            targets = _resolve_names(direction.group("to"), names)
            origin_rows = [first_by_fir[icao] for _, icao in origins if icao in first_by_fir]
            target_rows = [first_by_fir[icao] for _, icao in targets if icao in first_by_fir]
            if any(icao is None for _, icao in origins) and not origin_rows or all(icao is None for _, icao in targets):
                result = "unresolved"
            elif not origin_rows or not target_rows:
                result = "not_met"
            else:
                result = "met" if any(o["sequence"] < t["sequence"] for o in origin_rows for t in target_rows) else "not_met"
            conditions.append({
                "kind": "direction",
                "text": "/".join(icao or name for name, icao in origins) + " → " + "/".join(icao or name for name, icao in targets),
                "result": result,
            })
        # The sentence's own clauses first, then - for a continuation only - the governing crew sentence's qualifiers.
        conditions.extend(_subject_conditions(subjects[index], flight))
        if governing is not None:
            conditions.extend(_subject_conditions(subjects[governing], flight))
        conditions.extend(_trailing_conditions(part))
        conditions.extend(_population_conditions(part, flight))
        actor = _actor_of(part, subjects[index])
        unresolved = _UNRESOLVED.search(classify_text(part))
        if unresolved:
            conditions.append({"kind": "other", "text": unresolved.group(0).lower().replace(" ", "-"), "result": "unresolved"})
        conditions = _dedupe(conditions)
        details = printed_details(part)
        if route_frequencies is not None and not details["frequencies"]:
            details["frequencies"] = route_frequencies
        actions.append({
            "sentence": part,
            "kind": part_kind,
            "scope": scope,
            "actor": actor,
            "directive": actor == "crew" and (bool(_DIRECTIVE.search(classify_text(part))) or subjects[index]["kind"] == "imperative"),
            "conditions": conditions,
            "applicability_state": _state_of(conditions),
            "printed_details": details,
        })
    if not actions:
        return None

    def rank(action: dict[str, Any]) -> tuple[int, int, int, int, int]:
        return (
            0 if _scope_compatible(action["scope"], relation) else 1,
            0 if action["directive"] else 1,
            0 if action["kind"] == kind else 1,
            0 if _has_values(action["printed_details"]) else 1,
            actions.index(action),
        )

    headline = min(actions, key=rank)
    instruction = headline["sentence"]
    scope = headline["scope"]
    conditions = headline["conditions"]
    state = headline["applicability_state"]
    details = dict(headline["printed_details"])
    if route_frequencies is not None:
        details["frequencies"] = list(route_frequencies)
    lead_minutes = _lead_minutes(details["lead"])
    next_fir = _next_fir(crossings, fir) if fir and scope == "fir_exit" else None
    latest = None
    if lead_minutes is not None:
        anchor = None
        if scope == "fir_exit":
            anchor = next((row for row in crossings if next_fir and row["fir"] == next_fir["fir"] and row["actm"] == next_fir["actm"]), None)
        elif entry:
            anchor = entry
        if anchor and anchor["actm_minutes"] >= lead_minutes:
            latest = actm_text(anchor["actm_minutes"] - lead_minutes)

    return {
        "fir": fir,
        "notam_id": _normalise(record.get("notam_id")).upper(),
        "source_page": _integer(record.get("source_page")),
        "validity": validity,
        "heading": _normalise(record.get("heading")),
        "heading_kind": heading_kind,
        "kind": kind,
        "association": association,
        "instruction": instruction,
        "instruction_short": shorten(instruction),
        "note": _governed_note(record),
        "printed_details": details,
        "conditions": conditions,
        "applicability_state": state,
        "actor": headline["actor"],
        "actions": [{k: v for k, v in action.items() if k != "directive"} for action in actions],
        "next_fir": next_fir,
        "latest_actm": latest,
        "actm": entry["actm"] if entry else None,
        "sequence": entry["sequence"] if entry else None,
        "on_route": True,
        "applicability": "not_inferred",
    }


def _minutes(actm: str | None) -> int | None:
    if not actm:
        return None
    hours, minutes = actm.split(":")
    return int(hours) * 60 + int(minutes)


def _time_order(row: dict[str, Any]) -> tuple[int, int, int, str]:
    """Rows in the order their actions fall due: the latest ACTM a printed lead gives, else the entry; then state, kind, identity."""
    anchor = _minutes(row.get("latest_actm")) if row.get("latest_actm") else _minutes(row.get("actm"))
    return (anchor if anchor is not None else 10 ** 6, _STATE_RANK[row["applicability_state"]], _KIND_RANK[row["kind"]], row["notam_id"])


def is_call_line(line: dict[str, Any]) -> bool:
    """A voice / broadcast / logon row whose printed conditions are not failed."""
    return line["kind"] != "datalink_other" and line["applicability_state"] != "not_applicable"


def has_printed_values(line: dict[str, Any]) -> bool:
    details = line.get("printed_details") or {}
    return bool(details.get("frequencies") or details.get("lead") or details.get("interval"))


def primary_procedure_line(lines: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The one row every page-6 ladder step prints in full and parity binds on both surfaces: in time order, the first
    call row that prints a frequency, else the first with any printed value, else the first call row, else the first row."""
    return (
        next((l for l in lines if is_call_line(l) and (l.get("printed_details") or {}).get("frequencies")), None)
        or next((l for l in lines if is_call_line(l) and has_printed_values(l)), None)
        or next((l for l in lines if is_call_line(l)), None)
        or (lines[0] if lines else None)
    )


def printed_values(line: dict[str, Any]) -> list[str]:
    """The parts both surfaces print after the instruction: the frequencies, lead and interval as printed, the next FIR for an exit call, the latest ACTM a printed lead gives."""
    details = line.get("printed_details") or {}
    parts: list[str] = []
    if details.get("frequencies"):
        parts.append(", ".join(details["frequencies"]))
    if details.get("lead"):
        parts.append(details["lead"])
    if details.get("interval"):
        parts.append(details["interval"])
    if details.get("addresses"):
        parts.append("logon " + ", ".join(details["addresses"]))
    if line.get("next_fir"):
        parts.append(f"next FIR {line['next_fir']['fir']} at {line['next_fir']['actm']}")
    if line.get("latest_actm"):
        parts.append(f"not later than ACTM {line['latest_actm']}")
    return parts


def condition_phrase(condition: dict[str, Any]) -> str:
    kind, result, text = condition["kind"], condition["result"], condition.get("text") or ""
    if kind == "validity":
        outcome = {"met": "covers this crossing", "not_met": "outside this crossing", "unresolved": "not evaluable"}[result]
        return f"validity {text}: {outcome} (at {condition.get('basis') or 'no departure time held'})"
    if kind == "route":
        return f"route {text}: " + {"met": "on the filed route", "not_met": "not on the filed route", "unresolved": "unresolved"}[result]
    if kind == "level":
        return f"level {text}: {condition.get('note') or ''} " + {"met": "within", "not_met": "outside", "unresolved": "not evaluable"}[result]
    if kind == "direction":
        return f"direction {text}: " + {"met": "met", "not_met": "not met", "unresolved": "unresolved"}[result]
    if kind == "scope":
        return f"{text}: " + {"met": "met", "not_met": "not met", "unresolved": "unresolved"}[result]
    if kind in ("departure", "arrival"):
        return f"{kind} {text}: " + {"met": "met", "not_met": "not met", "unresolved": "not evaluable"}[result]
    if kind == "qualifier":
        return f"{text}: not evaluable from the OFP"
    if kind == "equipment":
        return f"equipment {text}: not held for this aircraft"
    if kind == "flight_rules":
        return f"flight rules {text}: not held in the analysis"
    if kind == "atc_request":
        return f"{text.lower()}: at ATC's request"
    if kind == "association":
        return text
    return f"{text} condition not evaluable"


STATE_PHRASES = {"conditions_held": "conditions held", "conditions_unresolved": "conditions unresolved", "not_applicable": "not applicable"}


def conditions_summary(row: dict[str, Any]) -> str:
    """The row's conditions and state in one line; an ATC provision says so first (release-424 QA, F1)."""
    phrases = ["ATC provision"] if row.get("actor") == "atc" else []
    phrases.extend(condition_phrase(c) for c in row.get("conditions") or [])
    phrases.append(STATE_PHRASES[row["applicability_state"]])
    return " · ".join(phrases)


def procedure_lines(procedures: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One printed row per FIR, text and applicability; notices that carry the same instruction share the row. Composed order kept."""
    lines: list[dict[str, Any]] = []
    for row in procedures:
        text = row["note"] or row["instruction_short"]
        line = next((item for item in lines if item["fir"] == row["fir"] and item["text"] == text and item["applicability_state"] == row["applicability_state"]), None)
        if line is not None:
            if row["notam_id"] not in line["notam_ids"]:
                line["notam_ids"].append(row["notam_id"])
            if row["source_page"] is not None and row["source_page"] not in line["source_pages"]:
                line["source_pages"].append(row["source_page"])
            continue
        lines.append({
            "fir": row["fir"], "actm": row["actm"], "sequence": row["sequence"], "text": text, "kind": row["kind"],
            "association": row["association"], "applicability_state": row["applicability_state"],
            "printed_details": {"frequencies": list(row["printed_details"]["frequencies"]), "lead": row["printed_details"]["lead"], "interval": row["printed_details"]["interval"], "addresses": list(row["printed_details"].get("addresses") or [])},
            "latest_actm": row["latest_actm"], "next_fir": dict(row["next_fir"]) if row["next_fir"] else None,
            "further_actions": max(0, len(row.get("actions") or []) - 1),
            "conditions_summary": conditions_summary(row),
            "notam_ids": [row["notam_id"]], "source_pages": [row["source_page"]] if row["source_page"] is not None else [],
        })
    for line in lines:
        line["source_pages"].sort()
    return lines


# ---------------------------------------------------------------- slot control


def _slot_control(flight: dict[str, Any]) -> dict[str, Any] | None:
    bobcat = flight.get("bobcat")
    if not isinstance(bobcat, dict) or not bobcat.get("waypoint"):
        return None
    waypoint = str(bobcat["waypoint"]).upper()
    ctot_at = _utc(bobcat.get("ctot_utc"))
    cto_at = _utc(bobcat.get("cto_utc"))
    # The engine's own rule: an allocated CTO printed before the CTOT is the next UTC day.
    if ctot_at and cto_at and cto_at < ctot_at:
        cto_at = cto_at + timedelta(days=1)
    row = next((w for w in flight.get("route_waypoints") or [] if isinstance(w, dict) and str(w.get("name") or "").upper() == waypoint), None)
    actm_minutes = _integer(row.get("actm_minutes")) if row else None
    computed = ctot_at + timedelta(minutes=actm_minutes) if actm_minutes is not None and ctot_at else None
    difference = round((computed - cto_at).total_seconds() / 60) if computed and cto_at else None
    evidence = flight.get("source_evidence") if isinstance(flight.get("source_evidence"), dict) else {}
    pages = sorted({p for p in (_integer(evidence.get("page1")), _integer(row.get("source_page")) if row else None) if p is not None and p > 0})
    level = bobcat.get("flight_level")
    return {
        "system": "BOBCAT",
        "waypoint": waypoint,
        "flight_level": _integer(level) if _integer(level) is not None else (int(level) if level is not None else None),
        "ctot": _hhmm_z(_utc(bobcat.get("ctot_utc"))),
        "cto": _hhmm_z(_utc(bobcat.get("cto_utc"))),
        "actm": actm_text(actm_minutes) if actm_minutes is not None else None,
        "computed_cto": _hhmm_z(computed),
        "difference_minutes": difference,
        "source_pages": pages,
    }


def slot_sentence(slot: dict[str, Any] | None) -> str:
    if not slot:
        return NO_ALLOCATION_SENTENCE
    pages = f" (OFP {', '.join(f'p{p}' for p in slot['source_pages'])})" if slot["source_pages"] else ""
    level = f"FL{slot['flight_level']}" if slot["flight_level"] is not None else "level not found"
    if slot["actm"] is None or slot["computed_cto"] is None or slot["difference_minutes"] is None:
        return (
            f"{slot['system']} {slot['waypoint']} {level}: CTOT {slot['ctot'] or 'not found'}, "
            f"CTO {slot['cto'] or 'not found'}; ACTM for {slot['waypoint']} not found in the OFP{pages}."
        )
    difference = slot["difference_minutes"]
    delta = "matches CTO" if difference == 0 else f"{abs(difference)} min {'before' if difference < 0 else 'after'} CTO"
    return (
        f"{slot['system']} {slot['waypoint']} {level}: CTOT {slot['ctot']} + ACTM {slot['actm']} = "
        f"{slot['computed_cto']}, {delta} {slot['cto']}{pages}."
    )


# ---------------------------------------------------------------- the composition


def _iso_z(value: datetime | None) -> str | None:
    return f"{value:%Y-%m-%dT%H:%M:%S}Z" if value else None


def timing_basis(flight: dict[str, Any], actual_takeoff_utc: Any = None) -> dict[str, Any]:
    """One effective basis for every clock and every validity decision: the actual take-off when held (the entered one first, then the analysis' own), else the scheduled departure, else none - and it is named."""
    takeoff = _utc(actual_takeoff_utc) if actual_takeoff_utc else _utc(flight.get("actual_takeoff_utc"))
    if takeoff:
        return {"kind": "actual_takeoff", "utc": _iso_z(takeoff)}
    scheduled = _utc(flight.get("scheduled_departure_utc"))
    if scheduled:
        return {"kind": "scheduled_departure", "utc": _iso_z(scheduled)}
    return {"kind": "none", "utc": None}


def extraction_statement(flight: dict[str, Any]) -> dict[str, Any]:
    """The extraction rules the parser stamped on this analysis, against the value in service."""
    rules = flight.get("extraction_rules") if isinstance(flight.get("extraction_rules"), str) and flight.get("extraction_rules") else None
    return {"rules": rules, "current": rules == EXTRACTION_RULES}


def compose_enroute_contact(flight: dict[str, Any] | None, findings: list[dict[str, Any]] | None = None, actual_takeoff_utc: Any = None) -> dict[str, Any]:
    source = flight if isinstance(flight, dict) else {}
    basis = timing_basis(source, actual_takeoff_utc)
    takeoff = _utc(basis["utc"]) if basis["kind"] == "actual_takeoff" else None
    crossings = _crossings(source, takeoff)
    route = _route(source)
    records = [r for r in source.get("notam_procedure_records") or [] if isinstance(r, dict)]
    names = _fir_names(source, records)
    extraction = extraction_statement(source)
    procedures: list[dict[str, Any]] = []
    other_procedure_count = 0
    for record in records:
        composed = _compose_procedure(record, source, route, crossings, names, basis)
        if composed is None:
            other_procedure_count += 1
        else:
            procedures.append(composed)
    procedures.sort(key=_time_order)

    required_calls: list[dict[str, Any]] = []
    for item in findings or []:
        if not isinstance(item, dict) or item.get("engine") != "communications":
            continue
        data = item.get("data") if isinstance(item.get("data"), dict) else {}
        minutes = _integer(data.get("action_actm_minutes"))
        if minutes is None:
            continue
        required_calls.append({
            "title": _normalise(item.get("title")),
            "summary": _normalise(item.get("summary")),
            "details": [_normalise(d) for d in (item.get("details") if isinstance(item.get("details"), list) else []) if _normalise(d)],
            "actm": actm_text(minutes),
            "actm_minutes": minutes,
        })

    source_pages = sorted({row["source_page"] for row in crossings if row["source_page"] is not None})
    voice = sum(1 for row in procedures if row["kind"] in ("voice_contact", "tiba_broadcast"))
    met = sum(1 for row in procedures if row["applicability_state"] == "conditions_held")
    unresolved = sum(1 for row in procedures if row["applicability_state"] == "conditions_unresolved")
    not_applicable = sum(1 for row in procedures if row["applicability_state"] == "not_applicable")
    if required_calls:
        state = "library_rules_held"
        state_sentence = f"{len(required_calls)} early-call requirement(s) from the approved reference library."
    elif procedures:
        state = "source_procedures_held"
        state_sentence = (
            f"No approved early-call rule is held. {len(procedures)} source-held communication notice(s) on the parsed route "
            f"({voice} voice/broadcast, {len(procedures) - voice} datalink): printed conditions met on {met}, unresolved on {unresolved}, "
            f"not applicable on {not_applicable}. Frequencies and lead times are the source's own printed values; none is inferred from crossing times."
        )
    elif crossings:
        state = "no_procedure_held"
        state_sentence = STATE_SENTENCES[state]
    else:
        state = "no_fir_rows_held"
        state_sentence = STATE_SENTENCES[state]
    if not extraction["current"]:
        state_sentence = (
            f"Held extraction predates the current parser ({extraction['rules'] or 'rules not stated'}): the notices below are the ones "
            f"that extraction held; Create updated briefing re-reads the OFP. {state_sentence}"
        )

    notam_pages = sorted({row["source_page"] for row in procedures if row["source_page"] is not None})
    if crossings:
        provenance = f"FPL {_page_range(source_pages) or 'page not held'}"
        if notam_pages:
            provenance += f" / NOTAM {_page_range(notam_pages)}"
    else:
        provenance = "FPL boundary rows not held"

    slot = _slot_control(source)
    return {
        "rule": ENROUTE_CONTACT_RULE,
        "state": state,
        "state_sentence": state_sentence,
        "timing_basis": basis,
        "extraction": extraction,
        "crossings": crossings,
        "crossing_sequence": " · ".join(f"{row['fir']} {row['actm']}" for row in crossings),
        "source_pages": source_pages,
        "procedures": procedures,
        "procedure_lines": procedure_lines(procedures),
        "other_procedure_count": other_procedure_count,
        "required_calls": required_calls,
        "slot_control": slot,
        "slot_sentence": slot_sentence(slot),
        "provenance": provenance,
    }


def crossing_sequence_limited(crossings: list[dict[str, Any]], limit: int = 24, compact: bool = False) -> str:
    """The PDF's whole-pair prefix rule: never a cut pair; the deferral is stated (in fewer words at the ladder's last step)."""
    pairs = [f"{row['fir']} {row['actm']}" for row in crossings]
    if len(pairs) <= limit:
        return " · ".join(pairs)
    suffix = "more on the dashboard" if compact else "more (ordered list with derived UTC on the dashboard)"
    return " · ".join(pairs[:limit]) + f" · +{len(pairs) - limit} {suffix}"
