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

HEADING-CONTINUITY-432 (26 Sep 2026, rule v8). The parser reads NOTAM headings
across page breaks and names each record's heading page; a record whose owner
the source layout does not establish arrives with heading_kind "unresolved".
Such a record is bound to no crossing - no ACTM, no lead-time clock - and says
so ("section heading not established from the source layout"); a FIR its own
body names still associates it. Every composed notice carries heading_page.

SLOT-ALLOCATION-434 (27 Sep 2026, rule v9). The slot line says what the OFP prints: the allocation read (under the
system and on the page the print names), an allocation printed but not read (quoted, with why - never absence), no
allocation held by an extraction older than the grammar (Create updated briefing re-reads it), or - only when the
current extraction found nothing allocation-like - that none is printed.

AIRSPACE-HEADINGS-436 (27 Sep 2026, rule v10). A record held under a FIR heading that names the FIR's airspace part
("RJJJ FUKUOKA FIR OCEANIC", "UBBA BAKU FIR LOWER", "KZNY NEW YORK DOMESTIC LOWER", "LFFF FRANCE UIR") is bound to that
FIR's crossing, and the printed part is stated as a condition the OFP's boundary rows cannot evaluate ("section ...").
A record held under a topic heading in an enroute part ("UAV 401614N 0250927E", "VAA GREAT SITKIN") is bound to no
crossing unless its own body names the FIR, and says the owning FIR is not established.

ATC-SOURCE-COVERAGE (30 Sep 2026, rule v11). Printed FIR status and crew
notification/fallback duties are retained even without a timed FPL boundary.
That missing association/time stays unresolved with source-page provenance.
Service availability, negation and ATC provisions cannot become crew calls;
only a positive crew instruction can derive a deadline from its printed lead.
Headings require source layout evidence; no route or notice outcome is pinned.

ATC-CLEARANCE-FAMILY (1 Oct 2026, rule v12). Release-444 QA found SQ23 CO188/02 (LTAA
ANKARA FIR p106) in the raw source but not the record: admission enumerated contact /
call / report verbs. A request, clarification or confirmation addressed to a unit and
the refusal or acceptance of an ATC clearance or ATC-qualified instruction are held;
maintenance instructions, terrain clearance and flow-unit queries are not. A stop printed
without a space (AIRSPACE.DO) ends a sentence outside dotted addresses; a crew directive
coordinated with a conditional instruction, and a list item opening its own crew request,
are separate statements; statements of a sentence referring to its notice's clearances
keep the text before and after verbatim and unresolved (no annotation decoded); a
navigation aid's frequency is never a printed communication value.
An agent printed inside a circumstance or exception ("UNLESS AUTH BY ATC ...:") is not the
statement's actor; an exception closed by a colon leads its statement; ACFT OPS is ACFT OPERATIONS.

"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

from .extraction_rules import EXTRACTION_RULES

# v13 (ATC-PDF-PRIORITY, 2 Oct 2026): the primary row prefers a call whose printed conditions are held; an airway-only route
# list ("VIA RTE B346, R474, W21 AND G473") is read against the airways the OFP files inside the notice's own FIR.
# v14 (ATC-AIRWAY-BOUNDARIES, Codex QA of release 448): an exit leg whose airway is not held, an exit leg after consecutive
# boundary rows and an exit boundary with no following waypoint leave the FIR's filed airways incomplete.
# v15 (ATC-AIRWAY-LEG-TRANSITIONS, Codex QA of release 450): a leg touching the FIR stays open across any boundary rows
# until a waypoint closes it; a touching leg still open at the end of the route leaves the FIR's airways incomplete.
# v16 (ATC-ABSENCE-WORDING, Codex review of release 452): an empty call list states only that no early-contact
# instruction was identified - never that the source's frequencies or lead times are absent (SQ882 09 Sep 1A2345/26).
# v17 (ATC-EARLY-CALLS, David 25 Oct 2026 on SQ301 MAN-SIN: "the early ATC call content is missing still"): every crew
# call row that prints a lead before a FIR entry is an early call. The composition lists them in the order they fall
# due (early_calls), each with its call time from the OFP entry ACTM and the printed lead read as printed (NOT LESS THAN
# / AT LEAST / bare -> not later than; WITHIN / BETWEEN / MAXIMUM -> a window ending at the entry), the unit the
# instruction or its filed-route table row names, the frequencies and the entry; a lead measured from take-off derives
# no FIR clock. The page-6 card, the decision timeline and the dashboard print these first; nothing is inferred.
ENROUTE_CONTACT_RULE = "enroute-contact-v17"
# A record whose owning heading the source layout does not establish (parser heading_kind "unresolved").
_UNRESOLVED_OWNER = "section heading not established from the source layout"

JAKARTA_AFN_NOTE = "CPDLC limited trial: pilot initiates AFN logon only when requested by ATC; address WIIF."
_JAKARTA_TOKENS = ("ADS-C/CPDLC", "REQUESTED BY ATC", "AFN LOGON", "ADDRESS FOR JAKARTA FIR IS WIIF")

# OCR / line-wrap splits joined for classification and evaluation only; every
# quotation keeps the source spelling. CALL SIGN is joined so that a bare CALL
# is an instruction and a call sign is not.
_OCR_JOINS = (
    ("CON TACT", "CONTACT"), ("BROAD CAST", "BROADCAST"), ("LOG ON", "LOGON"), ("LOG-ON", "LOGON"),
    ("TRANS MISSION", "TRANSMISSION"), ("FREQ UENCY", "FREQUENCY"), ("CALL SIGN", "CALLSIGN"), ("CALLSIGNS", "CALLSIGN"),
)
_UNIT = r"(?:ACC|ACCS|CTL|CONTROL|RADAR|RADIO|APP|APPROACH|TWR|TOWER|CENTER|CENTRE|ATC|ATS|FIR|INFORMATION|UNIT|SECTOR|CTR|OCC|ARTCC|ATSU|FSS)"
# ATC-CLEARANCE-FAMILY (1 Oct 2026). A request, clarification or confirmation addressed to an ATC unit, and the refusal
# or acceptance of an ATC clearance or ATC instruction, are communications with ATC - on positive ATC evidence only:
#   recipient    an ATC authority by name (ATC, ATS, ACC, ARTCC, ATSU, FIC, FSS, APP, TWR, an air traffic control / ATS
#                unit), or a radio call sign ("<NAME> CONTROL / RADAR / APPROACH / TOWER / CENTRE / RADIO / INFORMATION")
#                whose NAME the notice or its heading prints as an airspace ("NICOSIA FIR", "NICOSIA AIRSPACE"); a bare
#                "UNIT" or "CONTROL" is no ATC evidence ("THE MAINTENANCE UNIT", "MAINTENANCE CONTROL");
#   clearance    an ATC clearance by type (climb, descent, level, routing, direct ...; "ATC CLEARANCE"), one issued by or
#                from an ATC recipient, or "THESE / SUCH CLEARANCES" whose antecedent in the notice is one of those;
#                "MAINTENANCE CLEARANCES" or "TERRAIN CLEARANCE" are none;
#   instruction  an ATC recipient's instruction, or one issued by or from an ATC recipient (or a referent of one); a
#                frequency or company medium alone is no ATC evidence ("MAINTENANCE INSTRUCTIONS ... ON THE COMPANY
#                FREQUENCY"), while "ATC INSTRUCTIONS ... ON THE COMPANY FREQUENCY" are ATC's.
_ATC_AUTHORITY = r"(?:AIR TRAFFIC (?:CONTROLLERS?|CONTROL|SERVICES?)(?:\s+UNIT)?|(?:ATC|ATS)\s+UNIT|ATC|ATS|ATSU|ACC|ACCS|ARTCC|FIC|FSS|APP|TWR)"
_CALL_SIGN = r"(?:CONTROL|CTL|RADAR|APPROACH|TOWER|CENTRE|CENTER|RADIO|INFORMATION)"
# A name the source prints as airspace, for its call sign ("NICOSIA FIR" -> NICOSIA CONTROL); a determiner names nothing.
_AIRSPACE_NAME = re.compile(r"\b(?!(?:THE|THIS|THAT|EACH|ANY|ALL|NEXT|ADJACENT|RELEVANT|SAME|APPROPRIATE|RESPECTIVE|CONCERNED|OTHER)\b)"
                            r"([A-Z][A-Z-]{2,})\s+(?:FIR|UIR|ACC|AIRSPACE|CTA|UTA|TMA|OCEANIC|ARTCC|FIC)\b")
_RECIPIENT_WORDS = r"(?:THE\s+)?(?:[A-Z/][A-Z/-]*\s+){0,4}?"
# The clearances ATC issues, by their own printed type.
_CLEARANCE_TYPE = (r"(?:ATC|ATS|CLIMB|DESCENT|DESCEND|LEVEL|FLIGHT LEVEL|ALTITUDE|ROUTE|ROUTING|RE-?ROUTE|RE-?ROUTING|DIRECT|HEADING|SPEED"
                   r"|APPROACH|DEPARTURE|TAKE-?OFF|LANDING|OCEANIC|ENTRY|CROSSING|TRANSIT|HOLDING|TAXI|PUSH-?BACK|START-?UP|EN-?ROUTE)")
_REFERENT = r"(?:THESE|SUCH|THOSE|SAID|THIS)\s+(?:[A-Z-]+\s+){0,2}?"
# A negated act: a refusal printed as a negation is never a positive crew action (MAY NOT / WILL NOT included).
_NEGATION = r"(?:(?:SHALL|MUST|SHOULD|WILL|MAY|CAN|DO|DOES|ARE|IS)\s+NOT|CANNOT|NOT\s+TO|NEVER)"
_FAMILY_VERBS = r"(?:SEEK|REQUEST|REQ|OBTAIN|ASK FOR|CONFIRM|VERIFY|ACCEPT|REFUSE|DECLINE|REJECT|DISREGARD|IGNORE)"


def _unit_request(recipient: str) -> str:
    """A request, clarification or confirmation addressed to RECIPIENT ("SEEK CLARIFICATION FROM NICOSIA CONTROL")."""
    return (r"(?:SEEK|REQUEST|REQ|OBTAIN|ASK FOR|CONFIRM|VERIFY)\s+(?:(?!(?:FROM|FM|WITH|TO)\b)[A-Z][A-Z/-]*\s+){0,4}"
            r"(?:FROM|FM|WITH|TO)\s+" + _RECIPIENT_WORDS + recipient + r"\b")


# The structural form, satisfied by any authority or call sign: it reads an unmodalled requesting subject and splits a
# list item; it admits nothing (admission needs the ATC evidence above).
_UNIT_REQUEST = _unit_request(r"(?:" + _ATC_AUTHORITY + r"|[A-Z][A-Z-]*\s+" + _CALL_SIGN + r")")
# A communication instruction, by its own printed verb and object: contact /
# CTC / call a unit or a frequency as an obligation or imperative (a state
# such as "in positive contact with" is not), establish or maintain contact,
# report a position, monitor a frequency; comply with TIBA, broadcast (as an
# obligation) or transmit; logon; CPDLC / ADS-C. A reference to TIBA
# procedures, a broadcast made by the ground, a phone number to call, a
# monitoring a navigation selection alone is not a communications duty.
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
_KIND_RANK = {"voice_contact": 0, "tiba_broadcast": 1, "contact_logon": 2, "atc_duty": 3, "datalink_other": 4}
_STATE_RANK = {"conditions_held": 0, "conditions_unresolved": 1, "not_applicable": 2}
# Source service status is retained as communications evidence. These words
# classify the quotation; they do not supply a substitute crew instruction.
_COMMUNICATION_SERVICE = re.compile(r"\b(?:CPDLC|ADS-C|DATA[ -]?LINK|COM|COMMUNICATIONS?|HF|VHF|UHF|SATCOM|SELCAL|RCO|DRCO|RADIO(?! ALTIMETER| NAVIGATION| BEACON)|EMERGENCY|GUARD|A/G FAC)\b|\b(?:ACC|FIC|CENTRE|CENTER|ARTCC)\b.{0,180}\b(?:FREQ(?:UENCY)?|\d{2,3}\.\d{1,3}\s*MHZ)\b")
_SERVICE_STATUS = re.compile(r"\b(?:NOT (?:BE )?(?:AVBL|AVAILABLE)|UN[- ]?(?:AVBL|AVAILABLE|SERVICEABLE|SERVICEABILITY)|UNMONITORED|WITHDRAWN|SUSPENDED|OUT OF SERVICE|LIMITED (?:RADIO )?COVERAGE|SUBJ(?:ECT)? TO (?:INTRP|INTERRUPTION))\b|\bU/S\b")
# Equipment plus an obligation/restriction, never surveillance coverage alone.
_NONVOICE_EQUIPMENT = re.compile(r"\b(?:SSR|IFF|TRANSPONDERS?|ADS-B OUT EQUIPAGE)\b")
_NONVOICE_DIRECTIVE = re.compile(r"\b(?:SHALL|MUST|SHOULD|ARE REQUIRED TO|IS REQUIRED TO|NOT REQUIRED TO|(?:ARE|IS) NOT PERMITTED|(?:ARE|IS) (?:TEMPORARILY )?PROHIBITED)\b")
_OPERATING_SUBJECT = re.compile(r"\b(?:FLIGHT CREWS?|AIR CREWS?|CREWS?|PILOTS?|FLIGHTS?|FLTS?|ACFT|AIRCRAFT|AFCT|OVERFLIGHTS?|TFC|TRAFFIC)\b")
_OPERATING_DIRECTIVE = re.compile(r"\b(?:SHALL|MUST|SHOULD|ARE REQUIRED TO|IS REQUIRED TO|(?:ARE|IS) NOT PERMITTED TO|(?:ARE|IS) (?:TEMPORARILY )?PROHIBITED FROM)\s+(?:(?:NOT|CONTINUE TO|BE|FLT|FLIGHT)\s+)*(?:SQUAWK(?:ING)?|OPERAT(?:E|ED|ING)|DISPLAY(?:ED)?|CHANGE|MAINTAIN|FLY|ENTER(?:ING)?|DEPART(?:ING)?|CROSS|FOLLOW|AVOID|FILE|PLANNED|HAVE|REMAIN|BE CAPABLE OF CRUISING|APPROVED|COORDINATE|ON|IN)\b")
_OPERATING_TARGET = re.compile(r"^(?:(?:THEIR|ITS|THE|A|AN|ASSIGNED|CRUISING|LAST|NEW|PUBLISHED|MANDATORY|CURRENT|REQUIRED|WI|WITHIN|IN|ON|VIA|ABOVE|BELOW|OVER|WITH|BY|AT|HIGH|LOW|AND|SECTORS?)\s+)*(?:SSR|IFF|TRANSPONDERS?|ADS-B|(?:FLIGHT|FLT) LEVELS?|FL\d{2,3}|ALTITUDE|IAS|MACH|IAS\/MACH|ATS|ATC|TIBA|FIRS?|AIRSPACE|AERODROMES?|RUNWAYS?|RWY|ROUTES?|RTE|FPLS?|FLT PLAN|FLIGHT PLAN|WRA|TSA|TRA|NAVIGATION LIGHTS|ANTI-COLLISION LIGHTS|M\d{3}|MACH \d(?:\.\d+)?|TWO-WAY (?:RADIO )?(?:COMMUNICATIONS?|COM) WITH (?:ATC|ATS)|(?:AD|AERODROME|ATC|ATS) WATCH SUPERVISOR|(?:ACTIVE|FILED) (?:IFR|VFR)(?: OR (?:A )?(?:ACTIVE|FILED) (?:IFR|VFR))? (?:FPL|FLT PLAN|FLIGHT PLAN)|(?:[A-Z][A-Z0-9-]*\s+){1,4}(?:FIRS?|AIRSPACE))\b")
_ATC_SERVICE = re.compile(r"^(?:ATS|AIR TRAFFIC SERVICES?|AIR TRAFFIC CONTROL)\b")
_ATC_SERVICE_STATUS = re.compile(r"\b(?:NOT (?:BE )?(?:AVBL|AVAILABLE|PROVIDED)|UN[- ]?(?:AVBL|AVAILABLE))\b")
_PRIOR_ATS_APPROVAL = re.compile(r"\b(?:EXEMPTION|APPROVAL|PERMISSION)\b.{0,100}\bPRIOR (?:COOR|COORDINATION|APPROVAL)\b.{0,100}\b(?:ATS|ATC)\b")
_PRINTED_RADIO_ADVICE = re.compile(r"\bCHECK (?:ACT|ACTIVITY) WITH\b.{0,100}\b(?:APP|FIC|ACC|ATC)\b|\b(?:ADVICE|ADVISE|ADVISED)\s+(?:TO\s+)?(?:CTC|CONTACT)\s+(?:[A-Z]+\s+){0,4}(?:ACC|ATC|CONTROL|RADIO|FIR)\b|\bTRY\s+(?:ALTN|ALTERNATE)\s+FREQ(?:UENCY)?\b|\b(?:DISREGARD\s+(?:ANY\s+)?(?:NON-STANDARD|SUSPICIOUS)\s+(?:OR\s+SUSPICIOUS\s+)?CALLS|VERIFY\s+AUTHENTICITY\s+OF\s+ATS\s+INSTRUCTIONS|MAINTAIN\s+STRICT\s+ADHERENCE\s+TO\s+ASSIGNED\s+FREQUENCIES)\b")
_ATC_RECIPIENT = re.compile(r"\b(?:ATC|AIR TRAFFIC CONTROL)\s+(?:SHALL|MUST|SHOULD)\s+BE\s+INFORMED\b")
_ATC_REPORT = re.compile(r"\b(?:REPORT(?:ING)?|REP|INFORM|ADVISE|NOTIFY)\b.{0,300}\b(?:ATC|AIR TRAFFIC CONTROL|AIR TRAFFIC SERVICES|ATS UNIT|ATSU|ATS)\b|\b(?:ATC|AIR TRAFFIC CONTROL)\s+(?:SHALL|MUST|SHOULD)\s+BE\s+INFORMED\b|\bMAKE ATC AWARE\b")
_RETIRED_REPORT = re.compile(r"\b(?:NO LONGER|NOT) REQUIRED TO SEND\b.{0,100}\b(?:POSITION|PSN) REPORT\b|\b(?:WO|WITHOUT) THE REQUIREMENT FOR VOICE (?:POSITION|PSN) (?:REPORT|REP)\b|\b(?:POSITION|PSN) REPORT(?:ING)?\b.{0,60}\b(?:WITHDRAWN|NO LONGER REQUIRED)\b")
_REPORT_EVENT = re.compile(r"\b(?:GNSS (?:INTERFERENCE|JAMMING|SPOOFING)|RADIO ALTIMETER ANOMALIES|UNAUTHORIZED RADIO TRANSMISSIONS|SUSPICIOUS CALLS|VOLCANIC ASH|SIGHTING|ENCOUNTER|OCCURRENCE)\b")
_REFERENTIAL_REPORT_EVENT = re.compile(r"\b(?:SUCH|THIS|THESE|THOSE|ANY) (?:INTERFERENCES?|ADVERSE IMPACTS?|ANOMALIES|OCCURRENCES?)\b")
_NEGATED_FAMILY = re.compile(r"\b" + _NEGATION + r"\s+" + _FAMILY_VERBS + r"\b")
# An act inside a qualifying clause ("ACFT THAT CANNOT OBTAIN CLEARANCE FROM ... ACC SHALL HOLD") qualifies the population;
# it is neither the sentence's own act nor its refusal. A relative clause (THAT / WHICH / WHO) owns the verb group
# directly after its opener; a conditional (IF / WHEN ...) with a subject owns its first modal, a verbless one ("WHEN
# ENTERING ...", "IF UNABLE ...") none. A further modal opens the main clause ("PILOTS WHO OPERATE HERE MAY NOT ACCEPT").
_QUALIFYING_CLAUSE = re.compile(r"\b(?:THAT|WHICH|WHO|IF|WHEN|WHENEVER|UNLESS|WHILE|WHERE)\b")
_RELATIVE_OPENERS = {"THAT", "WHICH", "WHO"}
_ANY_MODAL = re.compile(r"\b(?:SHALL|MUST|SHOULD|WILL|MAY|CAN|CANNOT|ARE|IS|WERE|WAS|DO|DOES|NEED|HAVE|HAS)\b")
_VERBLESS_CONDITION = re.compile(r"(?:[A-Z-]+(?:ING|ED)|UNABLE|ABLE|IN|AT|ON|WITHIN|WI|REQUIRED|NECESSARY|APPROPRIATE|PRACTICABLE|POSSIBLE|NOT|SO|OTHERWISE)\b")
# An action that points back to clearances or instructions its own notice describes ("DO NOT ACCEPT THESE CLEARANCES").
_REFERENTIAL_CLEARANCE = re.compile(r"\b(?:SUCH|THIS|THESE|THOSE|SAID)\s+(?:[A-Z-]+\s+){0,2}?(?:CLEARANCES?|INSTRUCTIONS?)\b")
_NEGATED_CALL = re.compile(r"\b(?:(?:ARE|IS)\s+)?NOT REQUIRED TO\s+(?:CONTACT|CTC|CALL|LOGON|BROADCAST|MONITOR|TRANSMIT|REPORT|REP|INFORM|NOTIFY|ADVISE|SEEK|REQUEST|REQ|OBTAIN|ASK FOR|CONFIRM|VERIFY|ACCEPT)\b")
_PROHIBITED_CALL = re.compile(r"\b(?:SHALL|MUST|SHOULD|WILL|MAY|DO|DOES)\s+NOT\s+(?:CONTACT|CTC|CALL|LOGON|BROADCAST|MONITOR|TRANSMIT|REPORT|REP|INFORM|NOTIFY|ADVISE)\b")
# MAY NOT prohibits a printed act, not possible inability.
_NONVOICE_PROHIBITION = re.compile(r"\b(?:NOT PERMITTED|PROHIBITED|SHALL NOT|MUST NOT|DO NOT)\b|\bMAY NOT\s+(?:BE\s+)?(?:SQUAWK(?:ING)?|OPERAT(?:E|ED|ING)|DISPLAY(?:ED)?|USE(?:D)?|CHANGE(?:D)?|MAINTAIN(?:ED)?|FLY|FLOWN|ENTER(?:ED|ING)?|DEPART(?:ED|ING)?|CROSS(?:ED)?|FOLLOW(?:ED)?|AVOID(?:ED)?|FILE(?:D)?|HAVE|REMAIN|CONTINUE)\b")
# A sentence ends at "." or ";" after a word of two or more characters; a list
# marker ("A.", "1.") and a unit abbreviation ("MIN.", "HRS.") do not end one.
_SENTENCE_SPLIT = re.compile(r"(?<=\S\S[.;])\s+")
# A stop printed with no space before the next word ("NICOSIA AIRSPACE.DO NOT ACCEPT", "NICOSIA CONTROL.REF PGS") ends a
# sentence too when that word is followed by a space (ATC-CLEARANCE-FAMILY, 1 Oct 2026). A dotted address never does: a
# run holding "://", "@", "(AT)", a leading "WWW.", two or more dots, or a generic top-level domain label ("WWW.TSA.GOV
# FOR", "JATSC.CO.ID FOR", "FAA.GOV FOR"); nor a unit abbreviation ("MIN.").
_JOINED_STOP = re.compile(r"(?<=[A-Z]{2})[.;](?=([A-Z][A-Z'-]*)\s)")
_ADDRESS_LABELS = {"GOV", "COM", "ORG", "NET", "INT", "EDU", "MIL", "AERO", "INFO"}
_ABBREVIATION = re.compile(r"\b(?:MIN|MINS|HR|HRS|NM|FT|SEC|SECS|KT|KTS|DEG|APPROX)\.$")
_FREQUENCY = re.compile(r"\b\d{2,5}(?:\.\d{1,3})? ?(?:MHZ|KHZ)\b")
# A navigation aid's own frequency identifies the aid ("VORTAC SOT 116.900MHZ/CH116X U/S", "TRANG DVOR/DME (TRN) FREQ
# 116.6 MHZ, CH113X", "NDB (L) LCY 322.000 KHZ U/S"); it is never a communication frequency the crew calls on.
_NAVAID_FREQUENCY = re.compile(
    r"\b(?:D?VOR(?:/DME)?|VORTAC|TACAN|NDB|DME|ILS|LOC|LLZ)\b(?:\s*\([A-Z]{1,3}\))?(?:\s+[A-Z]{2,3})?(?:\s*\([A-Z]{2,3}\))?(?:\s+FREQ(?:UENCY)?)?\s+(?P<frequency>\d{2,5}(?:\.\d{1,3})? ?(?:MHZ|KHZ))\b"
    r"|\b(?P<channelled>\d{2,5}(?:\.\d{1,3})? ?(?:MHZ|KHZ))\s*[/,]\s*CH ?\d{1,3}[XY]\b")
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
# An airway-only route list ("ALL ACFT VIA RTE B346, R474, W21 AND G473 ..."): no waypoint is printed, so the list is read
# against the airways the OFP files inside the notice's own FIR (ATC-PDF-PRIORITY, 2 Oct 2026).
_AIRWAY = r"[A-Z]{1,2}\d{1,3}"
_AIRWAY_EXCEPTION = re.compile(r"\b(?:EXC|EXCEPT|EXCEPTING|EXCLUDING|OTHER THAN|NOT|UNLESS|OUTSIDE|BEYOND|AVOID(?:ING)?)\b")
_AIRWAY_LIST = re.compile(r"\b(?:VIA|ON|ALONG|USING)\s+(?:ATS\s+)?(?:RTES?|ROUTES?|AWYS?|AIRWAYS?)\s+"
                          rf"({_AIRWAY}(?:\s*(?:,|/|&|\bAND\b|\bOR\b)\s*{_AIRWAY})*)\b")
# Printed logon addresses: "USE LOGON ADDRESS PAZN", "THE AFN LOGON ADDRESS FOR JAKARTA FIR IS WIIF", "LOGON TO KZAK".
_ADDRESS = re.compile(r"\bLOGON ADDRESS(?:ES)?(?: FOR [A-Z][A-Z ]*? FIR)?(?: IS| ARE)? ([A-Z]{4})\b|\bLOG ?ON TO ([A-Z]{4})\b")
_ADDRESS_STOPWORDS = {"WHEN", "WITH", "THAT", "THIS", "FROM", "INTO", "OVER", "ONLY", "ALSO", "THEN", "THEM", "THEY", "WILL", "BASED", "UPON", "EACH", "BOTH", "SAME", "MUST", "SHALL"}
# ATC-EARLY-CALLS (v17): the unit a call instruction names, in the source's own words - the words after the call verb
# up to the first frequency, timing, place or clause word ("CTC KARACHI, LAHORE OR ISLAMABAD ACC AT LEAST ..." ->
# "KARACHI, LAHORE OR ISLAMABAD ACC"; "ESTABLISH CON TACT WITH TURKMENABAT-CTL ON 134.5 MHZ" -> "TURKMENABAT-CTL").
_CALL_UNIT = re.compile(
    r"\b(?:CONTACT|CTC|CALL|LOG ?ON (?:TO|WITH)|ESTABLISH (?:TWO-WAY )?(?:RADIO )?(?:CON ?TACT|COMMUNICATIONS?|COM) WITH)"
    r" (?P<unit>(?:(?!(?:ON|AT|NOT|WI|WITHIN|IN|BEFORE|PRIOR|AS|VIA|FOR|WHEN|IF|NO|BY|FREQ|FREQUENCY|UPON|AND|TO|FM|FROM|UNTIL)\b)"
    r"[A-Z][A-Z/'-]*,? ?){1,6})")
# A lead measured from the take-off or the departure is not a lead before a FIR entry: no FIR clock derives from it.
_TAKEOFF_LEAD = re.compile(r"\b(?:TAKE-?OFF|DEPARTURE)\b")
CALL_ACTIONS = {"voice_contact": "Contact", "tiba_broadcast": "TIBA broadcast", "contact_logon": "Logon"}
# A sentence's own crew subject, its qualifiers and the modal that ends them:
# "IFR AFCT FLT PLANNED TO DEP CYMM/OILSANDS UNABLE TO CTC ... SHOULD CTC ...".
_LIST_MARKER = r"(?:\(?[A-Z]\)?[.)]\s+|\d{1,2}[.)]\s+|-\s*)?"
# A population's qualifying prefixes: flight rules, and equipment named with or without EQUIPPED / PACKAGE
# ("FANS 1/A, PACKAGE AIRCRAFT", "ADS-B EQUIPPED ACFT", "DATA LINK - EQUIPPED AIRCRAFT"); items may be comma-separated.
_EQUIPMENT_FORMS = r"FANS[- ]?1/A(?:[ ,]+(?:PACKAGE|EQUIPPED|CAPABLE))?|DATA[- ]?LINK\s*-?\s*EQUIPPED|ADS-[BC](?:[- ]EQUIPPED)?|CPDLC(?:[- ]EQUIPPED)?|APPROPRIATELY EQUIPPED|SUITABLY EQUIPPED|EQUIPPED"
# A navigation specification qualifies the population as equipment does ("NON-RNAV ACFT", "RNP 10 ACFT"); the OFP does not
# say which this aircraft holds, so it stays an unresolved population (ATC-CLEARANCE-FAMILY, 1 Oct 2026).
_NAV_SPEC = r"(?:NON-)?(?:RNAV|RNP|PBN)(?: ?\d{1,2}(?:\.\d)?)?"
_SUBJECT_PREFIX = r"(?:(?:ALL|ANY|EVERY|IFR|VFR|MILITARY|CIVIL|NON-RVSM|RVSM|" + _NAV_SPEC + r"|" + _EQUIPMENT_FORMS + r")\s*,?\s+)*"
# Read the whole compound subject before its aircraft abbreviation; CREWS is the actor, not a population qualifier.
_SUBJECT_NOUN = r"(?:(?:AIRCRAFT|ACFT|AFCT) CREWS?|FLIGHT CREWS?|AIR CREWS?|THE PILOTS?|THE CREWS?|FLIGHTS?|FLTS?|ACFT|AIRCRAFT|AFCT|TFC|TRAFFIC|OVERFLIGHTS?|PILOTS?|CREWS?|OPERATORS?|AIRLINES?|PERSONS?|USERS?)(?:\s+(?:FLT|FLIGHTS?|OPERATIONS?|OPS|OPERATORS?))?"
_SUBJECT = re.compile(r"^" + _LIST_MARKER + r"(?P<prefix>" + _SUBJECT_PREFIX + r")(?P<noun>" + _SUBJECT_NOUN + r")\b(?P<qualifier>.*?)\s*\b(?P<modal>SHALL|MUST|SHOULD|WILL|MAY|CAN|ARE|IS|NEED|HAVE|HAS)\b")
# A headline AIR CREWS TO REPORT directive is not the infinitive within an
# ACFT UNABLE TO CTC ... SHOULD CTC qualifier. Prefer the finite modal, then
# accept an abbreviated TO directive only directly after its subject.
_SUBJECT_TO = re.compile(r"^" + _LIST_MARKER + r"(?P<prefix>" + _SUBJECT_PREFIX + r")(?P<noun>" + _SUBJECT_NOUN + r")\b(?P<qualifier>)\s+(?P<modal>TO)(?= (?:REMAIN|REPORT|REP|INFORM|NOTIFY|CONTACT|CTC|BROADCAST|MONITOR|TRANSMIT)\b)")
# A direct pilot/crew report can omit a modal. Read only the explicit
# headline subject and manner, not a pilot noun in another actor's object.
_REPORTING_SUBJECT = re.compile(r"^" + _LIST_MARKER + r"(?P<prefix>" + _SUBJECT_PREFIX + r")(?P<noun>(?:(?:AIRCRAFT|ACFT|AFCT|FLIGHT|AIR) CREWS?|(?:THE )?(?:PILOTS?|CREWS?)))\b(?P<qualifier>)\s+(?:(?:PROMPTLY|IMMEDIATELY)\s+)?(?P<modal>)(?=(?:REPORT|REP|INFORM|NOTIFY|ADVISE)\b)")
_EMBEDDED_SUBJECT = re.compile(r"\b(?P<prefix>" + _SUBJECT_PREFIX + r")(?P<noun>" + _SUBJECT_NOUN + r")\b(?P<qualifier>.*?)\s*\b(?P<modal>SHALL|MUST|SHOULD|WILL|MAY|CAN|ARE|IS|NEED|HAVE|HAS)\b")
_JOINED_CREW_SUBJECT = re.compile(r"\s+(?=" + _SUBJECT_PREFIX + _SUBJECT_NOUN + r"\b[^.;]*?\b(?:SHALL|MUST|SHOULD|WILL|MAY|CAN|ARE|IS|NEED|HAVE|HAS)\b)")
_IMPERATIVE_VERBS = (r"(?:USE|SELECT|CONTACT|CTC|CALL|MONITOR|LOGON|LOG ON|BROADCAST|REPORT|REP|INFORM|MAINTAIN|ESTABLISH|COMPLY|SQUAWK|TRANSMIT|NOTIFY"
                     r"|REFER|ADVISE|REQUEST|REQ|SEEK|OBTAIN|ASK|CONFIRM|VERIFY|ACCEPT|NEVER|DISREGARD|REFUSE|DECLINE|REJECT|IGNORE|EXPECT|FILE|OPERATE|AVOID|DO NOT|CONTINUE|PROCEED|REMAIN)")
_IMPERATIVE = re.compile(r"^" + _LIST_MARKER + _IMPERATIVE_VERBS + r"\b")
# A crew population requesting from a unit can omit a modal ("NON-RNAV ACFT REQ RADAR VECTOR TO DAEGU/INCHEON ACC").
_REQUESTING_SUBJECT = re.compile(r"^" + _LIST_MARKER + r"(?P<prefix>" + _SUBJECT_PREFIX + r")(?P<noun>" + _SUBJECT_NOUN + r")\b(?P<qualifier>)\s+(?P<modal>)(?=" + _UNIT_REQUEST + r")")
# Two statements printed as one sentence (ATC-CLEARANCE-FAMILY, 1 Oct 2026): a crew directive coordinated with a further
# conditional instruction ("DO NOT ACCEPT THESE CLEARANCES AND IF CONTENTION EXISTS ,SEEK CLARIFICATION FROM NICOSIA
# CONTROL."), and an unpunctuated list item opening its own crew request ("... CRITICAL DME 3. NON-RNAV ACFT REQUEST
# RADAR VECTOR TO DAEGU / INCHEON ACC ..."). Each keeps its own effect and conditions; both quotations are source spans.
_COORDINATED_CONDITION = re.compile(r"\s+AND\s+(?=(?:IF|WHEN|WHENEVER|IN CASE(?: OF)?|IN THE EVENT OF)\b[^,.;]{3,120}?\s*,\s*" + _IMPERATIVE_VERBS + r"\b)")
_REQUEST_ITEM = re.compile(r"\s+(?=\d{1,2}[.)]\s+" + _SUBJECT_PREFIX + _SUBJECT_NOUN + r"\b\s+(?:(?:SHALL|MUST|SHOULD|WILL|MAY|ARE TO|IS TO)\s+)?" + _UNIT_REQUEST + r")")
# The circumstance words a leading clause opens with (the ICAO abbreviation DRG included - release-430 QA, audit of SQ23 SX33/26).
_LEADING_OPENERS = r"WHENEVER|WHEN|IF|WHILE|UNLESS|IN CASE(?: OF)?|IN THE CASE OF|IN THE EVENT OF|AFTER|BEFORE|DURING|DRG|PROVIDED|WHEREVER|WHERE|AS LONG AS"
# A comma-ended literal date qualifies the following subject. Keep it as
# an unresolved clause; recognizing its syntax does not prove its calendar.
_LITERAL_DATE_PREFIX = r"ON (?:0?[1-9]|[12]\d|3[01]) (?:" + "|".join(_MONTHS) + r")(?: \d{2}(?:\d{2})?)?"
# An exception printed before its statement and closed by a colon ("EXC AS SPECIFIED BLW AND/OR UNLESS AUTH BY ATC ...: A.
# ALL ACFT OPS ... ARE PROHIBITED") leads that statement as a circumstance does (ATC-CLEARANCE-FAMILY review, 1 Oct 2026).
_LEADING_CLAUSE = re.compile(r"^" + _LIST_MARKER + r"(?P<clause>(?:(?:" + _LEADING_OPENERS + r")\b[^,]{3,120}|" + _LITERAL_DATE_PREFIX + r")(?=,)"
                             r"|(?:EXCEPT|EXC)\b[^,:;.]{3,200}(?=:))[,:]\s*")
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
_CREW_ACT_SUBJECT = re.compile(r"^" + _LIST_MARKER + r"(?P<noun>(?:THE\s+)?(?:CALL ?SIGNS?|FLIGHT IDENTIFIERS?|AIRCRAFT REGISTRATIONS?|NOTIFICATIONS?|CONTACTS?|LOG-?ONS?|POSITION REPORTS?|REPORTS?|REQUESTS?|CALLS?|BROADCASTS?|MESSAGES?|TRANSMISSIONS?|COMMUNICATIONS?|READ-?BACKS?)(?:\s+(?:TO|WITH|OF|FOR|VIA|ON)\s+[A-Z0-9/-]+)?)\s+\b(?:SHALL|MUST|SHOULD|WILL|MAY|CAN|ARE|IS|NEED|HAVE|HAS)\b")
_CREW_ACT_NOUN = re.compile(r"^(?:THE\s+)?(?:CALL ?SIGNS?|FLIGHT IDENTIFIERS?|AIRCRAFT REGISTRATIONS?|NOTIFICATIONS?|CONTACTS?|LOG-?ONS?|POSITION REPORTS?|REPORTS?|REQUESTS?|CALLS?|BROADCASTS?|MESSAGES?|TRANSMISSIONS?|COMMUNICATIONS?|READ-?BACKS?)\b")
# A qualification of the aircraft population anywhere in a sentence's body (F1 of the release-424 independent QA,
# 24 Sep 2026): a crew noun introduced by a population connector and followed by a restrictive modifier - "BTN ADS-B
# EQUIPPED ACFT THAT ARE CORRELATED WITH CPL ...", "FOR ACFT DEPARTING RJTT", "TO FLIGHTS UNABLE TO LOGON". It is
# evaluated exactly like a subject qualifier; an object mention without a modifier ("REPORT ANY ACFT") is not one.
_POPULATION_MODIFIER = r"(?:THAT|WHICH|WHO|EQUIPPED|CORRELATED|OPERATING|OPTG|OPERATED|PLANNED|PLANNING|FLYING|ENTERING|LEAVING|DEP(?:ARTING)?|ARRIVING|TRANSITING|OVERFLYING|CROSSING|HAVING|CAPABLE|ABLE|UNABLE|NOT|IN POSITIVE|IN CONTACT|IN CTC|WITH|WITHOUT|WITHIN|WI|INSIDE|OUTSIDE|USING|CONDUCTING|MAINTAINING|EXPERIENCING|LOGGED|BOUND|INBOUND|OUTBOUND|REQUESTING|INTENDING|EXPECTING|CLEARED|APPROACHING|HOLDING|PROCEEDING|ROUTING|CARRYING)"
_CREW_QUALIFIER_START = re.compile(r"^(?:" + _POPULATION_MODIFIER + r"|VIA|FLW|F(?:RO)?M|TO|IN|AT|ON|AND|OR)\b|^\(")
_POPULATION = re.compile(
    r"\b(?:BTN|BETWEEN|FOR|TO|OF|BY|APPLICABLE TO|APPLIES TO|APPLY TO|ONLY (?:TO|FOR)|AVAILABLE TO|PROVIDED TO)\s+"
    r"(?:(?:ALL|ANY|EVERY|THE|THOSE|SUCH)\s+)?(?P<prefix>" + _SUBJECT_PREFIX + r")(?P<noun>" + _SUBJECT_NOUN + r")\b"
    r"(?:\s+(?P<modifier>" + _POPULATION_MODIFIER + r"\b[^.;]*?)(?=\s+\b(?:SHALL|MUST|SHOULD|WILL|MAY|ARE TO|IS TO)\b|[.;]|$))?")
_RELATIVE_OPENING = re.compile(r"^(?:THAT|WHICH|WHO)\s+(?:ARE|IS|WERE|WAS)?\s*")
# Who acts. A sentence directing the crew (a crew subject with a modal, an imperative, a continuation of one) is a
# crew action. A sentence whose actor is ATC - a service, a separation, a procedure applied or provided, a centre or
# its automation - is an ATC provision: still held with its conditions, never presented as a required crew call.
_CREW_DIRECTIVE = re.compile(r"\b(?:" + _SUBJECT_NOUN + r")\b[^.;]*?\b(?:SHALL|MUST|SHOULD|ARE (?:REQUESTED|REQUIRED|EXPECTED) TO|IS (?:REQUESTED|REQUIRED|EXPECTED) TO|ARE TO|IS TO|NEED TO)\b")
# The HEAD of the subject noun phrase (its last word before the first preposition) names the actor: "OPPORTUNITY BASED
# APPLICATION OF ..." → APPLICATION, "ARTCC AUTOMATION" → AUTOMATION, "THE CALL SIGN TO BE USED ..." → SIGN (the crew's).
_HEAD_STOP = re.compile(r"\b(?:OF|ON|IN|FOR|TO|WITH|AT|BY|FROM|WITHIN|WI|BETWEEN|BTN|VIA|UNDER|OVER)\b")
# A source provenance block folded into a sentence - an AIP SUP / NOTAM reference with its validity - is set aside
# for the grammatical analysis only; the printed sentence keeps the source wording (release-428 QA, F1).
_PROVENANCE = re.compile(r"^(?:[A-Z]{1,2}\d{1,4}/\d{2}\s+)?AIP\s+SUP(?:PLEMENT)?\b(?:\s+NR\s+\S+)?(?:\s+[A-Z]{4}/[A-Z' .()-]*?\s+FIRS?)?\s+VALIDITY:?\s*\d{2}[A-Z]{3}\d{2,4}\s*-\s*(?:\d{2}[A-Z]{3}\d{2,4}|UFN|PERM)\s*")
# The phrase before a sentence's first modal / finite verb, for a subject the anchored patterns did not read.
_PRE_MODAL = re.compile(r"^(?P<phrase>.+?)\s+\b(?:SHALL|MUST|SHOULD|WILL|MAY|CAN|ARE|IS|NEED|HAVE|HAS|APPLY|APPLIES|DOES|DO)\b")
_CREW_ACT_HEADS = {"NOTIFICATION", "NOTIFICATIONS", "CONTACT", "CONTACTS", "LOGON", "LOGONS", "LOG-ON", "LOG-ONS", "REPORT", "REPORTS", "REQUEST", "REQUESTS", "CALL", "CALLS", "BROADCAST", "BROADCASTS", "MESSAGE", "MESSAGES", "TRANSMISSION", "TRANSMISSIONS", "COMMUNICATION", "COMMUNICATIONS", "READBACK", "READBACKS", "READ-BACK", "READ-BACKS"}
_ATC_HEADS = {"ATC", "ATS", "ACC", "ARTCC", "ATSU", "CENTRE", "CENTER", "CONTROL", "CTL", "AUTOMATION", "SERVICE", "SERVICES",
              "SEPARATION", "APPLICATION", "PROVISION", "SURVEILLANCE", "RADAR", "UNIT", "STATION", "FACILITY", "TOWER", "APP",
              "APPROACH", "FIS", "AFTN"}
# A service applied or provided (the strict passive), or an agent phrase naming ATC ("... ENDEAVOURED BY ATC", "... BY THE ATSU").
_SERVICE_PASSIVE = re.compile(r"\b(?:SHALL|WILL|MAY|IS|ARE)\s+(?:(?!BE\b)[A-Z]+\s+){0,2}BE\s+(?:APPLIED|PROVIDED|AVAILABLE|OFFERED|IMPLEMENTED|CONDUCTED|ESTABLISHED|MAINTAINED|EXERCISED|ENDEAVOURED)\b|\bIS\s+(?:[A-Z]+\s+)?(?:AVAILABLE|PROVIDED)\b")
# An agent phrase naming the crew keeps a passive sentence the crew's ("... SHALL BE APPLIED BY ALL AIRCRAFT").
_CREW_AGENT = re.compile(r"\bBY\s+(?:ALL\s+|THE\s+|EACH\s+)?(?:AIRCRAFT|ACFT|AFCT|PILOTS?|CREWS?|FLIGHT CREWS?|FLIGHTS?|OPERATORS?|TRAFFIC|TFC)\b")
_PASSIVE_CREW_CONTROL = re.compile(r"\b(?:TRANSPONDERS?|(?:NAVIGATION|ANTI-COLLISION|POSITION)(?: AND (?:NAVIGATION|ANTI-COLLISION|POSITION))? LIGHTS)\s+(?:SHALL|MUST|SHOULD)\s+BE\s+(?:OPERATED|DISPLAYED|ON|ACTIVE|ACT|OPN)\b|\b(?:CLIMBS?|DESCENTS?)(?: AND (?:CLIMBS?|DESCENTS?))? (?:SHALL|MUST|SHOULD) BE (?:CARRIED OUT|CONDUCTED|PERFORMED)\b")
_PASSIVE_NAMED_AGENT = re.compile(r"\b(?:SHALL|MUST|SHOULD|WILL|ARE|IS)\s+(?:[A-Z-]+\s+){0,2}BE\s+(?:[A-Z-]+(?:ED|EN)|SENT)\s+BY\s+(?:THE\s+|ALL\s+)?[A-Z][A-Z-]*(?:\s+[A-Z][A-Z-]*)*")
_ATC_AGENT = re.compile(r"\bBY (?:THE )?(?:ATC|ATS|ACC|ARTCC|ATSU|GROUND SYSTEM|(?:[A-Z]+ ){0,2}(?:CENTRE|CENTER|CONTROL|CTL|OCEANIC|RADIO|APPROACH|TOWER))\b")
_DIRECTIVE = re.compile(r"\b(?:SHALL|MUST|SHOULD|WILL|MAY|ARE REQUESTED TO|IS REQUESTED TO|ARE REQUIRED TO|IS REQUIRED TO|ARE TO|IS TO|NEED TO|EXPECTED TO)\b")
_OBLIGATION_MODAL = re.compile(r"\b(?:SHALL|MUST|SHOULD|ARE REQUESTED TO|IS REQUESTED TO|ARE REQUIRED TO|IS REQUIRED TO|ARE TO|IS TO|NEED TO|EXPECTED TO)\b")
_MIXED_MODAL_SCOPE = "permission and obligation clause scope unresolved"
# Aerodrome restrictions inside a qualifier: "PLANNED TO DEP CYMM/OILSANDS", "ARR KJFK", "OPERATING TO/FROM WSSS".
_AIRPORT_CONDITION = re.compile(r"\b(?P<kind>DEP(?:ARTING|ARTURE)?(?: FROM)?|ARR(?:IVING|IVAL)?(?: AT| TO)?|LANDING AT|OPERATING (?:TO/FROM|TO OR FROM|TO|FROM|AT)|TO OR FROM|BOUND FOR)\s+(?P<icao>[A-Z]{4})\b(?:/[A-Z-]+)?")
_ICAO_STOPWORDS = {"FROM", "WITH", "THAT", "THIS", "INTO", "OVER", "WHEN", "ONLY", "ALSO", "THEN", "THEM", "THEY", "WILL", "SHALL", "MUST", "AREA", "ZONE", "SAME", "EACH", "BOTH", "NEXT", "LAST", "FIRS", "AIRP"}
# The scope / direction qualifiers other rules already evaluate: a qualifier made only of these adds nothing.
# A qualifier naming the FIR(s) it applies in ("OPERATING IN THE KABUL FIR", "WHEN ENTERING THE ANCHORAGE ARTCC PAZA FIR"): evaluated
# against the crossings the OFP prints and kept as an explicit condition (release-430 QA, F1) - never assumed met.
_FIR_SCOPE_QUALIFIER = re.compile(r"^(?:DEPARTING|LEAVING|ENTERING|TRANSITING|OPERATING (?:IN|WITHIN)|WITHIN|WI|INSIDE|IN|OVERFLYING)\s+(?P<names>(?:THE\s+)?(?:(?!(?:FIRS?|FM|FROM|TO|INTO)\b)[A-Z][A-Z/-]*\s+){0,4}?)FIRS?$")
_EVALUATED_QUALIFIER = re.compile(
    r"^(?:FLW\s+F(?:RO)?M\s+.+?\s+FIRS?\s+(?:TO|INTO)\s+.+?\s+FIRS?(?:\s+\(.*\))?"
    r"|ENTERING\s+.+?\s+FIRS?\s+F(?:RO)?M\s+.+?\s+FIRS?"
    r"|ARRIVING OR DEPARTING(?: FROM)? AERODROMES(?: IN (?:THE )?[A-Z]+ FIR)?"
    r"|DEPARTING(?: FROM)? AERODROMES(?: IN (?:THE )?[A-Z]+ FIR)?)$"
)
_EQUIPMENT_PREFIX = re.compile(r"\b(?:" + _EQUIPMENT_FORMS + r")\b")
_RULES_PREFIX = re.compile(r"\b(?:IFR|VFR)\b")
_ATC_REQUEST = re.compile(r"\b(?:AS|WHEN|IF|WHERE) (?:SO )?REQUESTED BY ATC\b|\bON (?:ATC |CONTROLLER )?REQUEST\b|\bAT (?:ATC|CONTROLLER)(?:'S)? DISCRETION\b|\b(?:WHEN|IF|AS|UNLESS OTHERWISE) INSTRUCTED(?: BY ATC)?\b")
_OVERFLIGHT = re.compile(r"\bOVERFLIGHTS?\b|\bOVERFLYING\b|\bTRANSIT(?:ING)?\b")
_AERODROME = re.compile(r"\bAERODROMES?\b|\bTAKE-?OFF\b|\bLANDING\b|\bARRIVAL AND DEPARTURE\b|\bARRIVING OR DEPARTING\b|\bAPPROACH\b")
_FIR_EXIT = re.compile(r"\bDEPARTING (?:THE )?(?:[A-Z]+ )?FIR\b|\bLEAVING (?:THE )?(?:[A-Z]+ )?FIR\b|\bNEXT FIR\b")
_FIR_ENTRY = re.compile(r"\bENTERING\b|\bENTRY\b|\bENTRANCE\b")
_UNRESOLVED = re.compile(r"\bTEMPORARY PURPOSE\b|\bAS REQUIRED\b|\bUNLESS OTHERWISE\b|\bSUBJECT TO\b|\bWHEN INSTRUCTED\b")
# A population class the subject grammar accepts as a prefix: a qualification of its own (release-430 QA, F1).
_CLASS_PREFIX = re.compile(r"\b(?:MILITARY|CIVIL|NON-RVSM|RVSM|" + _NAV_SPEC + r")(?![A-Z0-9-])")

# ---- v7: an action's own sentence is accounted for before its state is computed (release-430 QA, F1)
#
# Every condition used to come from a recognizer for one grammatical position (the subject, a population connector, a
# leading or trailing clause) and the state was computed as if that list were complete: a restriction anywhere else -
# "CPDLC WILL BE USED AS COMMUNICATION WITHIN UBAC ON THE ROUTE PORTION M300, ... BEYOND VOICE VHF COVERAGE" - vanished.
# Now every span a recognizer consumed is set aside, the non-restrictive wording is typed (a reason, a manner, a timing,
# a means, a reference), and every restrictive phrase left becomes a condition: a named FIR scope evaluated against the
# printed crossings, a population prefix evaluated like a subject's, anything else an explicit unresolved restriction
# quoting the source. The accounting marker is NUL: never in the text, and not whitespace in either reader's regex.
_ACCOUNTED = "\x00"
_CIRCUMSTANCE = (r"WHENEVER|WHEN|IF|WHILE|UNLESS|IN CASE OF|IN THE CASE OF|IN THE EVENT OF|DURING|DRG|WHEREVER|WHERE|AS LONG AS|SUBJECT TO"
                 r"|OTHER THAN|EXCEPT(?! THAT\b)|EXC(?! THAT\b)|PROVIDED(?= (?:THAT|THE|A|AN|ALL|ANY|IT|THEY|THIS|SUCH|NO)\b)")
# A circumstance runs to a stop, a comma or the directive modal of the clause it qualifies ("... EXCEPT ON M875/L509 ROUTES SHALL USE ...").
_CIRCUMSTANCE_PHRASE = re.compile(r"\b(?:" + _CIRCUMSTANCE + r")\b(?:(?!\b(?:SHALL|MUST|SHOULD)\b)[^\x00;.,])*")
_CIRCUMSTANCE_OPENING = re.compile(r"^(?:" + _CIRCUMSTANCE + r")\s+")
# A reason ("AS THE GROUND SYSTEM USES THE INFORMATION DURING AFN LOGON", "DUE TO MAINT") qualifies nothing it contains. A causal
# AS needs an action verb: "AS THE AIRCRAFT IS WITHIN VHF COVERAGE" reads as a circumstance and stays one.
_REASON_PHRASE = re.compile(r"\b(?:BECAUSE(?: OF)?|DUE TO|OWING TO|AS A RESULT OF)\b[^\x00;.,]*"
                            r"|\bAS (?:THE|THIS|IT|THEY|THESE|THOSE)\s+(?:[A-Z/-]+\s+){0,3}?(?:USES|USE|REQUIRES|REQUIRE|NEEDS|NEED|RECEIVES|RECEIVE|PROCESSES|PROCESS|EXPECTS|EXPECT)\b[^\x00;.,]*")
# A manner, reference, addition, modification or emphasis; it stops before a circumstance, which stays one.
_MANNER_PHRASE = re.compile(r"\b(?:IN ACCORDANCE WITH|ACCORDING TO|AS PER|IN LIEU OF|IN ADDITION TO|EXCEPT THAT|WITH REFERENCE TO|WITH RESPECT TO|IN RESPECT OF"
                            r"|WHETHER|ESPECIALLY|PARTICULARLY|NOTABLY|IN PARTICULAR|INCLUDING)\b(?:(?!\b(?:" + _CIRCUMSTANCE + r")\b)[^\x00;.,])*")
# "CAN ONLY OCCUR AFTER THE AFN LOGON HAS BEEN COMPLETED": ONLY makes a timing a prerequisite.
_ONLY_TIMING = re.compile(r"\bONLY\b(?:\s+[A-Z-]+){0,3}?\s+(?:AFTER|BEFORE|UPON|ONCE|PRIOR TO|UNTIL)\b(?:(?!\b(?:SHALL|MUST|SHOULD)\b)[^\x00;.,])*")
# A timing of the action itself ("AFTER LANDING", "BEFORE CLIMBING ABV FL180", "UNTIL FURTHER NOTICE"); it stops before a
# spatial restriction, which stays one.
_TIMING_PHRASE = re.compile(r"\b(?:AFTER|BEFORE|BFR|PRIOR TO|UPON|ONCE|UNTIL|TIL)\b(?:(?!\b(?:WITHIN|WI|INSIDE|OUTSIDE|BEYOND|OUT OF)\b)[^\x00;.,:])*")
# Operating events do not prove a timestamp or cruise-level state.
_OPERATING_EVENT_TIMING = re.compile(r"^(?:AFTER|BEFORE|BFR|PRIOR TO|UPON|ONCE|UNTIL|TIL)\s+(?:THE\s+)?(?:DEP(?:ARTURE)?|ARR(?:IVAL)?|TAKE-?OFF|LANDING|CLIMB(?:ING)?|DESCENT|DESCEND(?:ING)?|FLY(?:ING)?)\b")
_PREFIXED_POPULATION = re.compile(r"\b(?P<prefix>(?:(?:" + _EQUIPMENT_FORMS + r"|IFR|VFR|MILITARY|CIVIL|NON-RVSM|RVSM|" + _NAV_SPEC + r")\s*,?\s+)+)(?P<noun>" + _SUBJECT_NOUN + r")\b")
_SPATIAL_OPENERS = (r"AT OR ABOVE|AT OR BELOW|OUT OF|(?:NORTH|SOUTH|EAST|WEST|NE|NW|SE|SW|N|S|E|W) OF|WITHIN|WI|INSIDE|OUTSIDE|BEYOND|THROUGH|THRU|ALONG|VIA"
                    r"|ABOVE|ABV|BELOW|BLW|BTN|BETWEEN|FROM|FM|FOR|IN|ON|AT")
_ALWAYS_SPATIAL = re.compile(r"^(?:OUT OF|(?:NORTH|SOUTH|EAST|WEST|NE|NW|SE|SW|N|S|E|W) OF|WITHIN|WI|INSIDE|OUTSIDE|BEYOND)$")
_WORD_STOP = r"(?:" + _SPATIAL_OPENERS + r"|SHALL|MUST|SHOULD|WILL|MAY|CAN|IS|ARE|WAS|WERE|BE|BEEN|DOES|DO|HAS|HAVE|NEED|NEEDS|ONLY)\b"
_OBJECT_WORD = r"(?:[^\s\x00;.:,]|(?<=\d)\.(?=\d))+"
_SPATIAL_PHRASE = re.compile(r"\b(?P<opener>" + _SPATIAL_OPENERS + r")\s+(?P<object>(?!" + _WORD_STOP + r")" + _OBJECT_WORD
                             + r"(?:(?:\s*,\s*|\s+)(?!" + _WORD_STOP + r")" + _OBJECT_WORD + r")*)")
_LEVEL_WORDS = re.compile(r"\bFL ?\d{2,3}\b|\b\d{3,5} ?(?:FT|M)\b|\bSFC\b|\bGND\b|\bUNL\b")
_LATLON_WORDS = re.compile(r"\b\d{1,3}(?:\.\d+)?[NSEW]\b|\b\d{2,7}[NS]\d{3,8}[EW]\b|\bLATITUDE\b|\bLONGITUDE\b|\bMERIDIAN\b|\bPARALLEL\b")
_TIME_WORDS = re.compile(r"\b\d{4} ?(?:UTC|Z)\b|\b\d{4} ?(?:-|TO|TIL|AND) ?\d{4}\b|\b(?:MON|TUE|WED|THU|FRI|SAT|SUN)\b|\bSR\b|\bSS\b|\bHJ\b|\bHN\b")
_ROUTE_WORDS = re.compile(r"\bROUTES?\b|\bRTES?\b|\bAIRWAYS?\b|\bAWYS?\b|\bTRACKS?\b|\bTRKS?\b|\bSEGMENTS?\b|\bPORTIONS?\b|\b[A-Z]{1,2}\d{1,4}[A-Z]?\b")
_AREA_WORDS = re.compile(r"\bAREAS?\b|\bSECTORS?\b|\bUTA\b|\bCTA\b|\bUIR\b|\bTMA\b|\bCTR\b|\bZONES?\b|\bREGIONS?\b|\bAIRSPACE\b|\bAOR\b|\bRESPONSIBILITY\b"
                         r"|\bOCEANIC\b|\bDOMESTIC\b|\bCOVERAGE\b|\bRANGE\b|\bVICINITY\b|\bCORRIDORS?\b")
_CIRCUMSTANCE_WORDS = re.compile(r"\bOCCASIONS?\b|\bCIRCUMSTANCES?\b|\bEMERGENC(?:Y|IES)\b|\bCONTINGENC(?:Y|IES)\b|\bFAILURES?\b|\bCASES?\b|\bSITUATIONS?\b|\bIMC\b|\bVMC\b|\bNIGHT\b")
_MEANS_WORDS = re.compile(r"\bCPDLC\b|\bADS-[BC]\b|\bSATCOM\b|\bVHF\b|\bHF\b|\bUHF\b|\bRADIO\b|\bRTF\b|\bR/T\b|\bTEL(?:EPHONE)?\b|\bPHONE\b|\bACARS\b|\bDATA ?LINK\b"
                          r"|\bAFTN\b|\bE-?MAIL\b|\bFAX\b|\bFREQ(?:UENCY|UENCIES)?\b|\bCONTROLLER\b|\bDISPATCH(?:ERS?)?\b|\bARINC\b|\bSITA\b")
_UNIVERSAL = re.compile(r"^(?:ALL|ANY|EVERY)\s+(?:(?:GIVEN|OTHER|ATS|PUBLISHED|DESIGNATED)\s+)?(?:CASES?|CIRCUMSTANCES?|SITUATIONS?|TIMES?|ROUTES?|RTES?|AIRWAYS?|AWYS?)$")
_DURATION = re.compile(r"^\d{1,3} ?MIN(?:S|UTES)?\b")
_RELATIVE_FIR = re.compile(r"^(?:THE\s+|THIS\s+|THAT\s+|EACH\s+)?(?:(?:NEXT|PREVIOUS|ADJACENT|RELEVANT|SAME|RESPECTIVE|APPROPRIATE|NEIGHBOU?RING|OTHER|DESTINATION|DEPARTURE|CONCERNED)\s+)?FIRS?\b")
_RELATIVE_WORDS = re.compile(r"\b(?:NEXT|PREVIOUS|ADJACENT|RELEVANT|SAME|RESPECTIVE|APPROPRIATE|NEIGHBOU?RING|OTHER|DESTINATION|DEPARTURE|CONCERNED)\b")
_FIR_PREFIX = re.compile(r"^(?:THE\s+)?(?P<names>(?:[A-Z][A-Z/-]*\s+){1,5}?)FIRS?\b(?P<rest>.*)$")
_LIST_CONTINUES = re.compile(r"^\s*(?:,|AND\b|OR\b)")
_RUN_GAP = re.compile(r"^[\s,/()]*(?:(?:AND|OR|AND/OR)[\s,/()]*)?$")
# The heads an IN-phrase names when it is a reference, a message field, a system or a manner - not a place.
_IN_NEUTRAL = {"ITEM", "ITEMS", "FIELD", "BOX", "LIEU", "ACCORDANCE", "ADDITION", "ADVANCE", "ORDER", "FULL", "USE", "FORCE", "EFFECT", "FLIGHT", "TIME",
               "VIEW", "LINE", "PRINCIPLE", "GENERAL", "PARTICULAR", "SEQUENCE", "FORMAT", "FPL", "PLAN", "RESPECT", "RESPONSE", "REPLY", "CONJUNCTION",
               "COORDINATION", "COMPLIANCE", "SUPPORT", "PREPARATION", "ICAO", "DOC", "DOCUMENT", "DOCUMENTS", "ANNEX", "AIP", "AIC", "NOTAM", "NOTAMS",
               "SUP", "SUPPLEMENT", "SECTION", "PARA", "PARAGRAPH", "ATTACHMENT", "APPENDIX", "CHAPTER", "TABLE", "FIGURE", "ENGLISH", "WRITING",
               "CONTACT", "CTC", "POSITIVE", "TWO-WAY", "REMARKS", "RMK", "FOLLOWING", "ABOVE-MENTIONED", "CPDLC", "ADS-C", "ACARS", "FMS", "FMC",
               "MESSAGE", "MESSAGES", "LOGON", "REQUEST", "REQUESTS", "REPORT", "REPORTS", "FREQUENCY", "FREQ", "AUTOMATIC", "MANUAL", "NEXT", "SAME",
               "THIS", "WHICH", "SUCH", "ITS", "THEIR"}
# A NOTAM's printed vertical limits (items F/G), printed after its text: a notice-level scope, evaluated from the planned levels.
_VERTICAL_LIMITS = re.compile(r"(?:^|\s)(?P<phrase>(?:FROM|FM)\s+(?P<lower>SFC|GND|FL\s?\d{2,3}|\d{3,5}\s?FT(?:\s?(?:AMSL|AGL|MSL))?)\s+TO\s+"
                              r"(?P<upper>UNL|FL\s?\d{2,3}|\d{3,5}\s?FT(?:\s?(?:AMSL|AGL|MSL))?))\s*\.?\s*$")
# A climb or descent can pass through a FIR entered within this many minutes of take-off or left within this many of the
# end of the route; a level band above the surface is evaluated from planned cruise levels only outside that margin.
_CRUISE_MARGIN_MINUTES = 60

STATE_SENTENCES = {
    "no_fir_rows_held": "No FIR boundary row is held in the parsed OFP; early-contact requirements are not established from this source.",
    "no_procedure_held": "No early-contact instruction is identified in this OFP's FIR notices or in an approved reference; the full FIR NOTAM source records hold the OFP's other communications notices. Lead times and frequencies are not inferred from crossing times.",
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


_FAMILY_PATTERNS: dict[tuple[str, ...], tuple[re.Pattern[str], re.Pattern[str], list[re.Pattern[str]]]] = {}


def _family_patterns(names: tuple[str, ...], context: str) -> re.Pattern[str]:
    """The admission pattern for a notice naming NAMES as airspace; a referent ("THESE CLEARANCES") is ATC's only when
    the notice's CONTEXT prints an ATC clearance (or instruction) it can refer to."""
    if names not in _FAMILY_PATTERNS:
        recipient = r"(?:" + _ATC_AUTHORITY + (r"|(?:" + "|".join(map(re.escape, names)) + r")\s+" + _CALL_SIGN if names else "") + r")"
        by_recipient = r"(?:(?:ISSUED|RECEIVED|TRANSMITTED|GIVEN|PASSED)\s+)?(?:BY|FROM|FM)\s+" + _RECIPIENT_WORDS + recipient + r"\b"
        clearance = (r"(?:[A-Z][A-Z/-]*\s+){0,3}?" + _CLEARANCE_TYPE + r"(?:\s+(?:AND|OR)\s+" + _CLEARANCE_TYPE + r")?\s+CLEARANCES?\b"
                     r"|(?:[A-Z][A-Z/-]*\s+){0,4}?CLEARANCES?\s+" + by_recipient)
        instruction = (r"(?:[A-Z][A-Z/-]*\s+){0,3}?" + recipient + r"\s+INSTRUCTIONS?\b"
                       r"|(?:[A-Z][A-Z/-]*\s+){0,3}?INSTRUCTIONS?\s+" + by_recipient)
        acts = []
        for referents in ((), ("CLEARANCES?",), ("INSTRUCTIONS?",), ("CLEARANCES?", "INSTRUCTIONS?")):
            target = r"(?:" + "|".join([clearance, instruction] + [_REFERENT + noun + r"\b" for noun in referents]) + r")"
            # A request noun ("ON REQUEST FROM ATC") is a condition, not an act.
            acts.append(re.compile(
                r"(?<!\bON )\b" + _unit_request(recipient)
                + r"|\b" + _NEGATION + r"\s+ACCEPT\s+" + target
                + r"|\b(?:REFUSE|DECLINE|REJECT|DISREGARD|IGNORE)\s+" + target
                + r"|\bACCEPT\s+(?:[A-Z][A-Z/-]*\s+){0,4}?(?:CLEARANCES?|INSTRUCTIONS?)\s+(?:ONLY\s+)?(?:FROM|FM)\s+" + _RECIPIENT_WORDS + recipient + r"\b"))
        _FAMILY_PATTERNS[names] = (re.compile(clearance), re.compile(instruction), acts)
    clearance, instruction, acts = _FAMILY_PATTERNS[names]
    return acts[(1 if clearance.search(context) else 0) + (2 if instruction.search(context) else 0)]


def _clearance_family(upper: str, context: str) -> bool:
    """ATC-CLEARANCE-FAMILY admission on positive ATC evidence; CONTEXT (the notice and its heading) names the airspaces
    whose call signs are ATC recipients and the clearances a referent can point to."""
    names = tuple(sorted({m.group(1) for m in _AIRSPACE_NAME.finditer(context)}))
    return any(not _inside_qualifier(upper, m.start(), m.end()) for m in _family_patterns(names, context).finditer(upper))


def _inside_qualifier(upper: str, start: int, end: int) -> bool:
    """Whether the act upper[start:end] sits in a qualifying clause of its own clause (see _QUALIFYING_CLAUSE): the
    modals between the last opener and the act's end are no more than the qualifier itself owns."""
    clause_start = max(upper.rfind(stop, 0, start) for stop in ",;.") + 1
    openers = list(_QUALIFYING_CLAUSE.finditer(upper[clause_start:start]))
    if not openers:
        return False
    after = upper[clause_start + openers[-1].end():end]
    rest = after.lstrip()
    if openers[-1].group(0) in _RELATIVE_OPENERS:
        own = 1 if _ANY_MODAL.match(rest) else 0
    else:
        own = 0 if _VERBLESS_CONDITION.match(rest) else 1
    return len(_ANY_MODAL.findall(after)) <= own


def _refused_family_act(upper: str) -> bool:
    """A negated clearance / request act on the sentence's own predicate (not inside a qualifying clause)."""
    return any(not _inside_qualifier(upper, m.start(), m.end()) for m in _NEGATED_FAMILY.finditer(upper))


def procedure_kind(text: Any, context: Any = None) -> str | None:
    """The notice's own instruction decides the kind; its FIR or region never does. None: not a communication instruction.
    CONTEXT is the notice (with its heading) a sentence belongs to; it names the airspaces whose call signs are ATC."""
    upper = classify_text(text)
    family_context = classify_text(context) if context is not None else upper
    for kind, pattern in _KIND_RULES:
        if pattern.search(upper) or (kind == "voice_contact" and _clearance_family(upper, family_context)):
            return kind
    if any(_nonvoice_duty(part) for part in sentences(upper)) or _PRIOR_ATS_APPROVAL.search(upper) or any(_ATC_SERVICE.search(part) and _ATC_SERVICE_STATUS.search(part) for part in sentences(upper)):
        return "atc_duty"
    if _PRINTED_RADIO_ADVICE.search(upper) or _ATC_REPORT.search(upper) or _RETIRED_REPORT.search(upper) or any(_COMMUNICATION_SERVICE.search(part) and _SERVICE_STATUS.search(part) for part in sentences(upper)):
        return "voice_contact"
    return None


def _instruction_effect(sentence: str, subject: dict[str, Any]) -> str:
    upper = _semantic(sentence)
    if _NEGATED_CALL.search(upper) or _RETIRED_REPORT.search(upper):
        return "not_required"
    if _possible_capability(sentence):
        return "capability"
    if _PROHIBITED_CALL.search(upper) or _refused_family_act(upper):
        return "prohibited"
    if _nonvoice_duty(upper) and _NONVOICE_PROHIBITION.search(upper):
        return "prohibited"
    # A positive crew instruction that contains an outage qualifier remains
    # an instruction ("if CPDLC is unavailable, contact ...").
    directed = bool(_CREW_DIRECTIVE.search(upper) or _IMPERATIVE.match(upper) or _PRINTED_RADIO_ADVICE.search(upper) or _ATC_REPORT.search(upper))
    if not directed and ((_COMMUNICATION_SERVICE.search(upper) and _SERVICE_STATUS.search(upper)) or (_ATC_SERVICE.search(upper) and _ATC_SERVICE_STATUS.search(upper))):
        return "availability"
    # The main subject's modal grants permission; a later exception, service
    # uncertainty or calendar date cannot replace a governing SHALL.
    leading = _LEADING_CLAUSE.match(upper)
    body = upper[leading.end():] if leading else upper
    modal_subject = _SUBJECT.match(body) or _OTHER_SUBJECT.match(body)
    if modal_subject and modal_subject.group("modal") == "MAY" and not _calendar_may(body, modal_subject.end() - 3) and not _OBLIGATION_MODAL.search(upper) and re.match(r"\s+(?!(?:NOT|SHALL|MUST|SHOULD|WILL|MAY|CAN|ARE|IS|NEED|HAVE|HAS)\b|\d)[A-Z]", body[modal_subject.end():]):
        return "permission"
    return "instruction"


def _possible_capability(sentence: str) -> bool:
    upper = _semantic(sentence)
    leading = _LEADING_CLAUSE.match(upper)
    body = upper[leading.end():] if leading else upper
    subject = _SUBJECT.match(body) or _OTHER_SUBJECT.match(body)
    return bool(subject and subject.group("modal") == "MAY" and not _calendar_may(body, subject.end() - 3)
                and not _OBLIGATION_MODAL.search(upper)
                and re.match(r"\s+(?:NOT\s+)?BE\s+(?:ABLE|UNABLE)\s+TO\b", body[subject.end():]))


def _calendar_may(upper: str, index: int) -> bool:
    # Date spelling is excluded only from the new modal checks, without
    # interpreting or modifying the original source's dates.
    return bool(re.search(r"\b(?:0?[1-9]|[12]\d|3[01])[- ]+$", upper[:index])
                or re.match(r"[- ]+(?:0?[1-9]|[12]\d|3[01]|\d{4})\b", upper[index + 3:]))


def _mixed_permission(sentence: str) -> bool:
    upper = _semantic(sentence)
    return any(not _calendar_may(upper, optional.start()) and _OBLIGATION_MODAL.search(upper[optional.end():])
               for optional in re.finditer(r"\bMAY\b", upper))


def _nonvoice_duty(upper: str) -> bool:
    operation = _OPERATING_DIRECTIVE.search(upper)
    target = re.split(r"\b(?:BEFORE|AFTER|DUE TO|EXCEPT|UNLESS|WHEN|IF)\b", upper[operation.end():].strip())[0] if operation else ""
    return bool((operation and _OPERATING_SUBJECT.search(upper[:operation.start()]) and _OPERATING_TARGET.search(target)) or re.search(r"\bSQUAWK(?:ING)?\b", upper)
                or _PASSIVE_CREW_CONTROL.search(upper)
                or (_NONVOICE_EQUIPMENT.search(upper) and _NONVOICE_DIRECTIVE.search(upper)))


def _action_sentences(text: str) -> list[str]:
    """Split independent unpunctuated subjects only after a complete printed
    non-voice duty. Leading geographic/equipment premises stay with their
    first subject; every quotation remains an original source substring."""
    result = []
    for part in (piece for sentence in sentences(text) for piece in _statement_parts(sentence)):
        if not _nonvoice_duty(classify_text(part)):
            result.append(part)
            continue
        start = 0
        circumstances = list(_CIRCUMSTANCE_PHRASE.finditer(part.upper()))
        for match in _JOINED_CREW_SUBJECT.finditer(part.upper()):
            if any(clause.start() < match.start() < clause.end() for clause in circumstances):
                continue
            preceding = part[start:match.start()].strip()
            if not _nonvoice_duty(classify_text(preceding)):
                continue
            result.append(preceding)
            start = match.end()
        remainder = part[start:].strip()
        if remainder:
            result.append(remainder)
    return result


def _statement_parts(sentence: str) -> list[str]:
    """A sentence holding two statements (_COORDINATED_CONDITION, _REQUEST_ITEM) as its source spans; else itself.
    A coordinated condition splits only after a crew directive of its own."""
    upper = sentence.upper()
    separators = sorted([(m.start(), m.end(), "item") for m in _REQUEST_ITEM.finditer(upper)]
                        + [(m.start(), m.end(), "and") for m in _COORDINATED_CONDITION.finditer(upper)])
    parts: list[str] = []
    start = 0
    for left, right, kind in separators:
        if left < start:
            continue
        preceding = sentence[start:left].strip()
        if kind == "and" and not (_IMPERATIVE.match(preceding.upper()) or _SUBJECT.match(preceding.upper())):
            continue
        if preceding:
            parts.append(preceding)
        start = right
    remainder = sentence[start:].strip()
    if remainder:
        parts.append(remainder)
    return parts or [sentence]


def _joined_stops(fragment: str) -> list[int]:
    """Offsets just after each stop printed without a following space that ends a sentence (see _JOINED_STOP)."""
    cuts: list[int] = []
    for match in _JOINED_STOP.finditer(fragment):
        start = fragment.rfind(" ", 0, match.start()) + 1
        end = fragment.find(" ", match.end())
        run = fragment[start:end if end >= 0 else len(fragment)]
        address = match.group(0) == "." and ("://" in run or "@" in run or "(AT)" in run or run.startswith("WWW.")
                                             or run.count(".") >= 2 or match.group(1) in _ADDRESS_LABELS)
        if not address and not _ABBREVIATION.search(fragment[:match.end()]):
            cuts.append(match.end())
    return cuts


def sentences(text: Any) -> list[str]:
    clean = _normalise(text)
    if not clean:
        return []
    parts: list[str] = []
    for spaced in _SENTENCE_SPLIT.split(clean):
        cuts = _joined_stops(spaced)
        for fragment in (spaced[a:b] for a, b in zip([0, *cuts], [*cuts, len(spaced)])):
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
    boundaries: list[str | None] = []
    airways: list[str | None] = []
    current: str | None = None
    for waypoint in flight.get("route_waypoints") or []:
        if not isinstance(waypoint, dict):
            continue
        boundary = _normalise(waypoint.get("fir_boundary")).upper() or None
        if boundary:
            current = boundary
        names.append(_normalise(waypoint.get("name")).upper().lstrip("-"))
        fir_in_effect.append(current)
        boundaries.append(boundary)
        airways.append(_normalise(waypoint.get("airway_in")).upper() or None)
    profile: list[tuple[str, int]] = []
    tokens = [t for t in _normalise(flight.get("planned_level_profile")).upper().split("/") if t]
    for index in range(0, len(tokens) - 1, 2):
        if tokens[index + 1].isdigit():
            profile.append((tokens[index], int(tokens[index + 1])))
    last = max((m for m in (_integer(w.get("actm_minutes")) for w in flight.get("route_waypoints") or [] if isinstance(w, dict)) if m is not None), default=None)
    return {"names": names, "fir_in_effect": fir_in_effect, "boundaries": boundaries, "airways": airways, "profile": profile, "last_minutes": last}


def _fir_airways(route: dict[str, Any], fir: str) -> tuple[set[str], bool]:
    """The airways the OFP files on every leg that touches one FIR, and whether each such leg's airway (or DCT) is held.
    False when the FIR is never entered.

    A leg runs from one waypoint to the next and its airway is the closing waypoint's airway_in. It touches the FIR when it
    starts inside it or crosses one of its boundary rows, however many boundary rows it crosses. Boundary rows only move
    the location; only a waypoint closes a leg, so a touching leg still open at the end of the route is unknown
    (ATC-AIRWAY-LEG-TRANSITIONS, Codex QA of releases 448 and 450)."""
    filed: set[str] = set()
    entered, complete, inside, touching = False, True, False, False
    for boundary, airway in zip(route.get("boundaries") or [], route.get("airways") or []):
        if boundary:
            touching = touching or inside or boundary == fir
            inside = boundary == fir
            entered = entered or inside
            continue
        if touching or inside:
            if airway is None:
                complete = False
            elif airway != "DCT":
                filed.add(airway)
        touching = False
    return filed, entered and complete and not touching


def _airway_list_condition(text: str, route: dict[str, Any], fir: str) -> dict[str, Any] | None:
    """An airway-only route list read against the airways filed inside the notice's FIR: met when one of them is filed
    there, not met only when every leg there is known and none is; otherwise no condition is added (it stays unresolved)."""
    upper = classify_text(text)
    match = _AIRWAY_LIST.search(upper)
    if not match or not fir:
        return None
    # A list inside an exception or negation ("CPDLC SHALL BE USED EXC ON ROUTE L774") does not limit the statement to
    # those airways; it is left to the restriction it already is.
    clause = re.split(r"[.;:]", upper[:match.start()])[-1]
    if _AIRWAY_EXCEPTION.search(clause):
        return None
    listed = re.findall(_AIRWAY, match.group(1))
    filed, known = _fir_airways(route, fir)
    if any(airway in filed for airway in listed):
        return {"kind": "route", "text": match.group(0).strip(), "result": "met"}
    if known:
        return {"kind": "route", "text": match.group(0).strip(), "result": "not_met"}
    return None


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
    navaids = [m.span("frequency") if m.group("frequency") else m.span("channelled") for m in _NAVAID_FREQUENCY.finditer(upper)]
    frequencies: list[str] = []
    for found in _FREQUENCY.finditer(upper):
        match = found.group(0)
        if found.span() not in navaids and match not in frequencies:
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


def call_unit(sentence: Any) -> str | None:
    """The unit a call instruction names, verbatim; None when the sentence names none (a TIBA broadcast, "LOGON ...")."""
    match = _CALL_UNIT.search(classify_text(sentence))
    unit = match.group("unit").strip().rstrip(",").strip() if match else ""
    return unit or None


def call_window(lead: Any, anchor_minutes: int | None) -> dict[str, Any] | None:
    """When a printed lead puts the call, against the anchor's OFP ACTM, read as printed (ATC-EARLY-CALLS, v17).

    NOT LESS THAN / AT LEAST / MINIMUM / NOT LATER THAN / a bare amount: not later than the anchor less the amount;
    APPROX: about that time; WITHIN / WI: from the anchor less the amount up to the anchor; BETWEEN a AND b: from the
    anchor less b to the anchor less a; NOT EARLIER THAN / MAXIMUM: from the anchor less the amount up to the anchor.
    Nothing is derived when an end of the window would fall before take-off (ACTM 00:00)."""
    upper = classify_text(lead)
    amounts = [int(n) for n in re.findall(r"\b(\d{1,3})\b", upper)]
    if not amounts or anchor_minutes is None:
        return None
    low, high = min(amounts), max(amounts)
    if upper.startswith("BETWEEN "):
        relation, start, by = "window", anchor_minutes - high, anchor_minutes - low
    elif re.match(r"^(?:WI|WITHIN|NOT EARLIER THAN|MAXIMUM|MAX)\b", upper):
        relation, start, by = "window", anchor_minutes - low, anchor_minutes
    elif upper.startswith("APPROX"):
        relation, start, by = "about", None, anchor_minutes - low
    else:
        relation, start, by = "not_later", None, anchor_minutes - low
    if by < 0 or (start is not None and start < 0):
        return None
    return {"relation": relation, "from_actm": actm_text(start) if start is not None else None, "by_actm": actm_text(by),
            "anchor_actm": actm_text(anchor_minutes)}


def call_time_phrase(window: dict[str, Any]) -> str:
    if window["relation"] == "window":
        return f"between ACTM {window['from_actm']} and ACTM {window['by_actm']}"
    if window["relation"] == "about":
        return f"about ACTM {window['by_actm']}"
    return f"not later than ACTM {window['by_actm']}"


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
        tokens.append({"waypoint": waypoint, "airway": airway, "band": None, "frequencies": frequencies, "unit": unit.strip(),
                       "text": f"{airway} {waypoint} {unit.strip()} {' '.join(frequencies)}"})
    return tokens


def _resolve_names(printed: str, names: dict[str, str]) -> list[tuple[str, str | None]]:
    """The FIR names a direction phrase lists, each with the ICAO the OFP's own headings or bodies give it."""
    by_name = {name: icao for icao, name in names.items()}
    return [(name, by_name.get(name)) for name in re.split(r", AND | AND |, OR | OR |, ", printed.strip()) if name.strip()]


# ---- a sentence's subject and the conditions it carries


def _semantic(sentence: str) -> str:
    """The sentence for classification: upper-cased, OCR joins applied, a leading provenance block set aside."""
    return _PROVENANCE.sub("", classify_text(sentence), count=1)


def _subject_of(sentence: str) -> dict[str, Any]:
    """What a sentence says about who acts, and the clauses it carries itself.

    kind "stated": a crew subject ("IFR AFCT FLT PLANNED TO DEP CYMM/OILSANDS UNABLE TO CTC ... SHOULD"), with its
    prefix and qualifier; "imperative": the crew addressed directly ("USE LOGON ADDRESS ..."); "other": a subject of its
    own that is not the crew ("THE PROCEDURES ... APPLY", "ARTCC AUTOMATION WILL PROVIDE", or the phrase before the
    first modal when no anchored pattern read it); "fragment": no finite verb at all. A sentence's own leading clause
    always belongs to it. Only a continuation - a fragment, or a subject whose head names the crew's own communication
    act - takes the governing crew sentence's qualifiers (release-422 QA, F1). A source provenance block is set aside
    first (release-428 QA, F1).
    """
    upper = _semantic(sentence)
    leading = _LEADING_CLAUSE.match(upper)
    body = upper[leading.end():] if leading else upper
    clause = leading.group("clause").strip() if leading else None
    match = _SUBJECT.match(body) or _SUBJECT_TO.match(body) or _REPORTING_SUBJECT.match(body) or _REQUESTING_SUBJECT.match(body)
    if match and (not match.group("qualifier").strip() or _CREW_QUALIFIER_START.match(match.group("qualifier").strip())):
        return {"kind": "stated", "prefix": match.group("prefix").strip(), "qualifier": match.group("qualifier").strip(), "leading": clause, "continuation": False}
    act = _CREW_ACT_SUBJECT.match(body)
    if act:
        return {"kind": "other", "prefix": "", "qualifier": "", "leading": clause, "noun": act.group("noun").strip(), "continuation": True}
    if _IMPERATIVE.match(body):
        return {"kind": "imperative", "prefix": "", "qualifier": "", "leading": clause, "continuation": False}
    other = _OTHER_SUBJECT.match(body)
    noun = other.group("noun").strip() if other else None
    if noun is None:
        pre = _PRE_MODAL.match(body)
        if pre:
            noun = " ".join(pre.group("phrase").split()[-10:]).strip(" ,;:")
    if noun:
        return {"kind": "other", "prefix": "", "qualifier": "", "leading": clause, "noun": noun,
                "continuation": bool(_CREW_ACT_NOUN.match(noun)) or _head_noun(noun) in _CREW_ACT_HEADS}
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


def _fir_scope_condition(text: str, names_text: str, ctx: dict[str, Any] | None) -> dict[str, Any] | None:
    """A phrase naming the FIR(s) it applies in, evaluated against the crossings the OFP prints: met when the route crosses
    one of them, not met when every one is identified and none is crossed, unresolved when a name is not identified. The
    notice's own FIR stands for "THE FIR"; a relative reference ("THE NEXT FIR") is left to the scope rules (None)."""
    ctx = ctx or {}
    words = re.sub(r"^(?:THE|THIS|THAT|A|AN|EACH|ANY)\s+", "", (names_text or "").strip()).strip()
    if _RELATIVE_WORDS.search(words):
        return None
    crossed: set[str] = ctx.get("crossed") or set()
    names: dict[str, str] = ctx.get("names") or {}
    if not words:
        firs = [ctx["fir"]] if ctx.get("fir") else []
        complete = bool(firs)
    else:
        codes = [w for w in re.findall(r"\b[A-Z]{4}\b", words) if w in names or w in crossed]
        if codes:
            firs, complete = codes, True
        else:
            by_name = {name: icao for icao, name in names.items()}
            parts = [part.strip() for part in re.split(r", AND | AND |, OR | OR |, |/", words) if part.strip()]
            resolved = [by_name.get(part) for part in parts]
            firs, complete = [r for r in resolved if r], bool(parts) and all(resolved)
    missing_source_boundary = ctx.get("fir") not in crossed and ctx.get("fir") in firs
    result = "met" if any(f in crossed for f in firs) else "not_met" if firs and complete and not missing_source_boundary else "unresolved"
    return {"kind": "fir_scope", "text": text, "result": result, "note": "/".join(firs)}


def _clause_conditions(clause: str, stripped: str, ctx: dict[str, Any] | None) -> list[dict[str, Any]]:
    """A leading / trailing clause: a direction or aerodrome form is evaluated by its own rule, a named FIR against the
    crossings; anything else stays an explicit unresolved qualifier quoting the clause."""
    if _EVALUATED_QUALIFIER.match(stripped):
        return []
    scope = _FIR_SCOPE_QUALIFIER.match(stripped)
    if scope:
        condition = _fir_scope_condition(clause, scope.group("names"), ctx)
        return [condition] if condition else []
    return [{"kind": "qualifier", "text": clause, "result": "unresolved"}]


def _qualifier_conditions(qualifier: str, flight: dict[str, Any], ctx: dict[str, Any] | None) -> list[dict[str, Any]]:
    """A subject / population qualifier: direction and aerodrome forms evaluated by their own rules, a named FIR against
    the crossings, aerodromes against the flight's own; anything else explicit and unresolved."""
    if _EVALUATED_QUALIFIER.match(qualifier):
        return []
    scope = _FIR_SCOPE_QUALIFIER.match(qualifier)
    if scope:
        condition = _fir_scope_condition(qualifier, scope.group("names"), ctx)
        return [condition] if condition else []
    airports, remainder = _airport_conditions(qualifier, flight)
    conditions = list(airports)
    if len(remainder.split()) >= 2 and not _EVALUATED_QUALIFIER.match(remainder):
        scope = _FIR_SCOPE_QUALIFIER.match(remainder)
        if scope:
            condition = _fir_scope_condition(remainder, scope.group("names"), ctx)
            if condition:
                conditions.append(condition)
        else:
            conditions.append({"kind": "qualifier", "text": qualifier if airports else remainder, "result": "unresolved"})
    return conditions


def _subject_conditions(subject: dict[str, Any], flight: dict[str, Any], ctx: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """The conditions a stated subject carries: every qualification-bearing prefix (equipment, flight rules, a population
    class), its qualifier and its own leading clause - evaluated where the OFP holds the evidence, explicit otherwise."""
    conditions: list[dict[str, Any]] = []
    prefix = subject.get("prefix") or ""
    equipment = _EQUIPMENT_PREFIX.search(prefix)
    if equipment:
        conditions.append({"kind": "equipment", "text": equipment.group(0), "result": "unresolved"})
    rules = _RULES_PREFIX.search(prefix)
    if rules:
        conditions.append({"kind": "flight_rules", "text": rules.group(0), "result": "unresolved"})
    population_class = _CLASS_PREFIX.search(prefix)
    if population_class:
        conditions.append({"kind": "population", "text": population_class.group(0), "result": "unresolved"})
    qualifier = (subject.get("qualifier") or "").strip(" ,;")
    if qualifier:
        conditions.extend(_qualifier_conditions(qualifier, flight, ctx))
    if subject.get("leading"):
        clause = subject["leading"]
        stripped = re.sub(r"^(?:WHENEVER|WHEN|IF|WHILE|UNLESS|AFTER|BEFORE|DURING|DRG|PROVIDED|WHEREVER|WHERE|AS LONG AS)\s+", "", clause)
        conditions.extend(_clause_conditions(clause, stripped, ctx))
    return conditions


def _population_conditions(sentence: str, flight: dict[str, Any], ctx: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Qualifications of the aircraft population inside a sentence's body, evaluated like a subject's (F1, 424 QA);
    a qualification-bearing prefix alone qualifies, with or without a modifier after the noun (F1, 428 QA)."""
    upper = _semantic(sentence)
    conditions: list[dict[str, Any]] = []
    for match in _POPULATION.finditer(upper):
        prefix = match.group("prefix").strip(" ,")
        modifier = _RELATIVE_OPENING.sub("", (match.group("modifier") or "").strip(" ,;"))
        if not modifier and not (_EQUIPMENT_PREFIX.search(prefix) or _RULES_PREFIX.search(prefix)):
            continue
        pseudo = {"kind": "population", "prefix": prefix, "qualifier": modifier, "leading": None}
        conditions.extend(_subject_conditions(pseudo, flight, ctx))
    return conditions


def _head_noun(noun: str) -> str:
    chunk = _HEAD_STOP.split(noun)[0].strip(" ,.;:-")
    words = chunk.split()
    return words[-1] if words else ""


def _chunk_heads(noun: str) -> list[str]:
    heads = []
    for chunk in _HEAD_STOP.split(noun):
        words = chunk.strip(" ,.;:-").split()
        if words:
            heads.append(words[-1])
    return heads


def _actor_of(sentence: str, subject: dict[str, Any], governing: int | None = None) -> str:
    """"crew" for a sentence that directs the crew; "atc" for a provision, service or separation ATC applies or
    provides. Decided by the subject's head noun, a service passive (adverbs allowed) beside an ATC-headed phrase, or
    an agent phrase naming ATC. Explicit other subjects keep their actor: equipment in their object is not a crew
    obligation. Source-passive aircraft control instructions are crew duties; an absent actor stays unresolved."""
    upper = _semantic(sentence)
    # An agent printed inside a circumstance or exception ("UNLESS AUTH BY ATC ...: A. ALL ACFT OPS ... ARE PROHIBITED")
    # qualifies the statement; it is not the statement's actor.
    main = _blank(upper, [m.span() for m in _CIRCUMSTANCE_PHRASE.finditer(upper)])
    passive_agent = _PASSIVE_NAMED_AGENT.search(main)
    if passive_agent:
        agent = re.split(r"\b(?:DURING|DRG|WHEN|IF|BEFORE|AFTER|WITHIN|IN|AT|ON|FROM|TO|BY|FOR)\b", re.split(r"\bBY\s+", passive_agent.group())[1])[0].strip()
        if _CREW_AGENT.search(f"BY {agent}"):
            return "crew"
        head = re.sub(r"S$", "", _head_noun(agent))
        if _ATC_AGENT.search(f"BY {agent}") or head in ("ATC", "ATS", "ACC", "ATSU", "ARTCC", "CENTRE", "CENTER", "CONTROL", "CTL", "APP", "TOWER"):
            return "atc"
        return "other"
    if subject["kind"] in ("stated", "imperative") or _CREW_AGENT.search(main):
        return "crew"
    heads = [head if head in _ATC_HEADS else re.sub(r"S$", "", head) for head in _chunk_heads(subject.get("noun") or "")]
    if _ATC_RECIPIENT.search(upper) and (heads and heads[0] == "ATC" or subject["kind"] == "fragment"):
        return "crew"
    passive = bool(_SERVICE_PASSIVE.search(main))
    if (heads and heads[0] in _ATC_HEADS) or (passive and any(head in _ATC_HEADS for head in heads)) or _ATC_AGENT.search(main):
        return "atc"
    if subject["kind"] == "other" and subject.get("continuation"):
        return "crew"
    if _PASSIVE_CREW_CONTROL.search(upper) and heads and heads[0] in ("TRANSPONDER", "LIGHT", "CLIMB", "DESCENT"):
        return "crew"
    # A geographic/provenance prelude can precede an embedded crew subject.
    # It must be before the first modal, not an object of another actor's duty.
    crew = _EMBEDDED_SUBJECT.search(upper)
    modal = re.search(r"\b(?:SHALL|MUST|SHOULD|WILL|MAY|CAN|ARE|IS|NEED|HAVE|HAS)\b", upper)
    if crew and modal and crew.start() < modal.start() and (not crew.group("qualifier").strip() or _CREW_QUALIFIER_START.match(crew.group("qualifier").strip())):
        return "crew"
    if subject["kind"] == "other":
        return "other"
    if _PRINTED_RADIO_ADVICE.search(upper):
        return "crew"
    return "crew" if governing is not None else "unresolved"


def _trailing_conditions(sentence: str, ctx: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """A WHEN / IF / UNLESS clause after the action ("USE LOGON ADDRESS PAZN WHEN OPERATING IN ...") stays an explicit
    condition: a named FIR evaluated against the crossings, anything else unresolved."""
    upper = _semantic(sentence)
    match = _TRAILING_CLAUSE.search(upper)
    if not match:
        return []
    clause = match.group("clause").strip(" ,;")
    stripped = re.sub(r"^(?:WHEN|IF|WHILE|UNLESS|PROVIDED|WHERE|EXCEPT WHEN|ONLY WHEN|ONLY IF)\s+", "", clause)
    return _clause_conditions(clause, stripped, ctx)


def _blank(text: str, spans: list[tuple[int, int]]) -> str:
    chars = list(text)
    for start, end in spans:
        for index in range(max(0, start), min(len(chars), end)):
            chars[index] = _ACCOUNTED
    return "".join(chars)


def _accounted_spans(upper: str, ctx: dict[str, Any] | None) -> list[tuple[int, int]]:
    """The spans the recognizers already account for: a leading clause, a stated crew subject (prefix, noun, qualifier),
    a trailing clause, population phrases, directions, ATC-request and other named phrases, route tokens, the printed
    frequencies, lead, interval and addresses, and the notice's vertical limits when this sentence prints them."""
    spans: list[tuple[int, int]] = []
    leading = _LEADING_CLAUSE.match(upper)
    offset = leading.end() if leading else 0
    if leading:
        spans.append((0, leading.end()))
    stated = (_SUBJECT.match(upper[offset:]) or _SUBJECT_TO.match(upper[offset:]) or _REPORTING_SUBJECT.match(upper[offset:])
              or _REQUESTING_SUBJECT.match(upper[offset:]))
    # Only a qualifier accepted by _subject_conditions has been accounted for.
    if stated and (not stated.group("qualifier").strip() or _CREW_QUALIFIER_START.match(stated.group("qualifier").strip())):
        spans.append((offset, offset + stated.start("modal")))
    trailing = _TRAILING_CLAUSE.search(upper)
    if trailing:
        spans.append(trailing.span("clause"))
    for pattern in (_POPULATION, *_DIRECTIONS, _ATC_REQUEST, _UNRESOLVED, _ROUTE_LIST, _ROUTE_PAIR, _ROUTE_FREQ_ROW, _FREQUENCY, _INTERVAL, _ADDRESS):
        spans.extend(match.span() for match in pattern.finditer(upper))
    spans.extend(match.span(1) for match in _LEAD.finditer(upper))
    vertical = (ctx or {}).get("vertical")
    if vertical:
        match = _VERTICAL_LIMITS.search(upper)
        if match and " ".join(match.group("phrase").split()) == vertical:
            spans.append(match.span("phrase"))
    return spans


def _spatial_kind(opener: str, obj: str) -> str:
    """What a spatial phrase is: "restriction" (a level, position, time, circumstance, area, route or unlisted place),
    "fir" (a named FIR, evaluated), or "neutral" (a means, a purpose, a reference, the notice's own or a relative FIR)."""
    if _UNIVERSAL.match(obj):
        return "neutral"
    if _LEVEL_WORDS.search(obj) or _LATLON_WORDS.search(obj) or _TIME_WORDS.search(obj) or _CIRCUMSTANCE_WORDS.search(obj):
        return "restriction"
    always = bool(_ALWAYS_SPATIAL.match(opener))
    if opener in ("WITHIN", "WI") and _DURATION.match(obj):
        return "neutral"
    if opener in ("WITHIN", "WI", "INSIDE", "IN", "FOR", "THROUGH", "THRU"):
        if _RELATIVE_FIR.match(obj):
            return "neutral"
        fir = _FIR_PREFIX.match(obj)
        if fir and not _LIST_CONTINUES.match(fir.group("rest")) and not _AREA_WORDS.search(fir.group("names")):
            return "fir"
    if always or _AREA_WORDS.search(obj) or _ROUTE_WORDS.search(obj):
        return "restriction"
    if opener in ("VIA", "ALONG"):
        return "neutral" if _MEANS_WORDS.search(obj) else "restriction"
    if opener == "IN":
        head = re.sub(r"^(?:THE|A|AN)\s+", "", obj).split()[0].strip("()\"'")
        return "neutral" if head in _IN_NEUTRAL else "restriction"
    return "neutral"


def _restriction_conditions(sentence: str, flight: dict[str, Any], ctx: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Every restrictive phrase of a sentence the recognizers did not account for (release-430 QA, F1): a circumstance
    (WHEN, DURING / DRG, EXCEPT ...), ONLY + a timing, a population prefix, a spatial phrase naming an area, a route, a
    level, a position, a coverage or a time, or a time window. A named FIR is evaluated; adjacent restrictive phrases
    are one condition quoting the source; everything else is typed non-restrictive."""
    upper = _semantic(sentence)
    residual = _blank(upper, _accounted_spans(upper, ctx))
    residual = _blank(residual, [m.span() for m in _REASON_PHRASE.finditer(residual)])
    residual = _blank(residual, [m.span() for m in _MANNER_PHRASE.finditer(residual)])
    conditions: list[dict[str, Any]] = []
    phrases: list[tuple[int, int]] = []
    circumstances = list(_CIRCUMSTANCE_PHRASE.finditer(residual))
    for match in circumstances:
        clause = upper[match.start():match.end()].strip(" ,;:")
        if not clause:
            continue
        stripped = _CIRCUMSTANCE_OPENING.sub("", clause)
        if _EVALUATED_QUALIFIER.match(stripped):
            continue
        scope = _FIR_SCOPE_QUALIFIER.match(stripped)
        condition = _fir_scope_condition(clause, scope.group("names"), ctx) if scope else None
        if scope and condition:
            conditions.append(condition)
        elif not scope:
            phrases.append(match.span())
    residual = _blank(residual, [m.span() for m in circumstances])
    only = list(_ONLY_TIMING.finditer(residual))
    phrases.extend(m.span() for m in only)
    residual = _blank(residual, [m.span() for m in only])
    timings = list(_TIMING_PHRASE.finditer(residual))
    phrases.extend(m.span() for m in timings if _OPERATING_EVENT_TIMING.match(m.group(0)))
    residual = _blank(residual, [m.span() for m in timings])
    populations = list(_PREFIXED_POPULATION.finditer(residual))
    for match in populations:
        pseudo = {"kind": "population", "prefix": match.group("prefix").strip(" ,"), "qualifier": "", "leading": None}
        conditions.extend(_subject_conditions(pseudo, flight, ctx))
    residual = _blank(residual, [m.span() for m in populations])
    spatial = list(_SPATIAL_PHRASE.finditer(residual))
    for match in spatial:
        opener, obj = match.group("opener"), match.group("object")
        kind = _spatial_kind(opener, obj)
        if kind == "restriction":
            phrases.append(match.span())
        elif kind == "fir":
            fir = _FIR_PREFIX.match(obj)
            text = f"{opener} {obj[:fir.start('rest')].strip()}"
            condition = _fir_scope_condition(text, fir.group("names"), ctx)
            if condition:
                conditions.append(condition)
    residual = _blank(residual, [m.span() for m in spatial])
    phrases.extend(m.span() for m in _TIME_WORDS.finditer(residual))
    runs: list[list[int]] = []
    for start, end in sorted(phrases):
        if runs and (start <= runs[-1][1] or _RUN_GAP.match(upper[runs[-1][1]:start])):
            runs[-1][1] = max(runs[-1][1], end)
        else:
            runs.append([start, end])
    for start, end in runs:
        text = upper[start:end].strip(" ,;:")
        if text:
            conditions.append({"kind": "restriction", "text": text, "result": "unresolved"})
    return conditions


def _band_value(token: str) -> int:
    token = token.replace(" ", "")
    if token in ("SFC", "GND"):
        return 0
    if token == "UNL":
        return 999
    if token.startswith("FL"):
        return int(token[2:])
    return int(re.match(r"\d+", token).group(0)) // 100


def _vertical_condition(match: re.Match[str], route: dict[str, Any], crossings: list[dict[str, Any]], fir: str) -> dict[str, Any]:
    """A notice's printed vertical limits against the planned levels: a band from the surface covering every planned level
    is met; otherwise the planned cruise levels in effect in this FIR decide, only where a climb or descent cannot pass
    through it (outside the cruise margin) - else the band stays explicit and unresolved."""
    low, high = _band_value(match.group("lower")), _band_value(match.group("upper"))
    text = " ".join(match.group("phrase").split())
    planned = [level for _, level in route["profile"]]
    if planned and low == 0 and high >= max(planned):
        return {"kind": "level", "text": text, "result": "met", "note": f"planned FL{min(planned)}-FL{max(planned)}"}
    in_fir = sorted({level for name, effect in zip(route["names"], route["fir_in_effect"]) if effect == fir
                     for level in [_planned_level_at(route, name)] if level is not None})
    if not fir or not in_fir:
        return {"kind": "level", "text": text, "result": "unresolved", "note": "planned level in this FIR not held"}
    held = f"planned FL{in_fir[0]}" if len(in_fir) == 1 else f"planned FL{in_fir[0]}-FL{in_fir[-1]}"
    entries = [row for row in crossings if row["fir"] == fir]
    exits = [row for row in crossings if entries and row["sequence"] > entries[0]["sequence"] and row["fir"] != fir]
    last = route.get("last_minutes")
    cruise = bool(entries) and entries[0]["actm_minutes"] >= _CRUISE_MARGIN_MINUTES and bool(exits) and last is not None \
        and exits[0]["actm_minutes"] <= last - _CRUISE_MARGIN_MINUTES
    if not cruise:
        return {"kind": "level", "text": text, "result": "unresolved", "note": f"{held} in {fir}; a climb or descent may pass through this FIR"}
    within = [low <= level <= high for level in in_fir]
    result = "met" if all(within) else "not_met" if not any(within) else "unresolved"
    return {"kind": "level", "text": text, "result": result, "note": f"{held} in {fir}"}


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


def _report_conditions(sentence: str, source: str) -> list[dict[str, Any]]:
    if not _ATC_REPORT.search(classify_text(sentence)):
        return []
    event = _REPORT_EVENT.search(classify_text(source))
    if event:
        return [{"kind": "qualifier", "text": f"report trigger: {event.group(0)}", "result": "unresolved"}]
    reference = _REFERENTIAL_REPORT_EVENT.search(classify_text(sentence))
    if not reference:
        return []
    conditions = [{"kind": "qualifier", "text": f"report trigger: {reference.group(0)}", "result": "unresolved"}]
    # Preserve a referential event's literal context without claiming that
    # the OFP establishes its event, schedule or geographic limits.
    start = source.find(sentence)
    if start > 0:
        conditions.append({"kind": "qualifier", "text": f"reporting context: {source[:start].strip()}", "result": "unresolved"})
    return conditions


def _clearance_context(sentence: str, source: str) -> list[dict[str, Any]]:
    """A printed sentence that refers back to clearances or instructions its own notice describes ("DO NOT ACCEPT THESE
    CLEARANCES AND IF CONTENTION EXISTS ,SEEK CLARIFICATION ...") cannot be read without that notice: every action quoted
    from it holds the text before it (which clearances, from whom, where) and the text after it (references, scope,
    annotations) verbatim and unresolved. Nothing in either is decoded or evaluated (ATC-CLEARANCE-FAMILY, 1 Oct 2026)."""
    if not _REFERENTIAL_CLEARANCE.search(classify_text(sentence)):
        return []
    start = source.find(sentence)
    if start < 0:
        return []
    conditions = []
    before, after = source[:start].strip(), source[start + len(sentence):].strip()
    if before:
        conditions.append({"kind": "qualifier", "text": f"clearance context: {before}", "result": "unresolved"})
    if after:
        conditions.append({"kind": "qualifier", "text": f"further notice text: {after}", "result": "unresolved"})
    return conditions


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
    """One held notice. A missing timed FIR entry cannot establish that the source airspace is irrelevant."""
    text = _normalise(record.get("text"))
    # The notice and its printed heading name the airspaces whose call signs are ATC recipients (ATC-CLEARANCE-FAMILY).
    context = f"{_normalise(record.get('heading'))} {text}"
    kind = procedure_kind(text, context)
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
        "no FIR crossing time held" if not entry
        else f"ATOT {basis_utc:%H%M}Z + ACTM" if basis["kind"] == "actual_takeoff" and basis_utc
        else f"scheduled departure {basis_utc:%H%M}Z + ACTM" if basis["kind"] == "scheduled_departure" and basis_utc
        else "no departure time held"
    )
    if window is None or instant is None:
        notice_conditions.append({"kind": "validity", "text": validity, "result": "unresolved", "basis": basis_text})
    else:
        start, end = window
        notice_conditions.append({"kind": "validity", "text": validity, "result": "met" if start <= instant and (end is None or instant <= end) else "not_met", "basis": basis_text})
    if kind == "atc_duty":
        for part in sentences(text):
            upper_part = classify_text(part)
            if not procedure_kind(part, context) and re.search(r"\b(?:AFFECTED AREAS?|APPLIES TO|APPLICABLE TO|LIMITED TO|RESTRICTED TO)\b", upper_part) and _AREA_WORDS.search(upper_part):
                # An earlier source sentence can qualify a later duty.
                notice_conditions.append({"kind": "qualifier", "text": part, "result": "unresolved"})
    tokens = _route_tokens(text)
    if segment is not None and heading_kind == "segment":
        tokens = [{"waypoint": w, "airway": segment.get("airway"), "band": None, "text": _normalise(record.get("heading"))} for w in segment_waypoints] + tokens
    route_frequencies: list[str] | None = None
    frequency_row: dict[str, Any] | None = None
    if tokens:
        on_route_tokens = [t for t in tokens if t["waypoint"] in route["names"]]
        matched = on_route_tokens[0] if on_route_tokens else None
        notice_conditions.append({"kind": "route", "text": matched["text"] if matched else tokens[0]["text"], "result": "met" if matched else "not_met"})
        if matched and matched.get("frequencies"):
            route_frequencies = list(matched["frequencies"])
            # ATC-EARLY-CALLS (v17): the table row the filed route selects is shown with the call (its unit and values).
            frequency_row = matched
        band_token = next((t for t in on_route_tokens if t["band"]), None)
        if band_token:
            level = _planned_level_at(route, band_token["waypoint"])
            low, high = band_token["band"]
            notice_conditions.append({
                "kind": "level", "text": f"FL{low}-FL{high} at {band_token['waypoint']}",
                "result": "unresolved" if level is None else "met" if low <= level <= high else "not_met",
                "note": f"planned FL{level}" if level is not None else "planned level not held",
            })
    else:
        airway_condition = _airway_list_condition(text, route, fir)
        if airway_condition:
            notice_conditions.append(airway_condition)
    if re.search(r"\b(?:TEMPORARY FLIGHT RESTRICTIONS?|TFR)\b", classify_text(text)):
        # A later TFR SSR/continuous-communications action retains the
        # notice's geographic/population/exception boundary as unresolved.
        notice_conditions.append({"kind": "qualifier", "text": "source airspace limits, population and exceptions", "result": "unresolved"})
    vertical = _VERTICAL_LIMITS.search(classify_text(text))
    if vertical:
        notice_conditions.append(_vertical_condition(vertical, route, crossings, fir))
    atc_request = _ATC_REQUEST.search(classify_text(text))
    if atc_request:
        notice_conditions.append({"kind": "atc_request", "text": atc_request.group(0), "result": "unresolved"})
    if heading_kind == "fir" and _normalise(record.get("airspace")):
        # The heading names the FIR's airspace part; which part this crossing is in is not in the OFP's boundary rows.
        notice_conditions.append({"kind": "qualifier", "text": f"section {_normalise(record.get('heading'))}", "result": "unresolved"})
    if association == "unresolved" or not entry:
        notice_conditions.append({
            "kind": "association",
            "text": f"source FIR {fir}; route association and crossing time unresolved" if heading_kind == "fir" and not entry
            else _UNRESOLVED_OWNER if heading_kind == "unresolved"
            else f"owning FIR not established: printed under {_normalise(record.get('heading'))}" if heading_kind == "topic"
            else "FIR in effect at the segment not derivable from the boundary rows",
            "result": "unresolved",
        })

    # ---- every communication sentence is an action with its own conditions (its subject's, or its governing sentence's)
    ctx = {"names": names, "crossed": crossed, "fir": fir, "vertical": " ".join(vertical.group("phrase").split()) if vertical else None}
    parts = _action_sentences(text)
    printed = sentences(text)
    subjects = [_subject_of(part) for part in parts]
    scopes = [sentence_scope(part) for part in parts]
    actions: list[dict[str, Any]] = []
    for index, part in enumerate(parts):
        part_kind = procedure_kind(part, context)
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
        conditions.extend(_subject_conditions(subjects[index], flight, ctx))
        if part_kind == "atc_duty":
            if subjects[index]["kind"] == "other" and _OPERATING_SUBJECT.search(subjects[index].get("noun") or ""):
                # Unknown flight-population qualifications stay explicit.
                conditions.append({"kind": "population", "text": subjects[index]["noun"], "result": "unresolved"})
            for match in _EMBEDDED_SUBJECT.finditer(_semantic(part)):
                conditions.extend(_subject_conditions({"prefix": match.group("prefix").strip(),
                                                       "qualifier": match.group("qualifier").strip(), "leading": None}, flight, ctx))
        if governing is not None:
            conditions.extend(_subject_conditions(subjects[governing], flight, ctx))
        conditions.extend(_trailing_conditions(part, ctx))
        conditions.extend(_population_conditions(part, flight, ctx))
        effect = _instruction_effect(part, subjects[index])
        actor = "service" if effect == "availability" else _actor_of(part, subjects[index], governing)
        unresolved = _UNRESOLVED.search(classify_text(part))
        if unresolved:
            conditions.append({"kind": "other", "text": unresolved.group(0).lower().replace(" ", "-"), "result": "unresolved"})
        # The completeness boundary: whatever restriction the sentence prints that no rule above consumed (release-430 QA, F1).
        conditions.extend(_restriction_conditions(part, flight, ctx))
        # Preserve a subordinate/mixed MAY-before-SHALL statement without
        # guessing which activity or channel each modal governs.
        if _mixed_permission(part):
            conditions.append({"kind": "restriction", "text": part, "result": "unresolved", "note": _MIXED_MODAL_SCOPE})
        if effect == "capability":
            conditions.append({"kind": "qualifier", "text": part, "result": "unresolved", "note": "capability not held"})
        fallback = re.search(r"\bIN CASE OF NO CONTACT\b", classify_text(part))
        if fallback:
            conditions.append({"kind": "qualifier", "text": fallback.group(0), "result": "unresolved"})
        # Statements split from one printed sentence share its context (its reported event, the clearances it refers
        # to); each keeps its own circumstance ("IF CONTENTION EXISTS", "IF IN DOUBT").
        enclosing = next((s for s in printed if part in s), part)
        shared = enclosing if len(_statement_parts(enclosing)) > 1 else part
        conditions.extend(_report_conditions(shared, text))
        conditions.extend(_clearance_context(shared, text))
        conditions = _dedupe(conditions)
        details = printed_details(part)
        if route_frequencies is not None and not details["frequencies"]:
            details["frequencies"] = route_frequencies
        actions.append({
            "sentence": part,
            "kind": part_kind,
            "scope": scope,
            "actor": actor,
            "instruction_effect": effect,
            "directive": actor == "crew" and effect in ("instruction", "prohibited") and (bool(_DIRECTIVE.search(classify_text(part)) or _PRINTED_RADIO_ADVICE.search(classify_text(part)) or _ATC_REPORT.search(classify_text(part))) or subjects[index]["kind"] == "imperative"),
            "conditions": conditions,
            "applicability_state": _state_of(conditions),
            "printed_details": details,
        })
    if not actions:
        return None

    def rank(action: dict[str, Any]) -> tuple[int, int, int, int, int]:
        return (
            (1 if kind == "atc_duty" and action["scope"] == "unscoped" else 0) if _scope_compatible(action["scope"], relation) else 2,
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
    positive_call = is_call_line(headline)
    next_fir = _next_fir(crossings, fir) if positive_call and fir and scope == "fir_exit" else None
    latest = None
    window = None
    # A lead measured from take-off gives no clock before a FIR entry (ATC-EARLY-CALLS, v17).
    if positive_call and lead_minutes is not None and not _TAKEOFF_LEAD.search(details["lead"] or ""):
        anchor = None
        if scope == "fir_exit":
            anchor = next((row for row in crossings if next_fir and row["fir"] == next_fir["fir"] and row["actm"] == next_fir["actm"]), None)
        elif entry:
            anchor = entry
        if anchor and anchor["actm_minutes"] >= lead_minutes:
            latest = actm_text(anchor["actm_minutes"] - lead_minutes)
            window = call_window(details["lead"], anchor["actm_minutes"])

    return {
        "fir": fir,
        "notam_id": _normalise(record.get("notam_id")).upper(),
        "source_page": _integer(record.get("source_page")),
        "heading_page": _integer(record.get("heading_page")),
        **({"source_label": _normalise(record["source_label"]), "source_label_page": _integer(record.get("source_label_page"))}
           if record.get("source_label") else {}),
        "validity": validity,
        "heading": _normalise(record.get("heading")),
        "heading_kind": heading_kind,
        # The row is the statement it prints: its kind is the headline's (a notice holding a voice permission beside an
        # equipment duty headlines the duty and is not a call row).
        "kind": headline["kind"],
        "association": association,
        "instruction": instruction,
        "instruction_short": shorten(instruction),
        "note": _governed_note(record),
        "printed_details": details,
        "conditions": conditions,
        "applicability_state": state,
        "actor": headline["actor"],
        "instruction_effect": headline["instruction_effect"],
        "actions": [{k: v for k, v in action.items() if k != "directive"} for action in actions],
        "next_fir": next_fir,
        "latest_actm": latest,
        "call_window": window,
        "call_unit": (frequency_row["unit"] if frequency_row and route_frequencies is not None else call_unit(instruction)) if positive_call else None,
        "frequency_row": frequency_row["text"] if frequency_row and positive_call else None,
        "actm": entry["actm"] if entry else None,
        "sequence": entry["sequence"] if entry else None,
        "on_route": True if entry else None,
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
    return (line["kind"] in {"voice_contact", "tiba_broadcast", "contact_logon"} and line["applicability_state"] != "not_applicable"
            and line.get("actor", "crew") == "crew" and line.get("instruction_effect", "instruction") == "instruction"
            and not any(c.get("kind") == "restriction" and c.get("note") == _MIXED_MODAL_SCOPE for c in line.get("conditions") or []))


def has_printed_values(line: dict[str, Any]) -> bool:
    details = line.get("printed_details") or {}
    return bool(details.get("frequencies") or details.get("lead") or details.get("interval"))


def primary_procedure_line(lines: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The one row every page-6 ladder step prints in full and parity binds on both surfaces: in time order, the first
    call row whose printed conditions are held and that prints a frequency, else any printed value; then the same
    without held conditions; else the first call row, else the first row (ATC-PDF-PRIORITY, 2 Oct 2026)."""
    held = [l for l in lines if l.get("applicability_state") == "conditions_held"]
    return (
        next((l for l in held if is_call_line(l) and (l.get("printed_details") or {}).get("frequencies")), None)
        or next((l for l in held if is_call_line(l) and has_printed_values(l)), None)
        or next((l for l in lines if is_call_line(l) and (l.get("printed_details") or {}).get("frequencies")), None)
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
    if line.get("call_window"):
        parts.append(call_time_phrase(line["call_window"]))
    elif line.get("latest_actm"):
        # A record held before ATC-EARLY-CALLS carries no window; its own latest ACTM prints as it did.
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
        # Publish the generated event label in plain language while retaining
        # the held condition identity and literal source qualifiers.
        published = "reporting condition: " + text[len("report trigger: "):] if text.startswith("report trigger: ") else text
        return f"{published}: not evaluable from the OFP"
    if kind == "equipment":
        return f"equipment {text}: not held for this aircraft"
    if kind == "flight_rules":
        return f"flight rules {text}: not held in the analysis"
    if kind == "atc_request":
        return f"{text.lower()}: at ATC's request"
    if kind == "fir_scope":
        firs = condition.get("note") or ""
        if result == "met":
            return f"{text}: {firs} on the route"
        if result == "not_met":
            return f"{text}: {firs} not on the route"
        return f"{text}: " + ("not every FIR identified in the OFP" if firs else "FIR not identified in the OFP")
    if kind == "restriction":
        return f"{text}: not evaluable from the OFP"
    if kind == "population":
        return f"population {text}: not held for this aircraft"
    if kind == "association":
        return text
    return f"{text} condition not evaluable"


STATE_PHRASES = {"conditions_held": "conditions held", "conditions_unresolved": "conditions unresolved", "not_applicable": "not applicable"}


def conditions_summary(row: dict[str, Any]) -> str:
    """The row's conditions and state in one line; an ATC provision says so first (release-424 QA, F1)."""
    labels = ({"instruction": "ATC duty", "permission": "ATC permission", "availability": "ATC service availability", "not_required": "No ATC duty", "prohibited": "ATC restriction"}
              if row.get("kind") == "atc_duty" else {"permission": "Communications permission", "availability": "Communications availability", "not_required": "No call requirement", "prohibited": "Communication prohibition"})
    label = labels.get(row.get("instruction_effect"))
    if row.get("instruction_effect") == "capability":
        label = "Capability unresolved"
    actor_label = {"atc": "ATC provision", "other": "Other actor duty", "unresolved": "Actor unresolved"}.get(row.get("actor"))
    if row.get("actor") == "other" and row.get("instruction_effect") == "permission":
        actor_label = "Other actor permission"
    if row.get("actor") == "other" and row.get("instruction_effect") == "capability":
        actor_label = "Other actor capability unresolved"
    phrases = [actor_label] if actor_label else [label] if label else []
    phrases.extend(condition_phrase(c) for c in row.get("conditions") or [])
    phrases.append(STATE_PHRASES[row["applicability_state"]])
    return " · ".join(phrases)


def procedure_lines(procedures: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One printed row per FIR, text and applicability; notices that carry the same instruction share the row. Composed order kept."""
    lines: list[dict[str, Any]] = []
    for row in procedures:
        text = row["note"] or (row["instruction"] if row.get("instruction_effect") == "availability" or row.get("kind") == "atc_duty" else row["instruction_short"])
        summary = conditions_summary(row)
        line = next((item for item in lines if item["fir"] == row["fir"] and item["text"] == text and item["conditions_summary"] == summary
                     and item["actor"] == row["actor"] and item["instruction_effect"] == row["instruction_effect"] and item["actm"] == row["actm"]
                     and item["further_actions"] == max(0, len(row.get("actions") or []) - 1)), None)
        if line is not None:
            if row["notam_id"] not in line["notam_ids"]:
                line["notam_ids"].append(row["notam_id"])
            if row["source_page"] is not None and row["source_page"] not in line["source_pages"]:
                line["source_pages"].append(row["source_page"])
            continue
        lines.append({
            "fir": row["fir"], "actm": row["actm"], "sequence": row["sequence"], "text": text, "kind": row["kind"],
            "association": row["association"], "applicability_state": row["applicability_state"],
            "actor": row["actor"], "instruction_effect": row["instruction_effect"],
            "printed_details": {"frequencies": list(row["printed_details"]["frequencies"]), "lead": row["printed_details"]["lead"], "interval": row["printed_details"]["interval"], "addresses": list(row["printed_details"].get("addresses") or [])},
            "latest_actm": row["latest_actm"], "next_fir": dict(row["next_fir"]) if row["next_fir"] else None,
            "call_window": dict(row["call_window"]) if row.get("call_window") else None,
            "call_unit": row.get("call_unit"), "frequency_row": row.get("frequency_row"),
            "further_actions": max(0, len(row.get("actions") or []) - 1),
            "conditions_summary": summary,
            "notam_ids": [row["notam_id"]], "source_pages": [row["source_page"]] if row["source_page"] is not None else [],
        })
    for line in lines:
        line["source_pages"].sort()
    return lines


# ---------------------------------------------------------------- early calls (ATC-EARLY-CALLS, v17)


def is_early_call(line: dict[str, Any]) -> bool:
    """A crew call row (voice / TIBA / logon, conditions not failed) that prints a lead: a call due before an entry."""
    return is_call_line(line) and bool((line.get("printed_details") or {}).get("lead"))


def _untimed_reason(line: dict[str, Any]) -> str:
    lead = (line.get("printed_details") or {}).get("lead") or ""
    if _TAKEOFF_LEAD.search(classify_text(lead)):
        return "the lead is measured from take-off, not from a FIR entry"
    if not line.get("actm"):
        return f"{line['fir']} has no boundary row in this OFP" if line.get("fir") else "the owning FIR is not established from the source"
    if line.get("call_window") is None and line.get("latest_actm") is None and not line.get("next_fir") and _scope_is_exit(line):
        return "no next FIR follows in this OFP"
    return "the lead falls before take-off on the OFP ACTM"


def _scope_is_exit(line: dict[str, Any]) -> bool:
    return sentence_scope(line.get("text")) == "fir_exit"


def boundary_points(flight: dict[str, Any]) -> dict[str, str]:
    """"FIR ACTM" -> the route waypoint the OFP prints immediately before that FIR's boundary row (the entry point)."""
    points: dict[str, str] = {}
    previous: str | None = None
    for waypoint in flight.get("route_waypoints") or []:
        if not isinstance(waypoint, dict):
            continue
        fir = _normalise(waypoint.get("fir_boundary")).upper()
        minutes = _integer(waypoint.get("actm_minutes"))
        if fir:
            if previous and minutes is not None:
                points.setdefault(f"{fir} {actm_text(minutes)}", previous)
            continue
        name = _normalise(waypoint.get("name")).upper().lstrip("-")
        if name:
            previous = name
    return points


def early_calls(lines: list[dict[str, Any]], takeoff: datetime | None = None,
                points: dict[str, str] | None = None) -> list[dict[str, Any]]:
    """Every early call in the order it falls due; one with no derivable clock keeps its place after the timed ones and
    says why. Values are the row's own printed ones; the unit is the instruction's or its filed-route table row's."""
    calls: list[dict[str, Any]] = []
    for line in lines:
        if not is_early_call(line):
            continue
        details = line.get("printed_details") or {}
        window = line.get("call_window")
        next_fir = line.get("next_fir")
        due = (window.get("from_actm") or window.get("by_actm")) if window else None
        utc, day = _clock(takeoff, _minutes(due)) if due else (None, "")
        # A window's end gets its own clock (the entry, or the later end of a BETWEEN window).
        until_utc, until_day = (_clock(takeoff, _minutes(window["by_actm"])) if window and window.get("from_actm")
                                else (None, ""))
        calls.append({
            "fir": line.get("fir") or "",
            "kind": line["kind"],
            "action": CALL_ACTIONS[line["kind"]],
            "unit": line.get("call_unit"),
            "frequencies": list(details.get("frequencies") or []),
            "addresses": list(details.get("addresses") or []),
            "frequency_row": line.get("frequency_row"),
            "lead": details.get("lead"),
            "entry_fir": (next_fir or {}).get("fir") if next_fir else (line.get("fir") or None),
            "entry_actm": (next_fir or {}).get("actm") if next_fir else line.get("actm"),
            "entry_after": (points or {}).get(f"{(next_fir or {}).get('fir') if next_fir else line.get('fir')} "
                                              f"{(next_fir or {}).get('actm') if next_fir else line.get('actm')}"),
            "leaving_fir": line.get("fir") if next_fir else None,
            "call_window": dict(window) if window else None,
            "due_actm": due,
            "due_utc": utc,
            "due_day": day,
            "until_utc": until_utc,
            "until_day": until_day,
            "untimed_reason": None if window else _untimed_reason(line),
            "applicability_state": line["applicability_state"],
            "text": line["text"],
            "notam_ids": list(line["notam_ids"]),
            "source_pages": list(line["source_pages"]),
        })
    # Due time first; at one time a call that prints its frequencies, then one whose conditions are held, comes first.
    calls.sort(key=lambda call: (_minutes(call["due_actm"]) if call["due_actm"] else 10 ** 6, 0 if call["frequencies"] else 1,
                                 _STATE_RANK[call["applicability_state"]]))
    return calls


def early_call_sentence(call: dict[str, Any], compact: bool = False) -> str:
    """The one early-call sentence both surfaces print: when, what, to whom, on what, the printed lead and the entry.
    ``compact`` (page 6's last capacity step) names the selected table row by its route and transfer point only - the
    unit and frequencies the row gives are already in the sentence."""
    if call.get("call_window"):
        when = f"Early call {call_time_phrase(call['call_window'])}"
        if call.get("due_utc"):
            clock = f"{call['due_utc']}{' ' + call['due_day'] if call.get('due_day') else ''}"
            if call.get("until_utc"):
                clock += f" - {call['until_utc']}{' ' + call['until_day'] if call.get('until_day') else ''}"
            when += f" ({clock})"
    else:
        when = f"Early call, time not derived ({call.get('untimed_reason') or 'no entry time held'})"
    what = call["action"]
    if call.get("unit"):
        what += f" {call['unit']}"
    elif call["kind"] != "tiba_broadcast" and not call.get("leaving_fir"):
        what += " (unit not named in the notice)"
    if call.get("leaving_fir"):
        what += f" {'of ' if call.get('unit') else ''}the next FIR ({call['entry_fir']})"
    if call.get("frequencies"):
        what += f" on {', '.join(call['frequencies'])}"
    elif call["kind"] != "contact_logon":
        what += " (no frequency printed)"
    if call.get("addresses"):
        what += f", logon {', '.join(call['addresses'])}"
    entry = ""
    if call.get("entry_actm") and call.get("entry_fir"):
        entry = (f" - leaving {call['leaving_fir']}, {call['entry_fir']} entry ACTM {call['entry_actm']}" if call.get("leaving_fir")
                 else f" - {call['entry_fir']} entry ACTM {call['entry_actm']}")
        if call.get("entry_after") and not compact:
            entry += f" (boundary after {call['entry_after']})"
    row = ""
    if call.get("frequency_row"):
        row = (f" Source row {' '.join(call['frequency_row'].split()[:2])} (filed route)." if compact
               else f" Source row: {call['frequency_row']} (filed route).")
    return f"{when}: {what}; lead {call['lead']}{entry}.{row}"


def named_early_call(call: dict[str, Any]) -> str:
    """Page 6's last resort for a timed early call it cannot hold whole: its time, entry FIR, action, identity, page, state."""
    pages = ", ".join(f"p{page}" for page in call.get("source_pages") or []) or "page not held"
    unit = f" {call['unit']}" if call.get("unit") else ""
    frequencies = f" on {', '.join(call['frequencies'])}" if call.get("frequencies") else ""
    return (f"{call_time_phrase(call['call_window'])} {call.get('entry_fir') or call.get('fir')} {call['action']}{unit}{frequencies} "
            f"({', '.join(call['notam_ids'])}, {pages}, {call['applicability_state'].replace('_', ' ')})")


def untimed_call_pointer(call: dict[str, Any]) -> str:
    """How page 6 names an early call with no derived time when its row defers: FIR, identity and page."""
    pages = ", ".join(f"p{page}" for page in call.get("source_pages") or []) or "page not held"
    return f"early call {call.get('fir') or 'FIR not derived'} {', '.join(call['notam_ids'])} ({pages}), time not derived"


def compact_state_sentence(contact: dict[str, Any]) -> str | None:
    """The page-6 ladder's short state line: the early-call count first, then every notice outcome count."""
    procedures = contact.get("procedures") or []
    if not procedures or contact.get("required_calls"):
        return None
    counts = {state: sum(row["applicability_state"] == state for row in procedures)
              for state in ("conditions_held", "conditions_unresolved", "not_applicable")}
    calls = contact.get("early_calls") or []
    opening = (f"{len(calls)} early call(s) from the OFP's FIR notices. " if calls
               else "No approved early-call rule held. ")
    sentence = (opening + f"{len(procedures)} source-held ATC/communications notices: {counts['conditions_held']} conditions met, "
                f"{counts['conditions_unresolved']} unresolved, {counts['not_applicable']} not applicable.")
    if not (contact.get("extraction") or {}).get("current"):
        sentence += " Held extraction predates the current parser; update re-reads the OFP."
    return sentence


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
    # An allocation held before SLOT-ALLOCATION-434 names neither: that grammar read BOBCAT labels on page 1 only.
    printed_page = _integer(bobcat.get("source_page")) or _integer(evidence.get("page1"))
    pages = sorted({p for p in (printed_page, _integer(row.get("source_page")) if row else None) if p is not None and p > 0})
    level = bobcat.get("flight_level")
    return {
        "system": _normalise(bobcat.get("system")).upper() or "BOBCAT",
        "waypoint": waypoint,
        "flight_level": _integer(level) if _integer(level) is not None else (int(level) if level is not None else None),
        "ctot": _hhmm_z(_utc(bobcat.get("ctot_utc"))),
        "cto": _hhmm_z(_utc(bobcat.get("cto_utc"))),
        "actm": actm_text(actm_minutes) if actm_minutes is not None else None,
        "computed_cto": _hhmm_z(computed),
        "difference_minutes": difference,
        "source_pages": pages,
    }


def _slot_unread(flight: dict[str, Any]) -> dict[str, Any] | None:
    """An allocation the OFP prints that the grammar did not read, as the parser quoted it."""
    unread = flight.get("slot_allocation_unread")
    if not isinstance(unread, dict) or not _normalise(unread.get("text")):
        return None
    return {"text": _normalise(unread.get("text")), "source_page": _integer(unread.get("source_page")),
            "reason": _normalise(unread.get("reason")) or None}


def unread_slot_sentence(unread: dict[str, Any]) -> str:
    page = f" on OFP p{unread['source_page']}" if unread.get("source_page") else ""
    reason = f" ({unread['reason']})" if unread.get("reason") else ""
    return (f'A slot-control allocation is printed{page} but was not read{reason}: "{unread["text"]}". '
            "Use the OFP's printed allocation; no CTOT + ACTM check was made.")


def slot_sentence(slot: dict[str, Any] | None, unread: dict[str, Any] | None = None,
                  extraction: dict[str, Any] | None = None) -> str:
    if not slot:
        if unread:
            return unread_slot_sentence(unread)
        if extraction is not None and not extraction.get("current"):
            return (f"No slot-control allocation is held by this extraction ({extraction.get('rules') or 'rules not stated'}), "
                    "which predates the current parser; Create updated briefing re-reads the OFP.")
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
    met = sum(1 for row in procedures if row["applicability_state"] == "conditions_held")
    unresolved = sum(1 for row in procedures if row["applicability_state"] == "conditions_unresolved")
    not_applicable = sum(1 for row in procedures if row["applicability_state"] == "not_applicable")
    lines = procedure_lines(procedures)
    calls = early_calls(lines, takeoff, boundary_points(source))
    timed = sum(1 for call in calls if call["call_window"])
    if required_calls:
        state = "library_rules_held"
        state_sentence = f"{len(required_calls)} early-call requirement(s) from the approved reference library."
    elif procedures:
        state = "source_procedures_held"
        opening = (f"{len(calls)} early call(s) are read from this OFP's FIR notices ({timed} with a call time from the "
                   "OFP entry ACTM and the printed lead); no approved reference library is held. " if calls
                   else "No approved early-call rule is held. ")
        state_sentence = (
            opening + f"{len(procedures)} source-held ATC/communications notice(s): "
            f"printed conditions met on {met}, unresolved on {unresolved}, "
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
        if notam_pages:
            provenance += f" / NOTAM {_page_range(notam_pages)}"

    slot = _slot_control(source)
    unread = None if slot else _slot_unread(source)
    composed = {
        "rule": ENROUTE_CONTACT_RULE,
        "state": state,
        "state_sentence": state_sentence,
        "timing_basis": basis,
        "extraction": extraction,
        "crossings": crossings,
        "crossing_sequence": " · ".join(f"{row['fir']} {row['actm']}" for row in crossings),
        "source_pages": source_pages,
        "procedures": procedures,
        "procedure_lines": lines,
        "early_calls": calls,
        "other_procedure_count": other_procedure_count,
        "required_calls": required_calls,
        "slot_control": slot,
        "slot_unread": unread,
        "slot_sentence": slot_sentence(slot, unread, extraction),
        "provenance": provenance,
    }
    composed["compact_state_sentence"] = compact_state_sentence(composed)
    return composed


def crossing_sequence_limited(crossings: list[dict[str, Any]], limit: int = 24, compact: bool = False) -> str:
    """The PDF's whole-pair prefix rule: never a cut pair; the deferral is stated (in fewer words at the ladder's last step)."""
    pairs = [f"{row['fir']} {row['actm']}" for row in crossings]
    if len(pairs) <= limit:
        return " · ".join(pairs)
    suffix = "more on the dashboard" if compact else "more (ordered list with derived UTC on the dashboard)"
    return " · ".join(pairs[:limit]) + f" · +{len(pairs) - limit} {suffix}"
