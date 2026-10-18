"""QA520 (Codex's QA of release 520, 18 Oct 2026, output/pd-520-codex-qa-20261018), in this runtime.

Two P1 findings, one cause: an object of a temporal connective was accounted for by a part of it, not the whole. A
role word anywhere in the object licensed all of it - 'RWY 08R/26L CLSD DURING AIRPORT CURFEW' read active because
AIRPORT is a place (QA520-01); and a recognised connective whose operand was missing, separated by a comma, cut off or
empty left no accounting token behind - 'TWY J CLSD UNTIL.' and 'TWY Y CLSD AFTER, CURFEW.' read active (QA520-02).

Invariants checked here (the same in the app, tests/notam-timing-qa520-20261018.test.mjs):
  I7 an operand of a temporal connective is benign only if EVERY content token of it is positively classified as
     consistent with a non-temporal role its connective admits (scheduleField.temporalObject: admits, modifiers,
     designator, anaphora, leadModifier, placePart by OF, codes in a structure); its head is defined by a stated
     composition (English compounds are head-final: 'AIRPORT CURFEW' is a curfew) - a place word never classifies a
     temporal, event or unclassified head;
  I8 every temporal connective recognised in a restriction sentence creates an obligation, entered in one ledger per
     decision (explain_timing_ledger) and checked once at the end: discharged only by an operand read and accounted for
     against Item D or B/C, or positively classified under I7; a missing, separated, cut-off or empty operand - a comma,
     period or semicolon after the connective, the connective at the end of its clause, line or record - discharges
     nothing, and any undischarged obligation is a review.
The proof: Codex's preregistered 408-case oracle (tests/fixtures/notam-timing-codex-oracles-qa520.json.gz, the
evidence file's own bytes, SHA-256 6b448528...) at 408/408 and every earlier set unchanged; the ledger balances for every
decision of every corpus; two metamorphic transforms (tests/notam_timing_qa520_generators.py: roleWord, damage) over the
whole case base - Codex's seven sets exhaustively (and QA518's five I5 transforms over the 408), the QA514 compositional
matrix and the QA506/QA510 corpora by seeded sample (every record, a seeded variant per transform;
PD_TIMING_QA520_METAMORPHIC_FULL=1 runs every variant of every composition and every position of every corpus phrase)
- with sizes and results pinned; the seeded QA520 fuzzer.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import os
import re
from collections import Counter
from pathlib import Path

from app.odss.notam_timing import (
    LEDGER_DISCHARGED,
    LEDGER_STATUSES,
    build_timing_gazetteer,
    decide_lido_record,
    decide_notice_timing,
    explain_timing_ledger,
    read_lido_schedule_field,
    read_lido_validity,
)
from tests import notam_timing_qa514_generators as G514
from tests import notam_timing_qa518_generators as G518
from tests import notam_timing_qa520_generators as G
from tests import test_notam_timing_qa518_20261017 as Q518

ROOT = Path(__file__).resolve().parents[1]
ORACLE = ROOT / "tests" / "fixtures" / "notam-timing-codex-oracles-qa520.json.gz"
ORACLE_GZ_SHA256 = "f965ab88d27064ebaf96b969229f0990fc0c597d06fc65833d153747b30a8680"
PREREGISTERED_SHA256 = "6b4485284a8b60a7eb7c6473f726868e4afc97d5d7f5c088be7b5c028b7686eb"
EARLIER = ROOT / "tests" / "fixtures" / "notam-timing-codex-oracles-qa518.json.gz"
EARLIER_SIZES = {"q108": 108, "o126": 126, "t61": 61, "t59": 59, "t67": 67, "q412": 412}
RULES = json.loads((ROOT / "app" / "odss" / "notam_timing_rules.json").read_text(encoding="utf-8"))["scheduleField"]
KEYS = ("status", "stateAtReference", "minutesDelta", "outsideBy")
FULL = os.environ.get("PD_TIMING_QA520_METAMORPHIC_FULL") == "1"
SEED = 20261018
AUGUST = "01-AUG-26 0000 - 31-AUG-26 2359"
WINDOW = {"startsAt": "2026-08-16T07:00:00Z", "endsAt": "2026-08-16T11:00:00Z", "referenceAt": "2026-08-16T09:00:00Z"}

# pinned: the ledger per corpus [records, obligations, classified, accounted, chained, free, undischarged]; the app pins the same
LEDGER: dict = {"q108":[108,42,4,2,0,2,34],"o126":[126,47,0,7,0,0,40],"t61":[61,36,0,6,0,0,30],"t59":[59,7,0,0,0,1,6],"t67":[67,0,0,0,0,0,0],"q412":[412,274,12,0,0,4,258],"q408":[408,390,60,0,0,2,328],"vectors":[1492,1010,126,24,3,17,840],"compositional":[14319,4149,477,63,108,972,2529],"qa506":[145416,81032,1024,28095,0,10376,41537],"qa510":[113232,62912,168,68,0,9720,52956],"fuzz520":[20000,20272,4741,9,0,0,15522]}
# pinned: per base and transform [variant decisions, unchanged, moved to review]; the app pins the same
METAMORPHIC_CODEX: dict = {"q108":{"roleWord":[136,105,31],"damage":[266,218,48]},"o126":{"roleWord":[190,153,37],"damage":[357,279,78]},"t61":{"roleWord":[108,96,12],"damage":[252,216,36]},"t59":{"roleWord":[26,26,0],"damage":[49,49,0]},"t67":{"roleWord":[8,8,0],"damage":[7,7,0]},"q412":{"roleWord":[1592,1124,468],"damage":[1876,1468,408]},"q408":{"roleWord":[1812,1714,98],"damage":[1722,1326,396],"wrap":[27140,27140,0],"punctuate":[8186,8186,0],"wordClock":[408,344,64],"synonym":[338,338,0],"contactMove":[26,26,0]}}
METAMORPHIC_CODEX_DIGEST = "9001aedf9ab8ba3f78f33f3fc983ce35ac24f879cc6c176c5ab312fb2996cf33"
METAMORPHIC_COMPOSITIONAL: dict = {"roleWord":[15480,10170,5310],"damage":[15480,10345,5135]}
METAMORPHIC_COMPOSITIONAL_DIGEST = "5f010f305f80e817ae0a6fd5c4035425c8af9d4c0fc0b402777075260f20d95c"
METAMORPHIC_CORPORA: dict = {"qa506":{"roleWord":[25776,19633,6143],"damage":[25776,19638,6138]},"qa510":{"roleWord":[17853,17749,104],"damage":[17826,17700,126]}}
METAMORPHIC_CORPORA_DIGEST = "f7b04e60a83c864a7de90f1261d799b642c33cf954457b81293a05cc8c0c32a4"
FUZZ_DEFAULT: dict = {"cases": 20000, "decisions": 100000, "caseDigest": "9ed1715772f34abf657c15976bdaa2b56a08346fc9988ee44d01fbde0c2112db", "decisionDigest": "8b60590d09c66b609a545653348c292d96de5a86b88eab8f5c89cb83bba0c407"}
FUZZ_FULL: dict = {"cases": 200000, "decisions": 1000000, "caseDigest": "1ae992129461dcf79b51a18b36cf81c0344498a358f928741b12e7ab94f027f4", "decisionDigest": "eb4d071a65202a455a547ca0b42043e1693b5d8f83fbac2c66e68063a02b1029"}
# pinned: the gazetteer transforms {benign variants, review variants} and the gazetteer fuzz; the app pins the same
METAMORPHIC_GAZETTEER: dict = {"benign":740,"review":492}
FUZZ_GAZETTEER_DEFAULT: dict = {"cases": 20000, "decisions": 20000, "caseDigest": "2d1fb653d7a2298b18914ea7ff38455116f8725a989bd79deb92b7bbec77f2fe", "decisionDigest": "576418a2b577b61bef96d53fa160bc986a9109cb9173744c7e4f716a363ccf2d"}
FUZZ_GAZETTEER_FULL: dict = {"cases": 200000, "decisions": 200000, "caseDigest": "f5bdc2dfeb43bf5dbd805103d05071145b2eff98be1b77bc073d55294dfea083", "decisionDigest": "382d226ce5c6cedcd23c661bbdbc9fc3b9076d88cbe4cb226823fab465bc614b"}


def _pick(decision: dict) -> list:
    return [decision.get(key) for key in KEYS]


def _excluded(decision: dict) -> bool:
    return decision.get("status") == "outside_window" and decision.get("outsideBy") == "validity"


def _q408() -> list[dict]:
    raw = ORACLE.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == ORACLE_GZ_SHA256, "the app evaluates the same oracle bytes"
    text = gzip.decompress(raw)
    assert hashlib.sha256(text).hexdigest() == PREREGISTERED_SHA256, "Codex's preregistered file, byte for byte"
    return json.loads(text)["cases"]


def _sets() -> dict[str, list[dict]]:
    earlier = json.loads(gzip.decompress(EARLIER.read_bytes()).decode("utf-8"))["sets"]
    return {**earlier, "q408": _q408()}


def test_codex_qa520_preregistered_oracle_passes_and_every_earlier_set_is_unchanged() -> None:
    results, failures = {}, []
    for name, cases in _sets().items():
        passed = 0
        for c in cases:
            got = decide_lido_record(c["validity"], c["lines"], c["window"])
            ok = (c["reviewAllowed"] and got["status"] == "review") or all(got.get(k) == v for k, v in c["expected"].items())
            passed += ok
            if not ok and len(failures) < 25:
                failures.append(f'{name} {c["id"]} {c["lines"]}: {got["status"]}/{got.get("stateAtReference")}, want {c["expected"]}')
        results[name] = passed
    assert failures == []
    assert results == {**EARLIER_SIZES, "q408": 408}


CODEX_RECORDS = [  # Codex's labelled records Z7001-Z7008 (evidence/synthetic-injection.json), verbatim, at EGKK's 0900Z
    (["RWY 08R/26L CLSD DURING AIRPORT CURFEW."], "review"), (["DLY 1800-2000", "TWY Y CLSD DURING AERODROME CURFEW."], "review"),
    (["TWY J CLSD UNTIL."], "review"), (["DLY 1800-2000", "TWY T CLSD UNTIL."], "review"), (["TWY Y CLSD AFTER, CURFEW."], "review"),
    (["TWY T CLSD AFTER TWY B."], "active"), (["DLY 1800-2000", "CRANE HGT 387FT AMSL."], "later"),
    (["TWY T CLSD. CONTACT AIS DURING OFFICE HOURS."], "active")]
REVIEWS = ["RWY 08R/26L CLSD DURING AIRPORT CURFEW.", "AFTER AIRPORT CURFEW, RWY 08R/26L CLSD.", "TWY J CLSD DURING RUNWAY CURFEW.",
           "TWY J CLSD DURING CURFEW AT AIRPORT.", "TWY J CLSD AFTER RWY 08R CURFEW.", "TWY J CLSD DURING LOCAL CURFEW HOURS.",
           "TWY J CLSD OUTSIDE TERMINAL QUIET PERIOD.", "TWY J CLSD AFTER LAST AIRPORT FLIGHT.", "TWY J CLSD DURING THE PERIOD OF CURFEW.",
           "TWY J CLSD UNTIL AERODROME COMPLETION OF WORKS.", "TWY J CLSD AFTER ACFT AIRPORT.", "TWY J CLSD AFTER RWY END.", "TWY J CLSD AFTER RWY 08R END OF WORKS.",
           "TWY J CLSD DURING AIRPORT LDG.", "TWY J CLSD AFTER PASSING POINT OLILA.", "TWY J CLSD AT CHIBOUGAMAU.",
           "PAL 253.2MHZ AT CHIBOUGAMAU U/S.", "TWY J CLSD UNTIL.", "TWY J CLSD UNTIL THE.", "TWY J CLSD UNTIL ( ).",
           "TWY J CLSD AFTER, CURFEW.", "TWY J CLSD AFTER; TWY B.", "TWY J CLSD BEFORE. TWY B.", "TWY J CLSD FROM TWY B TO.",
           "TWY J CLSD BTN TWY B AND.", "TWY J CLSD AT THE INTERSECTION OF.", "TWY J CLSD ONLY. CURFEW.", "TWY J CLSD ONLY, CURFEW.",
           "TWY J CLSD AFTER", "TWY J CLSD EXC DURING CURFEW.", "TWY J CLSD BFR OR AFT CURFEW.", "TWY J CLSD WEF.",
           "TWY J CLSD DURING THE AIRPORT CURFEW PERIOD.", "TWY J CLSD AFTER THE END OF SKED FLT OPS.",
           "TWY J CLSD. AFTER THE, FOR EMERGENCY REQUESTS CONTACT ATC.", "TWY J CLSD. DURING THE LOCAL PRECEDING HOURS 24 HR."]
BENIGN = ["TWY J CLSD AFTER TWY B.", "TWY J CLSD AFTER AIRPORT TWY B.", "TWY J CLSD BEFORE HOLDING POINT B.", "TWY J CLSD AT APRON A.",
          "TWY J CLSD FROM TWY B TO TWY C.", "TWY J CLSD BTN TWY B AND TWY C.", "TWY J CLSD BTN TWY KE AND TWY MA.",
          "TWY J CLSD FROM THE NORTH END OF RWY 08R.", "TWY J CLSD AFTER THE EXIT FROM TWY B.", "TWY J CLSD AFTER ACFT STAND 517L.",
          "TWY J CLSD AT OR BLW 3000FT AMSL.", "CRANE OPR AT PSN 512739N 0002745W (HEATHROW).", "TWY J CLSD DURING THE AIRPORT CLOSURE.",
          "TWY J AVBL FOR CODE C ACFT ONLY.", "TWY J AVBL ONLY FROM TWY B.", "TWY J CLSD UNTIL FURTHER NOTICE.",
          "TWY J CLSD DURING THIS PERIOD.", "ATS RTE W10 NOT AVBL BTN BILAN AND POSIG.", "RWY 05 CLSD EXC SKED FLT.",
          "TWY Z9 MAY BE CLOSED AT SHORT NOTICE.", "TWY J CLSD. CONTACT AIS DURING OFFICE HOURS.", "TWY J CLSD EXCEPT FOR ACFT WITH PPR.",
          "TWY F BTN APCH END RWY 25L AND TWY B CLSD.", "WIND PANEL AT RWY 01R END U/S.",
          "RWY 16R/34L CLSD DUE TO MAINT EXC ACFT WITH PRIOR PERMISSION AT LEAST 1HR BFR."]


def test_qa520_codex_records_and_the_i7_i8_probes() -> None:
    """Z7001-Z7008 verbatim; a role word never licenses a temporal, event or unclassified token and a damaged operand is
    a review (with and without Item D); the controls each stated composition keeps benign stay benign."""
    want = {"review": ("review", "unknown_at_reference", None), "active": ("affecting", "active_at_reference", 0),
            "later": ("outside_window", "begins_after_reference", 540)}
    for lines, verdict in CODEX_RECORDS:
        got = decide_lido_record(AUGUST, lines, WINDOW)
        assert (got["status"], got.get("stateAtReference"), got.get("minutesDelta")) == want[verdict], (lines, got)
    for body in REVIEWS:
        for lines in ([body], ["DLY 1800-2000", body]):
            got = decide_lido_record(AUGUST, lines, WINDOW)
            assert got["status"] == "review", (lines, got)
    for body in BENIGN:
        got = decide_lido_record(AUGUST, [body], WINDOW)
        assert (got["status"], got.get("stateAtReference")) == ("affecting", "active_at_reference"), (body, got)
        got = decide_lido_record(AUGUST, ["DLY 1800-2000", body], WINDOW)
        assert (got["status"], got.get("minutesDelta")) == ("outside_window", 540), (body, got)


# ---- I8: the ledger balances ----------------------------------------------------------------------------------------
_OBJECT = RULES["temporalObject"]
_CONNECTIVE = re.compile("(?:" + "|".join(_OBJECT["connectives"].values()) + ")", re.ASCII)
_RANGE_AFTER = re.compile(f"(?:{_OBJECT['rangeEnd']['after']})", re.ASCII)
_RANGE_END = re.compile(f"(?:{_OBJECT['rangeEnd']['connective']})", re.ASCII)
_RESTRICTION = re.compile(f"(?<![A-Z0-9/])(?:{_OBJECT['restriction']})(?![A-Z0-9/])", re.ASCII)
_CLAUSE = re.compile(RULES["syntax"]["clauseBoundary"], re.ASCII)
_STATEMENT = re.compile(RULES["statement"], re.ASCII)


def _recount(masked: str, text: str) -> list[list]:
    """The connectives of every sentence, counted independently of the ledger, with whether their sentence holds a
    restriction: every word (split at spaces and at commas not before a digit) that a connective class names, or TO/
    UNTIL/TIL/TILL within rangeEnd.withinWords words after FROM/FM."""
    found, start = [], 0
    for boundary in [*_CLAUSE.finditer(text), None]:
        end = boundary.start() if boundary else len(masked)
        restricted = _RESTRICTION.search(masked[start:end]) is not None
        # words: split at spaces and at a comma not before a digit (a comma before a digit is inside a number)
        words = [(start + token.start() + piece.start(), piece.group())
                 for token in re.finditer(r"[^ ]+", masked[start:end])
                 for piece in re.finditer(r"(?:[^,]|,(?=[0-9]))+", token.group())]
        range_at = None
        for index, (at, word) in enumerate(words):
            if _CONNECTIVE.fullmatch(word) or (range_at is not None and index - range_at <= int(_OBJECT["rangeEnd"]["withinWords"])
                                               and _RANGE_END.fullmatch(word)):
                found.append([at, restricted])
            if _RANGE_AFTER.fullmatch(word):
                range_at = index
        start = boundary.end() if boundary else len(masked)
    return found


def _balance(lines: list[str], validity: dict, totals: Counter, failures: list[str], tag: str) -> None:
    ex = explain_timing_ledger(lines, validity)
    read = read_lido_schedule_field(lines, validity)
    problems = []
    if ex["read"] != read:
        problems.append("the explained read is not the read")
    ledger = ex["ledger"]
    if [[entry["connective"][0], entry["restricted"]] for entry in ledger] != _recount(ex["masked"], ex["text"]):
        problems.append(f"recognised connectives {[e['word'] for e in ledger]} != recount")
    statements = [match.span() for match in _STATEMENT.finditer(ex["masked"])]
    for entry in ledger:
        status = entry["status"]
        if status not in LEDGER_STATUSES:
            problems.append(f"{entry['word']}: status {status}")
        if status == "classified" and (any(item[3] is None for item in entry["tokens"])
                                       or (entry["operand"] != "openEnd" and not entry["tokens"])):
            problems.append(f"{entry['word']}: classified with an unclassified token")  # I7: every token, never some
        if status == "free" and entry["restricted"]:
            problems.append(f"{entry['word']}: free inside a restriction sentence")
        if status == "accounted" and (not entry["unclassified"] or not all(
                any(low <= start and end <= high for low, high in statements) for start, end in entry["unclassified"])):
            problems.append(f"{entry['word']}: accounted outside a statement")
        if status == "chained" and ledger[entry["chain"]]["status"] not in LEDGER_DISCHARGED:
            problems.append(f"{entry['word']}: chained to an undischarged obligation")
        if entry["operand"] == "missing" and status != "undischarged":
            problems.append(f"{entry['word']}: a missing operand discharged")
        totals[status] += 1
    if any(entry["status"] not in LEDGER_DISCHARGED for entry in ledger) and not read["review"]:
        problems.append("an undischarged obligation, yet no review")  # the balance: checked once, at the end
    totals["records"] += 1
    totals["obligations"] += len(ledger)
    if problems and len(failures) < 25:
        failures.append(f"{tag} {lines}: {problems}")


def _corpus(name: str):
    fixture = json.loads(gzip.decompress((ROOT / "tests" / "fixtures" / f"notam-timing-adversarial-{name}.json.gz").read_bytes()))
    for d, v, _family, _relation, text in fixture["phrases"]:
        for position in fixture["positions"]:
            words = text.split(" ")
            mid = max(1, len(words) // 2)
            subject = fixture["subject"]
            body = {"after": [f"{subject} {text}."], "before": [f"{text} {subject}."], "ownline": [f"{subject}.", f"{text}."],
                    "wrapped": [f"{subject} " + " ".join(words[:mid]), " ".join(words[mid:]) + "."],
                    "bracket": [f"{subject} ({text})."], "comma": [f"{subject}, {text}."]}[position]
            yield fixture, d, v, position, [*fixture["itemD"][d], *body]


def _row(totals: Counter) -> list[int]:
    return [totals["records"], totals["obligations"], *(totals[status] for status in LEDGER_STATUSES)]


def test_i8_the_ledger_balances_for_every_decision_in_every_corpus() -> None:
    """Every decision of every corpus - Codex's seven sets, the shared vectors, the QA514 compositional matrix, every
    phrase of the QA506/QA510 corpora at every position, the default QA520 fuzz cases: the recognised connectives are
    exactly those an independent recount finds, each obligation has one of the four statuses, a classified operand has
    every token classified (I7), an accounted one lies in statements, a chain ends discharged, a missing operand
    discharges nothing, and a read with no review has every obligation discharged."""
    failures: list[str] = []
    table = {}
    for name, cases in _sets().items():
        totals: Counter = Counter()
        for c in cases:
            _balance(c["lines"], read_lido_validity(c["validity"]), totals, failures, f"{name} {c['id']}")
        table[name] = _row(totals)
    totals = Counter()
    vectors = json.loads((ROOT / "tests" / "fixtures" / "notam-timing-vectors.json").read_text(encoding="utf-8"))
    for c in vectors["decisionCases"]:
        _balance(c["lines"], read_lido_validity(c["validity"]), totals, failures, c["id"])
    table["vectors"] = _row(totals)
    totals = Counter()
    for c in G514.compositions():
        _balance([*G514.ITEM_D[c["itemD"]], *c["lines"]], read_lido_validity(G514.VALIDITIES["AUG"]), totals, failures, c["kind"])
    table["compositional"] = _row(totals)
    for name in ("qa506", "qa510"):
        totals = Counter()
        for fixture, d, v, position, lines in _corpus(name):
            _balance(lines, read_lido_validity(fixture["validities"][v]), totals, failures, f"{name} {d} {v} {position}")
        table[name] = _row(totals)
    totals = Counter()
    for fc in G.fuzz520_cases(SEED, 20000):
        _balance([*G514.ITEM_D[fc["itemD"]], fc["line"]], read_lido_validity(G514.VALIDITIES[fc["validity"]]), totals, failures, fc["family"])
    table["fuzz520"] = _row(totals)
    print(f"ledger [records, obligations, classified, accounted, chained, free, undischarged]: {json.dumps(table)}")
    assert failures == []
    assert table == LEDGER, "the app pins the same ledgers"


# ---- metamorphic (a) roleWord and (b) damage ------------------------------------------------------------------------
def _verdict(transform: str, name: str, base: dict, got: dict, restriction: bool) -> str:
    """'same', 'review' or a violation: (a) unchanged or a review; (b) a review (lineBreak: unchanged or a review); a
    decision excluded by validity stays excluded by validity."""
    same = _pick(got) == _pick(base)
    if _excluded(base):
        return "same" if same else "VIOLATION: excluded by validity, yet decided otherwise"
    if got.get("status") == "review":
        return "same" if same else "review"
    if transform == "damage" and not name.endswith("lineBreak"):
        return f"VIOLATION: a damaged operand decided {got.get('status')}, not a review"
    return "same" if same else f"VIOLATION: neither unchanged nor a review ({got.get('status')})"


def _transform_record(variants, decide, base_decisions, stats: Counter, digest, tag: str, failures: list[str]) -> None:
    for transform, name, variant, restriction in variants:
        for base, got in zip(base_decisions, decide(variant)):
            verdict = _verdict(transform, name, base, got, restriction)
            stats[(transform, "n")] += 1
            stats[(transform, verdict if not verdict.startswith("VIOLATION") else "violation")] += 1
            digest.update((json.dumps([tag, transform, variant, _pick(got)], separators=(",", ":"), ensure_ascii=False) + "\n").encode())
            if verdict.startswith("VIOLATION") and len(failures) < 25:
                failures.append(f"{tag} {name} {variant}: {verdict}")


def _all_variants(lines: list[str]) -> list[tuple[str, str, list[str], bool]]:
    return [(transform, name, variant, restriction) for transform in G.TRANSFORMS
            for name, variant, restriction in G.variants(lines, transform)]


def _table(stats: Counter, transforms) -> dict:
    return {t: [stats[(t, "n")], stats[(t, "same")], stats[(t, "review")]] for t in transforms if stats[(t, "n")]}


PLACE_PREFIXES = ("prefix AIRPORT", "prefix AERODROME", "prefix RUNWAY", "prefix TERMINAL")


def test_metamorphic_codex_sets_every_variant_of_every_case() -> None:
    """(a) and (b) over every case of Codex's seven sets, every variant; QA518's five I5 transforms over the 408; a
    benign spatial control with a place word put before its operand stays benign (the place word keeps it classified)."""
    stats_by_set, digest, failures = {}, hashlib.sha256(), []
    benign = Counter()
    for name, cases in _sets().items():
        stats: Counter = Counter()
        for c in cases:
            base = decide_lido_record(c["validity"], c["lines"], c["window"])
            decide = lambda lines: [decide_lido_record(c["validity"], lines, c["window"])]  # noqa: E731
            variants = _all_variants(c["lines"])
            _transform_record(variants, decide, [base], stats, digest, f'{name} {c["id"]}', failures)
            if name == "q408":  # QA518's I5 transforms and their verdicts, over Codex's new set
                Q518._transform_record(c["lines"], Q518._all_variants(c["lines"]), decide, [base], stats, digest,
                                       f'{name} {c["id"]}', failures)
            if c.get("label", "").startswith("benign-spatial"):
                for transform, vname, variant, _ in variants:
                    if transform == "roleWord" and vname.endswith(PLACE_PREFIXES):
                        got = decide(variant)[0]
                        benign["n"] += 1
                        benign["same"] += _pick(got) == _pick(base)
                        if _pick(got) != _pick(base) and len(failures) < 25:
                            failures.append(f"benign control {c['id']} {variant}: {got['status']}, a place word before it")
        stats_by_set[name] = {**_table(stats, G.TRANSFORMS), **Q518._table(stats)}
    print(f"metamorphic QA520 codex: {json.dumps(stats_by_set)} benign spatial controls under a place prefix "
          f"{benign['same']}/{benign['n']} unchanged digest {digest.hexdigest()}")
    assert failures == []
    assert stats_by_set == METAMORPHIC_CODEX and digest.hexdigest() == METAMORPHIC_CODEX_DIGEST, \
        "the app pins the same variants and decisions"


def test_metamorphic_compositional_matrix_every_composition() -> None:
    validity = read_lido_validity(G514.VALIDITIES["AUG"])
    rng = G514.Mulberry32(SEED)
    stats: Counter = Counter()
    digest, failures = hashlib.sha256(), []
    for c in G514.compositions():
        lines = [*G514.ITEM_D[c["itemD"]], *c["lines"]]

        def decide(body: list[str]) -> list[dict]:
            read = read_lido_schedule_field(body, validity)
            return [decide_notice_timing({"validity": validity, "schedule": read["field"], "review": read["review"]}, window)
                    for window in G514.WINDOWS.values()]

        variants = _all_variants(lines) if FULL else [(t, n, v, r) for t, n, v, r in G.sample(lines, rng)]
        _transform_record(variants, decide, decide(lines), stats, digest, f'{c["kind"]}/{c["order"]}/{c["joiner"]}', failures)
    table = _table(stats, G.TRANSFORMS)
    print(f"metamorphic QA520 compositional{' FULL' if FULL else ''}: {json.dumps(table)} digest {digest.hexdigest()}")
    assert failures == []
    if not FULL:
        assert table == METAMORPHIC_COMPOSITIONAL and digest.hexdigest() == METAMORPHIC_COMPOSITIONAL_DIGEST, \
            "the app pins the same variants and decisions"


def test_metamorphic_qa506_qa510_corpora_every_phrase() -> None:
    """Every phrase of both corpora at one rotating position (FULL: at every position), a seeded variant per transform."""
    rng = G514.Mulberry32(SEED + 1)
    tables, digest, failures = {}, hashlib.sha256(), []
    for name in ("qa506", "qa510"):
        stats: Counter = Counter()
        fixture = json.loads(gzip.decompress((ROOT / "tests" / "fixtures" / f"notam-timing-adversarial-{name}.json.gz").read_bytes()))
        for index, (fx, d, v, position, lines) in enumerate(_corpus(name)):
            if not FULL and position != fixture["positions"][(index // len(fixture["positions"])) % len(fixture["positions"])]:
                continue
            validity = read_lido_validity(fx["validities"][v])

            def decide(body: list[str]) -> list[dict]:
                read = read_lido_schedule_field(body, validity)
                return [decide_notice_timing({"validity": validity, "schedule": read["field"], "review": read["review"]}, window)
                        for window in fx["windows"].values()]

            _transform_record(G.sample(lines, rng), decide, decide(lines), stats, digest, f"{name} {d} {v}", failures)
        tables[name] = _table(stats, G.TRANSFORMS)
    print(f"metamorphic QA520 corpora{' FULL' if FULL else ''}: {json.dumps(tables)} digest {digest.hexdigest()}")
    assert failures == []
    if not FULL:
        assert tables == METAMORPHIC_CORPORA and digest.hexdigest() == METAMORPHIC_CORPORA_DIGEST, \
            "the app pins the same variants and decisions"


def _run_fuzz(count: int) -> tuple[list[str], dict, Counter]:
    cases, digest = hashlib.sha256(), hashlib.sha256()
    failures: list[str] = []
    families: Counter = Counter()
    canonical: dict[tuple, dict] = {}
    decisions = 0
    for fc in G.fuzz520_cases(SEED, count):
        families[fc["family"]] += 1
        cases.update((json.dumps([fc["itemD"], fc["validity"], fc["line"]], separators=(",", ":"), ensure_ascii=False) + "\n").encode())
        validity = read_lido_validity(G514.VALIDITIES[fc["validity"]])
        read = read_lido_schedule_field([*G514.ITEM_D[fc["itemD"]], fc["line"]], validity)
        key = (fc["itemD"], fc["validity"], fc["base"])
        if key not in canonical:
            canonical[key] = read_lido_schedule_field([*G514.ITEM_D[fc["itemD"]], fc["base"]], validity)
        canon = canonical[key]
        for window in G514.WINDOWS.values():
            decisions += 1
            got = decide_notice_timing({"validity": validity, "schedule": read["field"], "review": read["review"]}, window)
            expected = decide_notice_timing({"validity": validity, "schedule": canon["field"], "review": canon["review"]}, window)
            digest.update((json.dumps(_pick(got), separators=(",", ":")) + "\n").encode())
            why = G.fuzz520_verdict(fc, got, expected)
            if why and len(failures) < 25:
                failures.append(f'{fc["family"]} {fc["itemD"]} {fc["validity"]} {fc["line"]!r}: {why}')
    return failures, {"cases": count, "decisions": decisions, "caseDigest": cases.hexdigest(), "decisionDigest": digest.hexdigest()}, families


def test_fuzz_qa520_seeded_role_compositions_and_damaged_operands_are_reviews_benign_compositions_stay_benign() -> None:
    full = os.environ.get("PD_TIMING_QA520_FUZZ_FULL") == "1"
    pinned = FUZZ_FULL if full else FUZZ_DEFAULT
    failures, result, families = _run_fuzz(pinned.get("cases", 200000 if full else 20000))  # full: 1,000,000 decisions
    print(f"fuzz QA520 seed {SEED}: {json.dumps(result)} families {json.dumps(dict(sorted(families.items())))}")
    assert failures == []
    assert result == pinned, "the app pins the same cases and decisions for the same seed"


# ---- QA520 gazetteer: places the briefing itself names -----------------------------------------------------------------
# LABELLED SYNTHETIC. The gazetteer is built per analysis from the OFP's own lines (build_timing_gazetteer, the same data
# in the app) and handed to the read; a token it names is a place. The app runs the same probes, transforms and fuzz.
GAZ_LINES = ["VRMM /MLE   MALE/VELANA INTL - DETAILED INFO", "----------", "RKPC /CJU   JEJU INTL /ADEQ", "----------",
             "VHHK        HONG KONG FIR", "----------", "WSAP RTE: WSSS SAMKO W407 VTK DCT OMKOM DCT TOPUN",
             "PILOTS SHOULD AVOID DCT EYE EXPOSURES"]
GAZ = build_timing_gazetteer(GAZ_LINES)
GAZ_BENIGN = ["TWY C CLSD AT VELANA INTERNATIONAL AIRPORT.", "TWY C CLSD AT VELANA INTERNATIONAL AIRPORT (VRMM).",
              "TWY J CLSD FROM RWY 07 OF RKPC.", "ILS/DME FOR RWY 07 AT JEJU INTL AIRPORT U/S.", "TWY J CLSD AFTER SAMKO.",
              "RWY 04 CLSD EXC FLT DEP FM HONG KONG INTL AP.", "TWY C CLSD FROM A POINT IMMEDIATELY SOUTH OF TWY D2."]
GAZ_REVIEW = ["TWY C CLSD DURING VELANA CURFEW.", "TWY C CLSD AT CHIBOUGAMAU.", "TWY C CLSD AT VELANA KELVINGROVE PARK.",
              "TWY C CLSD AFTER VRMM ACTIVATION.", "TWY J CLSD UNTIL TOPUN TEATIME.", "TWY J CLSD AFTER AVOID.",
              "TWY C CLSD FROM IMMEDIATELY."]


def test_qa520_gazetteer_names_places_and_nothing_else() -> None:
    """The briefing's own station and FIR headings and route fixes name places; a name it holds is a place, any other
    word and any temporal head stay reviews."""
    assert GAZ == {"names": ["HONG", "INTL", "JEJU", "KONG", "MALE", "VELANA"], "indicators": ["RKPC", "VHHK", "VRMM"],
                   "fixes": ["OMKOM", "SAMKO", "TOPUN"]}
    for body in GAZ_BENIGN:
        for lines, want in (([body], ("affecting", 0)), (["DLY 1800-2000", body], ("outside_window", 540))):
            got = decide_lido_record(AUGUST, lines, WINDOW, GAZ)
            assert (got["status"], got.get("minutesDelta")) == want, (lines, got)
        if "IMMEDIATELY" not in body:
            assert decide_lido_record(AUGUST, [body], WINDOW)["status"] == "review", body
    for body in GAZ_REVIEW:
        for lines in ([body], ["DLY 1800-2000", body]):
            assert decide_lido_record(AUGUST, lines, WINDOW, GAZ)["status"] == "review", lines


def test_metamorphic_qa520_gazetteer_wrap_and_punctuate_keep_every_probe() -> None:
    """Every wrap and punctuate variant (I5) of a gazetteer probe decides as the probe."""
    tally = {"benign": 0, "review": 0}
    failures: list[str] = []
    for bodies, want in ((GAZ_BENIGN, "affecting"), (GAZ_REVIEW, "review")):
        for body in bodies:
            for transform in ("wrap", "punctuate"):
                for name, lines in G518.variants([body], transform):
                    got = decide_lido_record(AUGUST, lines, WINDOW, GAZ)["status"]
                    tally["review" if want == "review" else "benign"] += 1
                    if got != want and len(failures) < 25:
                        failures.append(f"{transform} {name} {json.dumps(lines)}: {got}, not {want}")
    print(f"metamorphic QA520 gazetteer: {json.dumps(tally, separators=(',', ':'))}")
    assert failures == []
    assert tally == METAMORPHIC_GAZETTEER


def test_fuzz_qa520_gazetteer_named_places_benign_unnamed_and_event_heads_reviews() -> None:
    full = os.environ.get("PD_TIMING_QA520_FUZZ_FULL") == "1"
    pinned = FUZZ_GAZETTEER_FULL if full else FUZZ_GAZETTEER_DEFAULT
    count = pinned.get("cases", 200000 if full else 20000)
    cases, digest = hashlib.sha256(), hashlib.sha256()
    families: Counter = Counter()
    failures: list[str] = []
    canonical: dict[str, dict] = {}
    decisions = 0
    for fc in G.fuzz_gazetteer_cases(SEED + 2, count):
        families[fc["family"]] += 1
        cases.update((json.dumps([fc["itemD"], fc["line"]], separators=(",", ":"), ensure_ascii=False) + "\n").encode())
        key = "|".join(fc["itemD"])
        if key not in canonical:
            canonical[key] = decide_lido_record(AUGUST, [*fc["itemD"], "TWY J CLSD."], WINDOW, G.FUZZ_GAZETTEER)
        got = decide_lido_record(AUGUST, [*fc["itemD"], fc["line"]], WINDOW, G.FUZZ_GAZETTEER)
        decisions += 1
        digest.update((json.dumps(_pick(got), separators=(",", ":")) + "\n").encode())
        ok = (_pick(got) == _pick(canonical[key])) if fc["family"] == "named" else got["status"] == "review"
        if not ok and len(failures) < 25:
            failures.append(f"{fc['family']} {json.dumps([*fc['itemD'], fc['line']])}: {got['status']}")
    result = {"cases": count, "decisions": decisions, "caseDigest": cases.hexdigest(), "decisionDigest": digest.hexdigest()}
    print(f"fuzz QA520 gazetteer seed {SEED + 2}: {json.dumps(result)} families {json.dumps(dict(sorted(families.items())))}")
    assert failures == []
    assert result == pinned, "the app pins the same cases and decisions for the same seed"
