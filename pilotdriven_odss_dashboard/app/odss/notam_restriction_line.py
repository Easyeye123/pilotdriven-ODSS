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


def _pick_clause(clauses: list[str], state_re: re.Pattern) -> tuple[str, set[int]] | None:
    best = None
    for index, clause in enumerate(clauses):
        state = state_re.search(clause)
        if not state:
            continue
        previous = clauses[index - 1] if index else ''
        if SUBJECT_RE.search(clause):
            joined, used, at = clause, {index}, state.start()
        elif previous and SUBJECT_RE.search(previous) and len(previous) + len(clause) <= LINE_LIMIT:
            joined, used, at = previous + ' - ' + clause, {index - 1, index}, len(previous) + 3 + state.start()
        else:
            continue
        rank = _score(joined, state_re)
        if best is None or rank > best[0]:
            best = rank, joined, at, used
    return (_clip(best[1], best[2]), best[3]) if best else None


def _with_marker(line: str, clauses: list[str], used: set[int]) -> str:
    # Only omitted content is known; a limited vocabulary cannot count the
    # notice's actual restrictions (Review5, Hong Kong AX32/24).
    if any(index not in used for index in range(len(clauses))):
        return line + ' This NOTAM has further content; open the full NOTAM.'
    return line


def derive_notam_restriction_line(raw_text: str) -> dict[str, str]:
    """Publish one source-derived line plus its evidence basis, never an empty template."""
    source = _squash(raw_text)
    if not source:
        return {'text': NO_TEXT_SENTENCE, 'basis': 'no_text'}
    body = strip_publication_envelope(source) or source
    clauses = _clauses(body)
    if len(body) > SUPPLEMENT_LENGTH and clauses and SUBJECT_RE.search(clauses[0]):
        state = RESTRICTION_STATE_RE.search(clauses[0])
        if state:
            return {'text': _with_marker(decode_notam_text(_clip(clauses[0], state.start())), clauses, {0}), 'basis': 'restriction_clause'}
    restriction = _pick_clause(clauses, RESTRICTION_STATE_RE)
    if restriction:
        return {'text': _with_marker(decode_notam_text(restriction[0]), clauses, restriction[1]), 'basis': 'restriction_clause'}
    label = next((label for pattern, label in NOTICE_TYPES if re.search(pattern, body, re.ASCII)), '')
    change = _pick_clause(clauses, CHANGE_STATE_RE)
    if change:
        decoded = decode_notam_text(change[0])
        if label:
            decoded = label + ': ' + (decoded[0].lower() + decoded[1:] if re.match(r'^[A-Z][a-z]', decoded) else decoded)
        return {'text': _with_marker(decoded, clauses, change[1]), 'basis': 'notice_type'}
    leads = [clause for clause in clauses if len(clause) >= 12]
    lead = next((clause for clause in leads if SUBJECT_RE.search(clause)), leads[0] if leads else '')
    if lead:
        return {'text': decode_notam_text(_clip(lead, 0)) + ' ' + UNRESOLVED_SENTENCE, 'basis': 'no_clause'}
    subject = re.search(r"\b(?:RWY|RWYS|TWY|TWYS|STAND|BAY|GATE)\s?\d[A-Z0-9/-]*|\b(?:ILS|LOC|GP|DME|VOR|NDB)(?:\s+'[A-Z0-9]+'|\s+RWY\s?\d[A-Z0-9/-]*)?", body, re.ASCII)
    scope = ' '.join(part for part in (label, 'for ' + _squash(subject[0]) if subject else '') if part)
    return {'text': (scope + '.' if scope else NO_STATEMENT_SENTENCE) + ' ' + UNRESOLVED_SENTENCE, 'basis': 'no_clause'}
