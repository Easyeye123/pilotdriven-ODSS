"""Source-only fallback for airport NOTAMs whose old summary stated no restriction.

Port of web/src/lib/notam-restriction-line.mjs, including Review5 repairs.
This selects and decodes a filed clause; it does not decide applicability or
reclassify a NOTAM. Timing and specialist safety analysis remain in engines.py.
Source is never replaced: the original item E stays beside this compact line.

Status selection, clipping, conditional-list binding and completeness markers
must remain equivalent to the legacy JS fallback for previously saved packs.
"""
from __future__ import annotations

import re

from .notam_plain_words import NOTAM_PLAIN_WORDS

LINE_LIMIT = 190
SUPPLEMENT_LENGTH = 420

EXTRA_PLAIN_WORDS = ['AUTHORISATION',
 'AUTHORISATIONS',
 'AUTHORISED',
 'CENTRE',
 'CENTRED',
 'METRE',
 'METRES',
 'ORGANISATION',
 'RECOGNISED',
 'UTILISED',
 'PATHS',
 'TAKES',
 'VARY',
 'PARTLY',
 'SIMPLY',
 'INSIDE',
 'TAXIWAY',
 'TAXIWAYS',
 'TAXILANE',
 'RUNWAYS',
 'CLOSURES',
 'FEET',
 'FULLY']

ENVELOPE_RULES = ['^[A-Z]{1,2}\\d{3,5}\\/\\d{2}\\s+',
 "^(?:AIP\\s+(?:SUPPLEMENT|SUP|RESTRICTION)|AIC(?:\\s+RESTRICTION)?)\\s+[A-Z]{4}(?:\\/\\s?[A-Z][A-Z.'-]*)+(?:(?:\\s+[A-Z][A-Z./'-]{1,20}){0,3}(?:\\s+(?:INTL|INTERNATIONAL|NATIONAL|AIRPORT|APT|AP|AD|FIR)(?:\\/[A-Z][A-Z.'-]*)*\\b|(?=\\s+VALIDITY)))?\\s*",
 '\\bVALIDITY\\s*:?\\s*\\d{2}[A-Z]{3}\\d{2}(?:\\d{2})?(?:\\s*\\d{4}\\s*(?:UTC)?)?\\s*(?:EST)?\\s*(?:-|TO)\\s*(?:UFN|\\d{2}[A-Z]{3}\\d{2}(?:\\d{2})?(?:\\s*\\d{4}\\s*(?:UTC)?)?(?:\\s*EST)?)\\s*',
 '\\bVALIDITY\\s*:?\\s*\\d{2}[A-Z]{3}\\d{2}(?:\\d{2})?(?:\\s*EST)?\\s*-?\\s*(?:UFN)?\\s*']

RESTRICTION_STATES = [['CLSD', 3],
 ['CLOSED', 3],
 ['CLOSURE[S]?', 3],
 ['U/S', 3],
 ['UNSERVICEABLE', 3],
 ['UNSERVICEABILIT(?:Y|IES)', 3],
 ['UNSER', 3],
 ['INOP', 3],
 ['INOPERATIVE', 3],
 ['UNUSABLE', 3],
 ['USABLE UP TO', 2],
 ['COVERAGE UP TO', 2],
 ['USABLE LIMITS', 2],
 ['OUT OF SER(?:VICE|VC)?', 3],
 ['OUT OF SVC', 3],
 ['NOT AVBL', 3],
 ['NOT AVAILABLE', 3],
 ['UNAVAILABLE', 3],
 ['UNAVBL', 3],
 ['NOT USABLE', 3],
 ['NOT AUTH(?:ORI[SZ]ED)?', 3],
 ['NOT PERMITTED', 3],
 ['NOT ALLOWED', 3],
 ['NOT APPROVED', 3],
 ['NA', 2],
 ['NOT (?:BE )?AVBL', 3],
 ['NOT (?:BE )?AVAILABLE', 3],
 ['AUTH(?:ORI[SZ]ATION)? REQUIRED', 2],
 ['OBSTRUCTION[S]?', 2],
 ['PROHIBITED', 3],
 ['SUSPENDED', 3],
 ['SUSPENSION', 3],
 ['WITHDRAWN', 3],
 ['WITHDRAWAL', 3],
 ['DOWNGRADE[D]?', 2],
 ['DEGRADED', 2],
 ['DEACTIVATED', 3],
 ['DECOMMISSIONED', 3],
 ['BLOCKED', 3],
 ['LIMITED', 2],
 ['NIL', 2],
 ['WITHOUT', 2],
 ['AVBL (?:ONLY )?FOR', 2],
 ['AVAILABLE (?:ONLY )?FOR', 2],
 ['RESTRICTION[S]?', 2],
 ['RESTRICTED', 2],
 ['LIMITATION[S]?', 2],
 ['REDUCED', 2],
 ['DISPLACED', 2],
 ['OBSTRUCTED', 2],
 ['ON TEST', 2],
 ['DO NOT USE', 3],
 ['NOT TO STD', 2],
 ['NOT STD', 2],
 ['INCREASED TO', 2],
 ['SHALL NOT', 1],
 ['WIP', 1],
 ['WORK IN PROGRESS', 1],
 ['WORKS', 1],
 ['PARTIALLY AVBL', 2],
 ['RAISED', 2],
 ['MODIFIED', 1],
 ['INCREASE[D]?', 2],
 ['PERMITTED', 1],
 ['ONLY', 1],
 ['INSTEAD OF', 1],
 ['SHOULD NOT', 1],
 ['NOT APPLICABLE', 3],
 ['NOT ADHERED', 2],
 ['UNAVAILABILIT(?:Y|IES)', 3],
 ['TEST OPERATION', 2],
 ['TAKE-?OFF MINIMUMS', 2],
 ['ALTERNATE MINIMUMS', 2],
 ['MINIMUM CLIMB', 2]]

CHANGE_STATE_SOURCE = ('\\b(?:AMD|AMDT|AMEND(?:ED|MENT|MENTS)?|CHANGE[DS]?|REVISED|REVISION|REPLACED|TO READ|SHALL BE '
 'READ|SHALL|MUST|CAN BE|EFFECTIVE|TAKES '
 'EFFECT|WEF|ADJUSTED|ADJUSTMENT|ADDED|ADDITION|DELETED|INTRODUCED|INSTALLED|RELOCATED|CAUTION|CTN|REMINDED|REQUIRED|RQMNTS|TEMPO|IMPLEMENTATION)\\b')

SUBJECT_SOURCE = ('(?:RWY|RWYS|RUNWAY|RUNWAYS|TWY|TWYS|TAXIWAY|TAXIWAYS|TAXILANE|APRON|STAND|STANDS|BAY|BAYS|GATE|GATES|PARKING|ILS|LOC|LLZ|LOCALI[SZ]ER|GP|GLIDE '
 '?PATH|GLIDESLOPE|DME|VOR|NDB|TACAN|GBAS|GLS|PAPI|VASI|ALS|RVR|RTZL|DVOR|DDME|AREA|AIRSPACE|IAP|IAC|APCH|APPROACH|APPROACHES|SID|STAR|MINIMA|MINIMUMS|OCA|OCH|DA|MDA|LVP|TORA|TODA|ASDA|LDA|THR|THRESHOLD|AD|AP|AIRPORT|AERODROME|PROCEDURE|PROCEDURES|PROC|ARRIVAL|ARRIVALS|DEPARTURE|DEPARTURES|TRANSITION|RNP|RNAV|LPV|LNAV|VNAV|CIRCLING|MISSED)')

DESIGNATOR_PREFIX = '(?:RWY|RWYS|TWY|TWYS|ILS|LOC|GP|DME|VOR|NDB|APCH)'

SUBJECT_RANKS = [['\\b(?:AIRPORT|AERODROME)\\b', 5],
 ['\\b(?:RWY\\d|RWY|RWYS|RUNWAY|RUNWAYS)\\b', 4],
 ['\\b(?:ILS\\d|ILS|LOC|LLZ|LOCALI[SZ]ER|GP|GLIDE '
  '?PATH|GLIDESLOPE|DME|VOR|NDB|TACAN|GBAS|GLS|IAP|IAC|APCH|APPROACH|APPROACHES|SID|STAR|MINIMA|MINIMUMS|OCA|OCH|RNP|RNAV|LPV|LNAV|VNAV|PROC|PROCEDURE|PROCEDURES|TRANSITION|CIRCLING|MISSED|LVP)\\b',
  3],
 ['\\b(?:TWY\\d|TWY|TWYS|TAXIWAY|TAXIWAYS|TAXILANE)\\b', 2]]

NOTICE_TYPES = [['\\b(?:RESTRICTED AREA|DANGER AREA|PROHIBITED AREA|AIRSPACE '
  '(?:BLOCKED|RESERVATION|CLOSURE)|BLOCKED AIRSPACE|TEMPO RESTRICTED AREA)\\b',
  'Airspace area notice'],
 ['\\b(?:STAND|STANDS|BAY|BAYS|GATE|GATES|APRON|PARKING)\\b', 'Apron and stand notice'],
 ['\\b(?:IAP|IAC|INSTRUMENT APPROACH|ILS OR LOC RWY|RNAV\\s?\\((?:GPS|RNP)\\)|RNP RWY|VOR RWY|LOC '
  'RWY|ILS RWY|APCH PROC|APPROACH CHART)\\b',
  'Instrument approach procedure notice'],
 ['\\b(?:STAR|STANDARD ARRIVAL|ARRIVAL CHART)\\b', 'Arrival procedure notice'],
 ['\\b(?:SID|STANDARD INSTR(?:UMENT)? DEP|DEPARTURE CHART)\\b', 'Departure procedure notice'],
 ['\\b(?:MINIMA|MINIMUMS|OCA|OCH|DECISION ALTITUDE)\\b', 'Operating minima notice'],
 ['\\b(?:TWY|TWYS|TAXIWAY|TAXIWAYS|TAXILANE)\\b', 'Taxiway notice'],
 ['\\b(?:RWY|RWYS|RUNWAY|RUNWAYS)\\b', 'Runway notice'],
 ['\\b(?:ILS|LOC|LLZ|GP|DME|VOR|NDB|TACAN|GBAS|GLS|GNSS)\\b', 'Navigation aid notice'],
 ['\\b(?:AD|AP|AIRPORT|AERODROME)\\b', 'Aerodrome notice']]

CONTRACTIONS = {'ABV': 'above',
 'ACFT': 'aircraft',
 'ACT': 'active',
 'ADDN': 'additional',
 'ADJ': 'adjacent',
 'AVBL': 'available',
 'BLW': 'below',
 'BTN': 'between',
 'CLSD': 'closed',
 'CMPL': 'completed',
 'CTC': 'contact',
 'CTN': 'caution',
 'DEP': 'departure',
 'DEST': 'destination',
 'DLY': 'daily',
 'DUR': 'during',
 'ELEV': 'elevation',
 'EQPT': 'equipment',
 'EV': 'every',
 'EXC': 'except',
 'EXER': 'exercise',
 'FLT': 'flight',
 'FM': 'from',
 'FST': 'first',
 'GND': 'ground',
 'HLDG': 'holding',
 'INFO': 'information',
 'INOP': 'inoperative',
 'INSTL': 'installation',
 'INSTR': 'instrument',
 'LDG': 'landing',
 'LGT': 'light',
 'LGTD': 'lighted',
 'LGTS': 'lights',
 'LVL': 'level',
 'MAINT': 'maintenance',
 'MNT': 'monitor',
 'NML': 'normal',
 'OBST': 'obstacle',
 'OPR': 'operating',
 'OPS': 'operations',
 'PERM': 'permanently',
 'POSS': 'possible',
 'PROC': 'procedure',
 'PSN': 'position',
 'RMK': 'remark',
 'RQMNTS': 'requirements',
 'REF': 'refer to',
 'RTE': 'route',
 'SER': 'service',
 'SFC': 'surface',
 'SGL': 'signal',
 'SKED': 'scheduled',
 'STD': 'standard',
 'TEMPO': 'temporarily',
 'TFC': 'traffic',
 'THR': 'threshold',
 'TIL': 'until',
 'TKOF': 'take-off',
 'TWR': 'tower',
 'UFN': 'until further notice',
 'UNSER': 'unserviceable',
 'VCY': 'vicinity',
 'WEF': 'with effect from',
 'WI': 'within',
 'WIE': 'with immediate effect',
 'WIP': 'work in progress',
 'WRNG': 'warning',
 'U/S': 'unserviceable'}

PHRASES = [['\\bOUT OF (?:SER|SVC|SERVICE|SERVC)\\b', 'out of service'],
 ['\\bAS FLW\\b', 'as follows'],
 ['\\bAS FLW:', 'as follows:'],
 ['\\bFLW\\b', 'following'],
 ['\\bDUE WIP\\b', 'due to work in progress'],
 ['\\bDUE MAINT\\b', 'due to maintenance']]

PLAIN_SHORT_WORDS = ['ALL',
 'AN',
 'AND',
 'ANY',
 'ARE',
 'AS',
 'AT',
 'BE',
 'BUT',
 'BY',
 'CAN',
 'DAY',
 'DO',
 'DUE',
 'FLY',
 'FOR',
 'HAS',
 'IF',
 'IN',
 'IS',
 'IT',
 'ITS',
 'MAY',
 'NO',
 'NOT',
 'OF',
 'ON',
 'ONE',
 'OR',
 'END',
 'OFF',
 'OUT',
 'PER',
 'SEE',
 'THE',
 'TO',
 'TWO',
 'UP',
 'USE',
 'VIA',
 'WAS']

DESIGNATOR_CONTEXT_SOURCE = '^(?:RWY|RWYS|RUNWAY|RUNWAYS|TWY|TWYS|TAXIWAY|TAXIWAYS|TAXILANE|STAND|STANDS|BAY|BAYS|GATE|GATES|APRON|APN|PIER|CAT|CATS|CODE|INT|INTERSECTION|EXIT|LINK|HLDG|HOLDING|POINT|PAD|SPOT)$'

HEADER_CLAUSE_SOURCE = '^(?:[A-Z]{3}\\s+)?(?:IAP|SPECIAL|TAKEOFF MINIMUMS|ODP)\\b[^.]*,\\s*[A-Z]{2}$'

UNRESOLVED_SENTENCE = 'This analysis could not reduce the notice to one restriction line; open the full NOTAM.'

NO_TEXT_SENTENCE = 'The source NOTAM text is not held in this analysis, so no concise line can be derived.'

NO_STATEMENT_SENTENCE = 'This analysis could not read a statement from the held NOTAM text.'

# ASCII boundaries match the JS decoder's semantics, not locale-dependent words.
RESTRICTION_STATE_RE = re.compile(r'\b(?:' + '|'.join('(?:' + token + ')' for token, _ in RESTRICTION_STATES) + r')\b', re.ASCII)
STATE_SEVERITY_RULES = [(re.compile('^(?:' + token + ')$', re.ASCII), weight) for token, weight in RESTRICTION_STATES]
CHANGE_STATE_RE = re.compile(CHANGE_STATE_SOURCE, re.ASCII)
SUBJECT_RE = re.compile(r'\b(?:' + DESIGNATOR_PREFIX + r'\d|' + SUBJECT_SOURCE + r'\b)', re.ASCII)
SUBJECT_COUNT_RE = re.compile(SUBJECT_SOURCE, re.ASCII)


def _squash(value: object) -> str:
    return ' '.join(str(value if value is not None else '').split())


def strip_publication_envelope(value: str) -> str:
    text = re.sub(r'\.{2,}', '. ', _squash(value))
    for pattern in ENVELOPE_RULES:
        text = _squash(re.sub(pattern, ' ', text, count=1, flags=re.ASCII))
    return text


def _decode_token(token: str, previous: str = '') -> str:
    bare = re.sub(r"[^A-Za-z0-9/'.-]", '', token)
    prior = re.sub(r'[^A-Za-z]', '', previous).upper()
    if re.fullmatch(DESIGNATOR_CONTEXT_SOURCE, prior) and re.fullmatch(r'[A-Z]{1,2}[0-9]*', bare):
        return token
    expanded = CONTRACTIONS.get(bare.upper()) if bare and bare == bare.upper() else None
    if expanded:
        return token.replace(bare, expanded, 1)
    if re.search(r'''[0-9/'"]''', token):
        return token
    letters = re.sub(r'[^A-Za-z]', '', token)
    if not letters or letters.upper() != letters:
        return token
    plain = (len(letters) >= 2 and letters in PLAIN_SHORT_WORDS) if len(letters) <= 3 else letters in NOTAM_PLAIN_WORDS or letters in EXTRA_PLAIN_WORDS
    return token.lower() if plain else token


def decode_notam_text(value: str) -> str:
    text = _squash(value)
    for pattern, replacement in PHRASES:
        text = re.sub(pattern, replacement.upper(), text, flags=re.ASCII)
    tokens = text.split(' ')
    sentence = ' '.join(_decode_token(token, tokens[index - 1] if index else '') for index, token in enumerate(tokens))
    sentence = re.sub(r'^[a-z]', lambda match: match[0].upper(), sentence)
    return sentence if re.search(r'[.!?…]$', sentence) else sentence + '.'


def _split_statements(sentence: str) -> list[str]:
    # A condition under a colon is governed by its head, never a filed closure.
    # WMKK SX50/25 and SX51/25 regress if this guard is deleted.
    first_list, first_colon = sentence.find(';'), sentence.find(':')
    if first_list >= 0 and 0 <= first_colon < first_list:
        return [sentence]
    return re.split(r'(?<=;)\s+', sentence)


def _clauses(text: str) -> list[str]:
    text = re.sub(r'(?<![\d/.])\b(\d{1,2})\.\s+(?=[A-Z])', r'(\1) ', text, flags=re.ASCII)
    result = []
    for sentence in re.split(r'(?<=\.)\s+', text):
        for clause in _split_statements(sentence):
            clause = re.sub(r'^[)\]}»,:;.\s-]+', '', _squash(clause))
            clause = re.sub(r'^\d+(?:\.\d+)*\s+(?=[A-Z])', '', clause)
            clause = re.sub(r'^\d+(?:\.\d+)*\s+[-–—]\s+(?=[A-Za-z])', '', clause)
            clause = re.sub(r'\s+\d+(?:\.\d+)*$', '', clause)
            clause = re.sub(r'[.;,]$', '', clause)
            clause = re.sub(r'\s+[-–—:;,]$', '', clause)
            if len(clause) >= 6 and not re.search(HEADER_CLAUSE_SOURCE, clause, re.ASCII):
                result.append(clause)
    return result


def _clip(clause: str, state_index: int) -> str:
    if len(clause) <= LINE_LIMIT:
        return clause
    start = 0
    if state_index > LINE_LIMIT - 40:
        head = clause[:state_index]
        separator = max(head.rfind(': '), head.rfind(', '), head.rfind(' - '))
        if separator > 0 and state_index - separator < LINE_LIMIT - 40:
            start = separator + 2
        else:
            space = clause.rfind(' ', 0, max(0, state_index - 60) + 1)
            start = space + 1 if space > 0 else 0
    window = clause[start:]
    lead = '… ' if start > 0 else ''
    if len(window) <= LINE_LIMIT:
        return lead + window
    cut = window[:LINE_LIMIT]
    boundary = max(cut.rfind(', '), cut.rfind(' '))
    return lead + cut[:boundary if boundary > 60 else LINE_LIMIT].strip() + ' …'


def _state_severity(matched: str) -> int:
    return next((weight for pattern, weight in STATE_SEVERITY_RULES if pattern.fullmatch(matched)), 1)


def _score(clause: str, state_re: re.Pattern) -> int:
    states = [match[0] for match in state_re.finditer(clause)]
    subjects = SUBJECT_COUNT_RE.findall(clause)
    severity = max([1] + [_state_severity(state) for state in states]) if state_re is RESTRICTION_STATE_RE else 1
    # A closure named under a possible suspension condition is not a filed closure.
    if re.search(r'\bMAY BE SUSPENDED UNDER\b', clause) and ':' in clause:
        severity = min(severity, 2)
    named = min(len(states), 3) * 3 + min(len(subjects), 3)
    subject_rank = next((weight for pattern, weight in SUBJECT_RANKS if re.search(pattern, clause, re.ASCII)), 1)
    return severity * 1000 + named * 10 + subject_rank


def _ranked(clauses: list[str], state_re: re.Pattern) -> list[dict]:
    """Every clause that states a filed state, strongest first (ties keep source order)."""
    found = []
    for index, clause in enumerate(clauses):
        state = state_re.search(clause)
        if not state:
            continue
        previous = clauses[index - 1] if index else ''
        if SUBJECT_RE.search(clause):
            joined, used, at, join_at = clause, {index}, state.start(), -1
        elif previous and SUBJECT_RE.search(previous) and len(previous) + len(clause) <= LINE_LIMIT:
            joined, used, at = previous + ' - ' + clause, {index - 1, index}, len(previous) + 3 + state.start()
            join_at = len(previous.split(' '))
        else:
            continue
        found.append({'rank': _score(joined, state_re), 'joined': joined, 'at': at, 'used': used, 'last': index,
                      'join_at': join_at, 'text': _clip(joined, at)})
    return sorted(found, key=lambda item: -item['rank'])


def _with_marker(line: str, clauses: list[str], used: set[int]) -> str:
    # Only omitted content is known; a limited vocabulary cannot count the
    # notice's actual restrictions (Review5, Hong Kong AX32/24).
    if any(index not in used for index in range(len(clauses))):
        return line + ' ' + OMITTED_CONTENT_MARKER
    return line


def _lower_first(value: str) -> str:
    return value[0].lower() + value[1:] if re.match(r'^[A-Z][a-z]', value) else value


# ------------------------------------------------------------- copy guard

OMITTED_CONTENT_MARKER = 'This NOTAM has further content; open the full NOTAM.'
FIXED_MARKER_SENTENCES = (UNRESOLVED_SENTENCE, OMITTED_CONTENT_MARKER, NO_STATEMENT_SENTENCE, NO_TEXT_SENTENCE)
GATE_COPY_RUN = 18
GATE_COPY_MIN_WORDS = 3
MIN_KEPT_LENGTH = 12


def _gate_words(value: object) -> list[str]:
    return re.sub(r'[^A-Z0-9]+', ' ', str(value).upper()).split()


class _SourceCopy:
    def __init__(self, source: str):
        self.words = _gate_words(source)
        self.whole = ' '.join(self.words)
        count = len(self.words) - GATE_COPY_RUN + 1
        self.runs = sorted({' '.join(self.words[i:i + GATE_COPY_RUN]) for i in range(count)}) if count > 0 else []

    def copied_by(self, text: str) -> bool:
        body = ' '.join(_gate_words(text))
        if len(self.words) >= GATE_COPY_MIN_WORDS and self.whole in body:
            return True
        return body.count(' ') >= GATE_COPY_RUN - 1 and any(run in body for run in self.runs)


def _without_fixed_markers(text: str) -> str:
    body = text
    trimmed = True
    while trimmed:
        trimmed = False
        for sentence in FIXED_MARKER_SENTENCES:
            if body.endswith(sentence):
                body = body[:-len(sentence)].rstrip()
                trimmed = True
    return body


QUALIFIER_RE = re.compile(r'\b(?:EXC|EXCEPT|EXCEPTING|EXCLUDING|WHEN|IF|UNLESS|ONLY|CIV|CIVIL|NOT|NO|PROVIDED\s+THAT|SUBJECT\s+TO|(?:FOR|TO)\s+(?:ACFT|AIRCRAFT))\b', re.ASCII)
TIME_EXTENT_RE = re.compile(r'\b(?:DAILY|DLY|BTN|BETWEEN|UNTIL|TIL|DURING|DUR|H24|MON|TUE|WED|THU|FRI|SAT|SUN|JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC|UTC|CODE|MTOW|WINGSPAN|MAX|MAXIMUM|MINIMUM|WITHOUT)\b|\b\d{4}\s*-\s*\d{4}\b|\b\d{4}Z\b', re.ASCII)
SPACE_EXTENT_RE = re.compile(r'\b(?:ABV|ABOVE|BLW|BELOW|BEYOND|WI|WITHIN|SECTOR|SECT|RADIALS?|BRG|BEARING|QDM|QDR)\b|\bIN\s+(?:THE\s+)?AREA\b', re.ASCII)
COMPLEMENT_RE = re.compile(r'^\s*(?:(?:TO|AS|AT|BY|FROM|OF|UP\s+TO|ABOVE|BELOW|ABV|BLW)\s+)?\(?\d', re.ASCII)
TIME_COMPLEMENT_RE = re.compile(r'^\s*(?:(?:FROM|TO|UNTIL|TIL|BTN|BETWEEN)\s+)?\d{4}\b', re.ASCII)
CONDITION_RE = re.compile(r'\b(?:WHEN|IF|UNLESS|EXC|EXCEPT|EXCEPTING|PROVIDED\s+THAT)\b', re.ASCII)
OPERATIONAL_STATE_RE = re.compile(r'\b(?:NOT\s+(?:(?:BE|YET|CURRENTLY|REPORTED)\s+)?)?(?:CLSD|CLOSED|CLOSURE|CLOSES|OPEN|OPN|AVBL|AVAILABLE|UNAVAILABLE|U/S|UNSERVICEABLE|INOP|INOPERATIVE|SUSPENDED|WITHDRAWN|OUT\s+OF\s+(?:SERVICE|SER|SVC))(?![A-Z0-9])', re.ASCII)
ANNOUNCED_RE = re.compile(r'\b(?:THE\s+(?:FOLLOWING|FLW)|AS\s+(?:FOLLOWS?|FLW))\b|:$', re.ASCII)
HEAD_DEPENDENCY_RE = re.compile(r'[:]|\b(?:WHEN|IF|UNLESS|PROVIDED\s+THAT|SUBJECT\s+TO|EXC|EXCEPT|NOT|NO|OR|UNDER|DURING|WHILE|UNTIL|TIL|BEFORE|AFTER|ONCE|IN\s+CASE|MAY|MIGHT|COULD|FLW|FOLLOWING)\b', re.ASCII)
LABEL_HEAD_EXCLUSION_RE = re.compile(r'\b(?:WHEN|IF|UNLESS|MAY|MIGHT|COULD|EXC|EXCEPT|NOT|NO)\b', re.ASCII)
LABEL_NOUN_HEAD_RE = re.compile(r'\b(?:RMK|REMARKS?|NOTES?|DETAILS?|INTRODUCTION|SCOPE|BACKGROUND|PURPOSE)\s*:?$', re.ASCII)
REFERENCE_HEAD_RE = re.compile(r'^(?:REF|REFER|REFERENCE)\b', re.ASCII)
PURPOSE_HEAD_RE = re.compile(r'^(?:IN\s+ORDER\s+TO|TO\s+(?:FACILITATE|ENABLE|ALLOW|ACCOMMODATE|SUPPORT|PERMIT|ENSURE|PROVIDE))\b[^,:;]*,$', re.ASCII)
CAUSE_RE = re.compile(r'^(?:DUE|BECAUSE)$', re.ASCII)
REASON_AFTER_FOR_RE = re.compile(r'^(?:MAINT|MAINTENANCE|WIP|WORK|WORKS|CONST|CONSTRUCTION|RESURFACING|REPAIR|REPAIRS|INSPECTION)$', re.ASCII)
UNIT_RE = re.compile(r'^(?:FT|M|NM|SM|KM|DEG|KT|KTS|MHZ|KHZ|HZ|HPA|MB|PCT|PERCENT|UTC|Z|AMSL|AGL|MSL|HAT|MIN|SEC|KG|LB|LBS)(?![A-Z0-9])|^[)%]', re.ASCII)
LIST_ENTRY_RE = re.compile(r'^(?:[-–]\s*)?(?:[A-Z][A-Z0-9()/.-]*\s+){0,4}RWY\s?(\d{2}[LCR]?(?:/\d{2}[LCR]?)?)\s*:\s*\S', re.ASCII)
LIST_START_RE = re.compile(r'^(?:\(\d{1,2}\)\s|\d{1,2}\.\s|[-–]\s|(?:ACFT\s+)?CAT\s+[A-E](?:[/-][A-E])*:?\s+\d|[A-E]\s+\d)', re.ASCII)
LIST_LEAD_OUT_RE = re.compile(r'\s+AS\s+(?:FLW|FOLLOWS?)$', re.ASCII)
REMARK_HEAD_RE = re.compile(r'\b(?:RMK|REMARKS?|NOTES?)$', re.ASCII)
FUNCTION_WORDS = frozenset(
    'A AN THE AND OR NOR OF TO FOR AT IN ON BY WITH FROM VIA DUE AS IS ARE WAS WERE BE BEEN BEING WILL SHALL '
    'MAY CAN MUST SHOULD WOULD COULD NOT NO THAT WHICH WHO THIS THESE THOSE ITS THEIR INTO ONTO UPON PER THAN '
    'THEN SO IF WHEN UNLESS WHILE BETWEEN BTN TIL UNTIL EXC EXCEPT DURING DUR OVER UNDER ABOVE BELOW ABV BLW '
    'WI WITHIN BEYOND AFTER BEFORE FM ALL ANY EACH EVERY SOME BOTH OTHER SUCH'.split())
PHRASE_STARTERS = frozenset(
    'AND BUT FOR TO AT IN ON BY WITH FROM VIA DUE BECAUSE AS WHICH THAT WHO WHERE WHILE AFTER BEFORE DURING '
    'UNTIL TIL INTO ONTO UNDER OVER BETWEEN BTN WI WITHIN WHEN IF UNLESS THEN THEREFORE REF REFER SEE IAW '
    'PLEASE THE THIS THESE IS ARE WAS WERE WILL SHALL MAY CAN MUST SHOULD HAS HAVE BE NOT NO'.split())
DESIGNATOR_WORDS = frozenset(
    'RWY RWYS RUNWAY RUNWAYS TWY TWYS TAXIWAY TAXIWAYS TAXILANE TXL APRON APN STAND STANDS BAY BAYS GATE GATES '
    'PIER CAT CATS CODE INT INTERSECTION EXIT LINK HLDG HOLDING POINT PAD SPOT ILS LOC LLZ GP DME VOR NDB TACAN '
    'GBAS GLS PAPI VASI ALS RVR DVOR DDME IAP IAC APCH APPROACH SID STAR OCA OCH DA MDA THR THRESHOLD AD AP '
    'PROC PROCEDURE RNP RNAV LPV LNAV VNAV FREQ CH ID PSN ELEV'.split())
SEPARATORS = ('-', '–', '—')
# What a designator looks like once its noun has named it: "RWY 16-34", "TWY W4",
# "CAT A", "VOR 'PLS'". A head may end on the noun, never between it and this.
DESIGNATOR_TOKEN_RE = re.compile(r"^(?:[A-Z]{1,3}\d[A-Z0-9/-]*|\d{1,3}[LCR]?(?:\s?/\s?\d{1,3}[LCR]?)?[A-Z0-9/-]*|[A-Z]|'[A-Z0-9]+')$", re.ASCII)


def _bare(token: str) -> str:
    return re.sub(r'[^A-Z0-9/]', '', token.upper())


def _word(token: str) -> str:
    return re.sub(r'[,;:.]+$', '', token).upper()


def _decisive(text: str, state_re: re.Pattern) -> re.Match | None:
    """The statement a clause was chosen for: its strongest filed state."""
    matches = list(state_re.finditer(text))
    if not matches:
        return None
    if state_re is not RESTRICTION_STATE_RE:
        return matches[0]
    strongest = max(_state_severity(match[0]) for match in matches)
    return next(match for match in matches if _state_severity(match[0]) == strongest)


def _asserts_state(text: str) -> bool:
    return bool(RESTRICTION_STATE_RE.search(text) or OPERATIONAL_STATE_RE.search(text))


def _omission_allowed(kept: str, omitted: str, unavailable: bool = False) -> bool:
    """A kept statement must not lose what qualifies it.

    A condition is never cut short. Only the words up to the next filed state
    qualify a kept state; a later state carries its own qualifiers into the
    omitted remainder. Dropping where an outage applies only widens the
    outage, so an unavailable state may lose its spatial extent, never its
    time window, aircraft limits, conditions or exceptions.
    """
    condition = list(CONDITION_RE.finditer(kept))
    if condition and not re.search(r'[,;:]', kept[condition[-1].end():]):
        return False
    if not _asserts_state(kept):
        return True
    following = OPERATIONAL_STATE_RE.search(omitted)
    zone = omitted[:following.start()] if following else omitted
    # "Until further notice" leaves the state open-ended; it limits nothing.
    zone = re.sub(r'\b(?:UNTIL|TIL)\s+FURTHER\s+NOTICE\b|\bUFN\b', ' ', zone)
    if QUALIFIER_RE.search(zone):
        return False
    if (TIME_COMPLEMENT_RE if unavailable else COMPLEMENT_RE).match(zone):
        return False
    if ANNOUNCED_RE.search(kept):
        return True
    return not TIME_EXTENT_RE.search(zone) and (unavailable or not SPACE_EXTENT_RE.search(zone))


def _cut_is_clean(tokens: list[str], end: int, at_state: bool = False) -> bool:
    """A head may end only where the source starts a new phrase.

    A head that ends where the notice starts stating something is already at a
    boundary, so it is held only to the checks that keep a designator whole.
    """
    last, following = tokens[end - 1], tokens[end]
    word = _word(last)
    letters = re.sub(r'[^A-Z]', '', word)
    if word in SEPARATORS or word in FUNCTION_WORDS:
        return False
    if word in DESIGNATOR_WORDS and DESIGNATOR_TOKEN_RE.match(_word(following)):
        return False
    if len(letters) == 1 and word == letters and not re.search(r'[,;]$', last):
        return False
    upper = following.upper()
    if UNIT_RE.search(upper) or (re.match(r'^\(\d', upper) and re.search(r'\d\)?$', word)):
        return False
    punctuated = bool(re.search(r'[,;:]$', last)) or following in SEPARATORS
    starter = _word(following) in PHRASE_STARTERS or _word(following) in DESIGNATOR_WORDS or upper.startswith('(')
    if not (at_state or punctuated or starter):
        return False
    kept = ' '.join(tokens[:end])
    return kept.count('(') == kept.count(')')


def _render(tokens: list[str], start: int, end: int) -> str:
    kept = ' '.join(tokens[start:end])
    if end < len(tokens):
        kept = re.sub(r'[\s,;:–—-]+$', '', kept) + ' …'
    return decode_notam_text(('… ' if start else '') + kept)


def _reductions(clause: str, state_re: re.Pattern | None, join_at: int = -1) -> list[str]:
    """Source-bound shortenings of one clause, most preferred first."""
    tokens = clause.split(' ')
    offsets = []
    position = 0
    for token in tokens:
        offsets.append((position, position + len(token)))
        position += len(token) + 1
    count = len(tokens)
    decisive = _decisive(clause, state_re) if state_re is not None else None
    if state_re is not None and decisive is None:
        return []
    covered = lambda lo, hi: [i for i, (a, b) in enumerate(offsets) if a < hi and b > lo]
    state_tokens = covered(decisive.start(), decisive.end()) if decisive else []
    subject_tokens = {i for match in SUBJECT_RE.finditer(clause) for i in covered(match.start(), match.end())}
    state_spans = [(m.start(), m.end()) for regex in (RESTRICTION_STATE_RE, CHANGE_STATE_RE) for m in regex.finditer(clause)]

    def keeps(start: int, end: int, subject_needed: bool) -> bool:
        kept = ' '.join(tokens[start:end])
        if state_tokens and not (start <= state_tokens[0] and state_tokens[-1] < end):
            return False
        if subject_needed and subject_tokens and not any(start <= i < end for i in subject_tokens):
            return False
        return MIN_KEPT_LENGTH <= len(kept) <= LINE_LIMIT and end - start >= 2

    unavailable = decisive is not None and state_re is RESTRICTION_STATE_RE and _state_severity(decisive[0]) >= 3

    def allowed(start: int, end: int) -> bool:
        return _omission_allowed(' '.join(tokens[start:end]), ' '.join(tokens[end:]), unavailable)

    def cuts(start: int, subject_needed: bool) -> list[str]:
        found, rest = [], []
        first_end = max(state_tokens[-1] + 1 if state_tokens else start + 1, start + 1)
        # 1. The reason a restriction exists is not the restriction.
        for end in range(first_end, count):
            word = _bare(tokens[end])
            inside_state = any(a <= offsets[end][0] < b for a, b in state_spans)
            reason = (word == 'FOR' and end + 1 < count and not inside_state
                      and REASON_AFTER_FOR_RE.match(_bare(tokens[end + 1])))
            if CAUSE_RE.match(word) or reason:
                if keeps(start, end, subject_needed) and _cut_is_clean(tokens, end) and allowed(start, end):
                    found.append(_render(tokens, start, end))
                break
        # 2. The longest head that reads as the source wrote it.
        for end in range(count - 1, first_end - 1, -1):
            if keeps(start, end, subject_needed) and _cut_is_clean(tokens, end) and allowed(start, end):
                rest.append(_render(tokens, start, end))
        return found + rest

    if decisive is None:
        # No filed state: keep the notice's own subject when a cut can.
        return cuts(0, True) + cuts(0, False)
    lines = cuts(0, True)
    severity = _state_severity(decisive[0]) if state_re is RESTRICTION_STATE_RE else 0
    # 3. The decisive statement after a head it does not depend on.
    for start in range(1, state_tokens[0] + 1):
        previous = tokens[start - 1]
        head = ' '.join(tokens[:start])
        window = ' '.join(tokens[start:])
        lead_in = [token for token in tokens[start:state_tokens[0]] if _bare(token) not in FUNCTION_WORDS]
        subject_needed = True
        if start == join_at + 1:
            # A second source sentence, joined only to borrow a subject, may
            # stand alone when it names what it is about before its state.
            if len(lead_in) < 2 and not SUBJECT_RE.search(window):
                continue
            if not SUBJECT_RE.search(window):
                if state_re is RESTRICTION_STATE_RE and severity < 2:
                    continue
                if state_re is not RESTRICTION_STATE_RE and not any(re.search(r'\d', token) for token in lead_in):
                    continue
                if not (_asserts_state(head) or CHANGE_STATE_RE.search(head) or any(re.search(r'\d', token) for token in lead_in)):
                    continue
            subject_needed = False
        elif PURPOSE_HEAD_RE.match(head):
            # Why a restriction exists is not the restriction (as a cause is).
            if RESTRICTION_STATE_RE.search(head) or CONDITION_RE.search(head) or re.search(r'\b(?:NOT|NO)\b', head):
                continue
        elif REFERENCE_HEAD_RE.match(head) and _bare(tokens[start]) == 'REGARDING':
            if HEAD_DEPENDENCY_RE.search(head) or RESTRICTION_STATE_RE.search(head) or CHANGE_STATE_RE.search(head):
                continue
        elif previous.endswith(':') and ':' not in head[:-1] and ';' not in window and (
                start <= 3 or LABEL_NOUN_HEAD_RE.search(head[:-1].strip())):
            # A label introduces the statement that follows it; a condition,
            # a negation or a filed state makes the head govern it instead.
            if LABEL_HEAD_EXCLUSION_RE.search(head) or (start > 3 and (
                    RESTRICTION_STATE_RE.search(head) or CHANGE_STATE_RE.search(head))):
                continue
        else:
            if not (previous.upper() == 'AND' or previous in SEPARATORS or re.search(r'[,;]$', previous)):
                continue
            if HEAD_DEPENDENCY_RE.search(head) or not (RESTRICTION_STATE_RE.search(head) or CHANGE_STATE_RE.search(head)):
                continue
            if _bare(tokens[start]) in FUNCTION_WORDS:
                continue
        if keeps(start, count, subject_needed):
            lines.append(_render(tokens, start, count))
        lines += cuts(start, subject_needed)
    return lines


def _declared_list(clauses: list[str], picked: dict, basis: str) -> list[tuple[str, str, bool]]:
    """A heading that declares a list: publish the heading, and the runways each entry names.

    Returns (decoded line, basis, always-mark-omitted) in preference order.
    """
    clause = picked['joined']
    heading = re.match(r'^([^:;]{3,160}?)\s*:\s+(.*)$', clause)
    if not heading:
        return []
    head, rest = heading[1], heading[2]
    if REMARK_HEAD_RE.search(head) or re.search(r'\b(?:IF|WHEN|UNLESS|MAY|MIGHT|COULD)\b', head, re.ASCII):
        return []
    if not SUBJECT_COUNT_RE.search(head) and not RESTRICTION_STATE_RE.search(head):
        return []
    items = re.split(r';\s*', rest)
    entries = list(items) if all(LIST_ENTRY_RE.match(item) for item in items) else []
    last = picked['last']
    if entries:
        for following in clauses[picked['last'] + 1:]:
            if not LIST_ENTRY_RE.match(following):
                break
            entries.append(following)
            last += 1
    runway_list = len(entries) >= 2 and not re.search(r'\bRWY\s?\d', head, re.ASCII)
    if not runway_list and not LIST_START_RE.match(rest):
        return []
    decisive = _decisive(clause, RESTRICTION_STATE_RE)
    held = _decisive(head, RESTRICTION_STATE_RE)
    omitted = ' '.join([rest, *clauses[picked['last'] + 1:last + 1]])
    if not _omission_allowed(head + ':', omitted, held is not None and _state_severity(held[0]) >= 3):
        return []
    if basis == 'restriction_clause':
        if held is not None and _state_severity(held[0]) >= _state_severity(decisive[0]):
            line_basis = 'restriction_clause'
        elif CHANGE_STATE_RE.search(head) and _state_severity(decisive[0]) <= 1:
            line_basis = 'notice_type'
        else:
            return []
    elif SUBJECT_COUNT_RE.search(head) and decisive is None:
        line_basis = 'notice_type'
    else:
        return []
    head = LIST_LEAD_OUT_RE.sub('', head)
    lines = []
    if runway_list:
        runways = list(dict.fromkeys(LIST_ENTRY_RE.match(entry)[1] for entry in entries))
        lines.append((decode_notam_text(head + ': ' + ', '.join('RWY ' + runway for runway in runways)), line_basis, True))
    lines.append((decode_notam_text(head + ': …'), line_basis, False))
    return lines


US_RUNWAY_FACILITY_HEADER_RE = re.compile(r'^(?:([A-Z]{3})\s+)?(NAV\s+)?(?=(?:(?:ILS|LOC|GP|LDA|SDF)\s+)?RWY\s?\d)', re.ASCII)
MONTHS_AND_DAYS = frozenset('JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC MON TUE WED THU FRI SAT SUN'.split())


def strip_us_facility_header(body: str) -> str:
    """Drop a US NOTAM's accountable location and NAV keyword before a runway-named facility.

    "ORD ILS RWY 28L CAT II/III NA": ORD repeats the airport the card names and
    NAV only classifies the notice. Only a facility the runway designator
    names is eligible: in "SAX NAV VOR U/S" the location is the VOR itself.
    """
    header = US_RUNWAY_FACILITY_HEADER_RE.match(body)
    if not header or not header.group(0):
        return body
    location = header.group(1)
    if location and (location in PLAIN_SHORT_WORDS or location in CONTRACTIONS or location in MONTHS_AND_DAYS
                     or location in DESIGNATOR_WORDS or re.fullmatch(SUBJECT_SOURCE, location)
                     or location in ('NEW', 'OLD', 'ALL', 'TWO', 'ONE')):
        return body
    return body[header.end():]


def _candidates(source: str):
    body = strip_us_facility_header(strip_publication_envelope(source) or source) or source
    label = next((label for pattern, label in NOTICE_TYPES if re.search(pattern, body, re.ASCII)), '')
    # An affirmative suspension declaration can head a long numbered list.
    # Publish that declared scope and disclose the omitted list; clipping the
    # list would copy dates/designators while pretending to be a compact line.
    declaration = re.match(r'^(THE\s+(?:FLW|FOLLOWING)\s+.{1,160}?\s+PROCEDURES\s+ARE\s+(?:TEMPORARILY\s+)?(?:SUSPENDED|WITHDRAWN)):\s*(?:1\.|\(1\))\s+', body)
    clauses = _clauses(body)
    if declaration and not re.search(r'\b(?:IF|WHEN|UNLESS|MAY|MIGHT|COULD)\b', declaration[1]):
        yield decode_notam_text(declaration[1]) + ' ' + OMITTED_CONTENT_MARKER, 'restriction_clause'
    else:
        picked, basis, state_re = None, '', None
        title_state = RESTRICTION_STATE_RE.search(clauses[0]) if clauses and SUBJECT_RE.search(clauses[0]) else None
        if len(body) > SUPPLEMENT_LENGTH and title_state:
            picked = {'joined': clauses[0], 'at': title_state.start(), 'used': {0}, 'last': 0, 'join_at': -1,
                      'text': _clip(clauses[0], title_state.start())}
            basis, state_re = 'restriction_clause', RESTRICTION_STATE_RE
            alternates = []
        else:
            ranked, basis, state_re = _ranked(clauses, RESTRICTION_STATE_RE), 'restriction_clause', RESTRICTION_STATE_RE
            if not ranked:
                ranked, basis, state_re = _ranked(clauses, CHANGE_STATE_RE), 'notice_type', CHANGE_STATE_RE
            picked = ranked[0] if ranked else None
            # Another clause may stand in only if it bites at least as hard.
            alternates = [item for item in ranked[1:] if item['rank'] // 1000 >= picked['rank'] // 1000] if picked else []
        if picked:
            def publish(line: str, line_basis: str) -> str:
                return label + ': ' + _lower_first(line) if line_basis == 'notice_type' and label else line
            for choice in [picked, *alternates]:
                yield _with_marker(publish(decode_notam_text(choice['text']), basis), clauses, choice['used']), basis
                for line, line_basis, omitted in _declared_list(clauses, choice, basis):
                    named = publish(line, line_basis)
                    yield (named + ' ' + OMITTED_CONTENT_MARKER if omitted else _with_marker(named, clauses, choice['used'])), line_basis
                for line in _reductions(choice['joined'], state_re, choice['join_at']):
                    yield _with_marker(publish(line, basis), clauses, choice['used']), basis
        else:
            leads = [clause for clause in clauses if len(clause) >= 12]
            lead = next((clause for clause in leads if SUBJECT_RE.search(clause)), leads[0] if leads else '')
            if lead:
                yield decode_notam_text(_clip(lead, 0)) + ' ' + UNRESOLVED_SENTENCE, 'no_clause'
                for line in _reductions(lead, None):
                    yield line + ' ' + UNRESOLVED_SENTENCE, 'no_clause'
    if picked:
        # Last resort: the subject the source names, before it states anything,
        # with the unresolved marker. It is the notice's own opening words, so
        # it asserts nothing this analysis could not reduce.
        tokens = picked['joined'].split(' ')
        opening = min((match.start() for regex in (RESTRICTION_STATE_RE, CHANGE_STATE_RE)
                       for match in [regex.search(picked['joined'])] if match), default=-1)
        if opening > 0:
            end = len([token for token in re.finditer(r'\S+', picked['joined']) if token.start() < opening])
            if 2 <= end < len(tokens) and _cut_is_clean(tokens, end, at_state=True) and MIN_KEPT_LENGTH <= len(' '.join(tokens[:end])) <= LINE_LIMIT:
                yield _render(tokens, 0, end) + ' ' + UNRESOLVED_SENTENCE, 'no_clause'
    named = [re.sub(r'[-/]+$', '', match[0]) for match in re.finditer(r"\b(?:RWY|RWYS|TWY|TWYS|STAND|BAY|GATE)\s?\d[A-Z0-9/-]*|\b(?:ILS|LOC|GP|DME|VOR|NDB)(?:\s+'[A-Z0-9]+'|\s+RWY\s?\d[A-Z0-9/-]*)?", body, re.ASCII)]
    subject = next((name for name in named if re.search(r"[0-9']", name)), named[0] if named else '')
    scope = ' '.join(part for part in (label, 'for ' + _squash(subject) if subject else '') if part)
    if scope:
        yield scope + '. ' + UNRESOLVED_SENTENCE, 'no_clause'
    if label:
        yield label + '. ' + UNRESOLVED_SENTENCE, 'no_clause'


def derive_notam_restriction_line(raw_text: str) -> dict[str, str]:
    """Publish one source-derived line plus its evidence basis, never an empty template."""
    source = _squash(raw_text)
    if not source:
        return {'text': NO_TEXT_SENTENCE, 'basis': 'no_text'}
    copy = _SourceCopy(source)
    for text, basis in _candidates(source):
        if not copy.copied_by(_without_fixed_markers(text)) and not copy.copied_by(text):
            return {'text': text, 'basis': basis}
    return {'text': NO_STATEMENT_SENTENCE + ' ' + UNRESOLVED_SENTENCE, 'basis': 'no_clause'}
