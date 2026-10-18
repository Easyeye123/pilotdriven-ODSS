"""QA518 (Codex's QA of release 518, 17 Oct 2026, output/pd-518-codex-qa-20261017), in this runtime.

Two P1 findings, one cause: a governance relation was read on the raw characters, and an unread temporal qualification
counted only when a detector knew its words. 'TWY J CLSD UNTIL "121.35"' (or [121.35], - 121.35, : 121.35) masked the
operand as a frequency because the quote or bracket stood between UNTIL and the number (QA518-01, active or +540
instead of a review); 'TWY T CLSD AFTER HALF PAST EIGHT' read as no schedule because no detector knew the words
(QA518-02).

Invariants checked here (the same in the app, tests/notam-timing-qa518-20261017.test.mjs):
  I5 every governance relation is read on the SYNTACTIC text - the body line with every piece of punctuation that can
     only wrap or join tokens removed (scheduleField.syntax; read_body_line): inserting or removing such punctuation
     anywhere around a span never changes a masking decision; clauses end only at syntax.clauseBoundary, defined once;
  I6 in a sentence that holds a restriction, the object of a temporal connective is temporal content unless a benign
     mask or a role its connective admits positively classifies it (scheduleField.temporalObject) - an unclassified
     object is a review, never 'no schedule';
  I1 (extended) numeric content in words is numeric content (accountedResidue.words): no clock is guessed from words.
The proof: Codex's six preregistered oracle sets (tests/fixtures/notam-timing-codex-oracles-qa518.json.gz) pass; five
metamorphic transforms (tests/notam_timing_qa518_generators.py: wrap, punctuate, wordClock, synonym, contactMove) over
the whole case base - Codex's sets exhaustively, the QA514 compositional matrix and the QA506/QA510 corpora by seeded
sample (every record, a seeded variant per transform; PD_TIMING_QA518_METAMORPHIC_FULL=1 runs every variant of every
composition and every position of every corpus phrase) - with sizes and results pinned; every connective list of the rules names every same-role synonym; the seeded QA518 fuzzer. The
labelled QA518 forms also run through every surface (the shared vectors and tests/fixtures/notam-timing-synthetic-
injection.json, in tests/test_notam_timing_qa500_surfaces_20261015.py and the parity census).
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
    decide_lido_record,
    decide_notice_timing,
    explain_schedule_free_text,
    read_body_line,
    read_lido_schedule_field,
    read_lido_validity,
)
from tests import notam_timing_qa514_generators as G514
from tests import notam_timing_qa518_generators as G

ROOT = Path(__file__).resolve().parents[1]
ORACLES = ROOT / "tests" / "fixtures" / "notam-timing-codex-oracles-qa518.json.gz"
ORACLES_SHA256 = "4ce0be5d08a5d1a9cddab8de9dd86fc23ad87f905716f797cae9756c226598c9"
ORACLE_SIZES = {"q108": 108, "o126": 126, "t61": 61, "t59": 59, "t67": 67, "q412": 412}
RULES = json.loads((ROOT / "app" / "odss" / "notam_timing_rules.json").read_text(encoding="utf-8"))["scheduleField"]
KEYS = ("status", "stateAtReference", "minutesDelta", "outsideBy")
FULL = os.environ.get("PD_TIMING_QA518_METAMORPHIC_FULL") == "1"
SEED = 20261017

# pinned: per base and transform [variant decisions, unchanged, moved to review]; the app pins the same
METAMORPHIC_CODEX: dict = {"q108":{"wrap":[7771,7771,0],"punctuate":[2307,2307,0],"wordClock":[142,88,54],"synonym":[31,31,0],"contactMove":[10,10,0]},"o126":{"wrap":[9042,9042,0],"punctuate":[2649,2649,0],"wordClock":[194,97,97],"synonym":[29,29,0],"contactMove":[4,4,0]},"t61":{"wrap":[4408,4408,0],"punctuate":[1199,1199,0],"wordClock":[154,106,48],"synonym":[23,23,0],"contactMove":[1,1,0]},"t59":{"wrap":[3275,3275,0],"punctuate":[834,834,0],"wordClock":[112,40,72],"synonym":[7,7,0]},"t67":{"wrap":[4598,4598,0],"punctuate":[1245,1245,0],"wordClock":[117,11,106],"synonym":[1,1,0]},"q412":{"wrap":[30934,30934,0],"punctuate":[9332,9332,0],"wordClock":[424,308,116],"synonym":[308,308,0],"contactMove":[92,92,0]}}
METAMORPHIC_CODEX_DIGEST = "a4c3100f7e13133cd4fa4abd207356386d90bba8cbe3e4d7ea6fb82c659436d8"
METAMORPHIC_COMPOSITIONAL: dict = {"wrap":[71595,71595,0],"punctuate":[71595,71595,0],"wordClock":[51075,24840,26235],"synonym":[11790,11790,0],"contactMove":[1800,1800,0]}
METAMORPHIC_COMPOSITIONAL_DIGEST = "d7265bf389cbfbddfb08abfb9fae68cfc3496bcf45a68967dbb15ad3444e64c7"
METAMORPHIC_CORPORA: dict = {"qa506":{"wrap":[72708,72708,0],"punctuate":[72708,72708,0],"wordClock":[66636,49717,16919],"synonym":[25464,25464,0]},"qa510":{"wrap":[56616,56616,0],"punctuate":[56616,56616,0],"wordClock":[31752,31114,638],"synonym":[20664,20664,0]}}
METAMORPHIC_CORPORA_DIGEST = "2b4013a08919371685ab8539d56529952c4300d356643d2e314b3790e8c6745d"
FUZZ_DEFAULT = {"cases": 20000, "decisions": 100000, "caseDigest": "3b49f4d5d11d22ca9ff8da0b72869ec9911acfd2bb25c0129bc63dbc225cc98f", "decisionDigest": "a4643b877798ff8668952d95ad31ee2bec27a83faa756b157e0f0c1b687d4da7"}
FUZZ_FULL = {"cases": 200000, "decisions": 1000000, "caseDigest": "48f35b641b412d83291a91fc661d9b69ea2ac856f360a413cb0ea70ad3d64e3b", "decisionDigest": "1fc00a9d05f2da3456debdf9d90f525f2209f2d7ab1f36d88b3d2701b75a13de"}


def _pick(decision: dict) -> list:
    return [decision.get(key) for key in KEYS]


def _excluded(decision: dict) -> bool:
    return decision.get("status") == "outside_window" and decision.get("outsideBy") == "validity"


def _oracles() -> dict:
    raw = ORACLES.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == ORACLES_SHA256, "the app evaluates the same oracle bytes"
    return json.loads(gzip.decompress(raw).decode("utf-8"))


def _verdict(transform: str, base: dict, got: dict, lines: list[str], variant: list[str], masked_clock: bool) -> str:
    """'same', 'review' or a violation: T1/T2 leave every body line's syntactic text and the decision unchanged; T3
    makes the decision a review unless the clock sat in a benign span; T4/T5 leave it unchanged or make it a review;
    a decision excluded by validity stays excluded by validity."""
    same = _pick(got) == _pick(base)
    if _excluded(base):
        return "same" if same else "VIOLATION: excluded by validity, yet decided otherwise"
    if transform in ("wrap", "punctuate"):
        if [read_body_line(line) for line in variant] != [read_body_line(line) for line in lines]:
            return "VIOLATION: the syntactic text changed"
        return "same" if same else "VIOLATION: the decision changed"
    if got.get("status") == "review":
        return "same" if same else "review"
    if transform == "wordClock" and not (masked_clock and same):
        return f"VIOLATION: a clock in words decided {got.get('status')}"
    return "same" if same else f"VIOLATION: neither unchanged nor a review ({got.get('status')})"


def _clock_masked(lines: list[str], li: int, start: int, end: int) -> bool:
    spans = explain_schedule_free_text(lines[li].upper())["spans"]
    return any(span["start"] <= start and end <= span["end"] for span in spans)


def _transform_record(lines: list[str], transforms: list[tuple[str, str, list[str], bool]], decide, base_decisions,
                      stats: Counter, digest, tag: str, failures: list[str]) -> None:
    for transform, name, variant, masked in transforms:
        decisions = decide(variant)
        for base, got in zip(base_decisions, decisions):
            verdict = _verdict(transform, base, got, lines, variant, masked)
            stats[(transform, "n")] += 1
            stats[(transform, verdict if not verdict.startswith("VIOLATION") else "violation")] += 1
            digest.update((json.dumps([tag, transform, variant, _pick(got)], separators=(",", ":"), ensure_ascii=False) + "\n").encode())
            if verdict.startswith("VIOLATION") and len(failures) < 25:
                failures.append(f"{tag} {name} {variant}: {verdict}")


def _all_variants(lines: list[str]) -> list[tuple[str, str, list[str], bool]]:
    out = []
    for transform in G.TRANSFORMS:
        if transform == "wordClock":
            out += [(transform, name, variant, _clock_masked(lines, li, start, end))
                    for name, variant, li, start, end in G.word_clock_variants(lines)]
        else:
            out += [(transform, name, variant, False) for name, variant in G.variants(lines, transform)]
    return out


def _sampled_variants(lines: list[str], rng) -> list[tuple[str, str, list[str], bool]]:
    out = []
    for transform, name, variant in G.sample(lines, rng):
        masked = False
        if transform == "wordClock":
            spot = next(item for item in G.word_clock_variants(lines) if item[0] == name)
            masked = _clock_masked(lines, spot[2], spot[3], spot[4])
        out.append((transform, name, variant, masked))
    return out


def _table(stats: Counter) -> dict:
    return {t: [stats[(t, "n")], stats[(t, "same")], stats[(t, "review")]] for t in G.TRANSFORMS if stats[(t, "n")]}


def test_codex_oracle_sets_pass_in_this_runtime() -> None:
    """Codex's preregistered sets: 108 (QA514), 126/61/59/67 (QA510) and the 412 QA518 matrix - every case."""
    oracles = _oracles()
    results = {}
    failures = []
    for name, cases in oracles["sets"].items():
        passed = 0
        for c in cases:
            got = decide_lido_record(c["validity"], c["lines"], c["window"])
            ok = (c["reviewAllowed"] and got["status"] == "review") or all(got.get(k) == v for k, v in c["expected"].items())
            passed += ok
            if not ok and len(failures) < 25:
                failures.append(f'{name} {c["id"]} {c["lines"]}: {got["status"]}/{got.get("stateAtReference")}, want {c["expected"]}')
        results[name] = passed
    assert failures == []
    assert results == ORACLE_SIZES


def test_qa518_codex_forms_and_the_i6_role_probes() -> None:
    """QA518-01/02 forms and the I6 probes: an unread temporal qualification is a review; a positively classified
    spatial, traffic, exception or anaphoric object is not."""
    august = "01-AUG-26 0000 - 31-AUG-26 2359"
    window = {"startsAt": "2026-08-16T07:00:00Z", "endsAt": "2026-08-16T11:00:00Z", "referenceAt": "2026-08-16T09:00:00Z"}
    reviews = ['TWY J CLSD UNTIL "121.35".', "TWY J CLSD UNTIL [121.35].", "TWY J CLSD UNTIL - 121.35.", "TWY J CLSD UNTIL : 121.35.",
               "TWY J CLSD UNTIL '121.35'.", "TWY J CLSD UNTIL “121.35”.", "TWY J CLSD AFT (121.35).", "TWY J CLSD (UNTIL) 121.35.",
               "TWY T CLSD AFTER HALF PAST EIGHT.", "RWY 08R/26L CLSD AFTER HALF PAST EIGHT.", "TWY T CLSD AFTER TEATIME.",
               "TWY T CLSD UNTIL SUNDOWN.", "TWY T CLSD DURING PRAYER.", "TWY T CLSD AT LUNCH.", "TWY T CLSD FOR MAINT AT LUNCH.",
               "TWY T CLSD 'UNTIL' TEATIME.", "TWY T CLSD (AFTER TEATIME).", "TWY T CLSD OUTSIDE CURFEW.", "TWY T CLSD EXCEPT WEEKENDS.",
               "TWY T CLSD AFTER LAST FLIGHT.", "TWY T CLSD UNTIL COMPLETION OF WORKS.", "TWY T CLSD BEFORE NIGHTFALL.",
               "TWY T CLSD WEF TEATIME.", "TWY T CLSD FROM TEATIME TO SUPPER.", "TWY T CLSD BTN BREAKFAST AND LUNCH.",
               "AFTER TEATIME TWY T CLSD.", "TWY T CLSD AFTER TEATIME TWY B.", "TWY T CLSD DURING THE TRIAL.", "TWY T CLSD AT DAYBREAK.",
               "TWY T CLSD UNTIL TEATIME FOR TWY B.", "TWY T CLSD. CONTACT CAA DURING OFFICE HOURS. TWY T CLSD AFTER HALF PAST EIGHT.",
               "TWY T CLSD AFTER SIX O'CLOCK.", "TWY T CLSD AFTER EIGHTEEN HUNDRED.", "TWY T CLSD DRG CURFEW.",
               "CRANE ERECTED. NO OPS DURING LOW VIS.",
               # QA520 I7 (18 Oct 2026): every token of the operand must be classified, and a place named only by a proper
               # name is classified by no role - this QA518 control was benign only through the 'governor' rule, which
               # licensed any word after a facility (the QA520-01 root)
               "PAL 253.2MHZ AT CHIBOUGAMAU U/S."]
    benign = ["TWY T CLSD AFTER TWY B.", "TWY T BTN TWY A AND TWY B CLSD.", "RWY 05 CLSD EXC SKED FLT.", "TWY T CLSD UFN.",
              "TWY T CLSD UNTIL FURTHER NOTICE.", "TWY T CLSD BEFORE THR 05.", "TWY T CLSD FM THR 05 TO TWY C.",
              "TWY T CLSD EXCEPT FOR ACFT WITH PPR.", "TWY T CLSD DURING THIS PERIOD.", "ATS RTE W10 NOT AVBL BTN BILAN AND POSIG.",
              "TWY T CLSD ONLY FOR CODE C ACFT.", "STAND 12 CLSD EXC HEL.",
              "TWY Z9 MAY BE CLOSED AT SHORT NOTICE. ACFT MAY EXPECT DELAYS.", "TWY T CLSD. DURING OFFICE HOURS CONTACT AIS.",
              "TWY J CLSD. CONTACT CAA DURING NORMAL OFFICE HOURS.", "TWY J CLSD (CONTACT CAA DURING NORMAL OFFICE HOURS).",
              'TWY J CLSD. "FREQ 122.850 MHZ".', "TWY J CLSD. [CRANE HGT 2350FT AMSL].", "TWY J CLSD. TWO MANDATORY INSTRUCTION MARKINGS."]
    for body in reviews:
        for lines in ([body], ["DLY 1800-2000", body]):
            got = decide_lido_record(august, lines, window)
            assert got["status"] == "review", (lines, got)
    for body in benign:
        got = decide_lido_record(august, [body], window)
        assert got["status"] == "affecting" and got["stateAtReference"] == "active_at_reference", (body, got)
    # a sentence is found on the unmasked text (the list labels '4.' and '4.1' are masked with their periods), and
    # operations ('MIXED-MODE OPS', 'NML OPS') are no restriction: these connectives qualify no restriction
    lines = ["TWY J CLSD.", "4. FLUCTUATIONS AT HKIA, PARTICULARLY DRG MIXED-MODE OPS. 4.1 DRG NML OPS PILOTS SHOULD MNT ILS."]
    got = decide_lido_record(august, lines, window)
    assert got["status"] == "affecting" and got["stateAtReference"] == "active_at_reference", (lines, got)


def test_i5_wrapping_and_joining_punctuation_never_changes_the_syntactic_text() -> None:
    same = [("TWY J CLSD UNTIL 121.35.", ['TWY J CLSD UNTIL "121.35".', "TWY J CLSD UNTIL [121.35].", "TWY J CLSD UNTIL - 121.35.",
                                           "TWY J CLSD UNTIL : 121.35.", "TWY J CLSD UNTIL ('121.35').", "TWY J CLSD UNTIL «121.35».",
                                           "TWY J CLSD (UNTIL) 121.35.", "TWY J CLSD UNTIL  121.35 .", "TWY J CLSD \"UNTIL 121.35\"."]),
            ("CRANE 3000' AMSL.", ["CRANE \"3000'\" AMSL.", "CRANE (3000') AMSL.", "[CRANE 3000'] AMSL."]),
            ("AUG 16 1800-", ["AUG 16 (1800-)", "AUG 16 1800-"]),
            ("OCA(OCH) 570 (367).", ["\"OCA(OCH)\" 570 (367).", "OCA(OCH) [570] (367)."]),
            ("AS (A)2020.", ["AS \"(A)2020\".", "AS [(A)2020]."]),
            ("TWY T CLSD AFTER HALF PAST EIGHT.", ["TWY T CLSD AFTER 'HALF PAST EIGHT'.", "TWY T CLSD AFTER: HALF PAST EIGHT."])]
    for plain, forms in same:
        for form in forms:
            assert read_body_line(form) == read_body_line(plain), (form, read_body_line(form), read_body_line(plain))
    # a clause ends only at a semicolon or a period followed by a space or the end; a period inside a number never ends one
    assert RULES["syntax"]["clauseBoundary"] == "[;]|\\.(?= |$)"
    assert all(re.search(RULES["syntax"]["clauseBoundary"], text) is None for text in ["121.35", "WWW.FAA.GOV", "CLSD.CONTACT"])


def test_every_connective_list_of_the_rules_names_every_same_role_synonym() -> None:
    """T4 by construction: a pattern that names one member of a same-role group (UNTIL/TILL/TIL, AFTER/AFT, BEFORE/BFR,
    DURING/DRG, BETWEEN/BTN, FROM/FM, EXCEPT/EXC) as an alternation item or a 'never after' guard names them all."""
    groups = RULES["connectiveSynonyms"]
    assert sorted(map(tuple, groups)) == sorted([("UNTIL", "TILL", "TIL"), ("AFTER", "AFT"), ("BEFORE", "BFR"), ("DURING", "DRG"),
                                                 ("BETWEEN", "BTN"), ("FROM", "FM"), ("EXCEPT", "EXC")])
    gaps = []

    def walk(obj, path):
        if isinstance(obj, str):
            items = set(re.findall(r"(?:^|(?<=[(|:]))([A-Z]{2,8})(?=[|)]|$)", obj))
            guards = set(re.findall(r"\(\?<!\\b([A-Z]{2,8}) \)", obj))
            for group in groups:
                for found in (items, guards):
                    present = [w for w in group if w in found]
                    if present and len(present) < len(group):
                        gaps.append(f"{path}: {group} has {present}")
        elif isinstance(obj, dict):
            for key, value in obj.items():
                if key not in ("note", "class", "rules", "quotes", "brackets", "quotePairs", "connectiveSynonyms",
                               "startPrepositions", "endPrepositions", "prepare"):
                    walk(value, f"{path}.{key}")
        elif isinstance(obj, list):
            for index, value in enumerate(obj):
                walk(value, f"{path}[{index}]")

    walk(RULES, "scheduleField")
    assert gaps == []


def test_metamorphic_codex_oracle_sets_every_variant_of_every_case() -> None:
    oracles = _oracles()
    stats_by_set = {}
    digest = hashlib.sha256()
    failures: list[str] = []
    benign_variants = 0
    for name, cases in oracles["sets"].items():
        stats: Counter = Counter()
        for c in cases:
            base = decide_lido_record(c["validity"], c["lines"], c["window"])
            variants = _all_variants(c["lines"])
            if c.get("label", "").startswith("benign"):
                benign_variants += sum(1 for v in variants if v[0] in ("wrap", "punctuate"))
            _transform_record(c["lines"], variants, lambda lines: [decide_lido_record(c["validity"], lines, c["window"])],
                              [base], stats, digest, f'{name} {c["id"]}', failures)
        stats_by_set[name] = _table(stats)
    print(f"metamorphic codex: {json.dumps(stats_by_set)} benign-control wrap/punctuate variants {benign_variants} digest {digest.hexdigest()}")
    assert failures == []
    assert stats_by_set == METAMORPHIC_CODEX and digest.hexdigest() == METAMORPHIC_CODEX_DIGEST, \
        "the app pins the same variants and decisions"


def test_metamorphic_compositional_matrix_every_composition() -> None:
    validity = read_lido_validity(G514.VALIDITIES["AUG"])
    rng = G.Mulberry32(SEED)
    stats: Counter = Counter()
    digest = hashlib.sha256()
    failures: list[str] = []
    for c in G514.compositions():
        lines = [*G514.ITEM_D[c["itemD"]], *c["lines"]]

        def decide(body: list[str]) -> list[dict]:
            read = read_lido_schedule_field(body, validity)
            return [decide_notice_timing({"validity": validity, "schedule": read["field"], "review": read["review"]}, window)
                    for window in G514.WINDOWS.values()]

        variants = _all_variants(lines) if FULL else _sampled_variants(lines, rng)
        _transform_record(lines, variants, decide, decide(lines), stats, digest, f'{c["kind"]}/{c["order"]}/{c["joiner"]}', failures)
    table = _table(stats)
    print(f"metamorphic compositional{' FULL' if FULL else ''}: {json.dumps(table)} digest {digest.hexdigest()}")
    assert failures == []
    if not FULL:
        assert table == METAMORPHIC_COMPOSITIONAL and digest.hexdigest() == METAMORPHIC_COMPOSITIONAL_DIGEST, \
            "the app pins the same variants and decisions"


def _corpus_records(name: str):
    fixture = json.loads(gzip.decompress((ROOT / "tests" / "fixtures" / f"notam-timing-adversarial-{name}.json.gz").read_bytes()))
    for index, (d, v, family, relation, text) in enumerate(fixture["phrases"]):
        positions = fixture["positions"] if FULL else [fixture["positions"][index % len(fixture["positions"])]]
        for position in positions:
            words = text.split(" ")
            mid = max(1, len(words) // 2)
            subject = fixture["subject"]
            body = {"after": [f"{subject} {text}."], "before": [f"{text} {subject}."], "ownline": [f"{subject}.", f"{text}."],
                    "wrapped": [f"{subject} " + " ".join(words[:mid]), " ".join(words[mid:]) + "."],
                    "bracket": [f"{subject} ({text})."], "comma": [f"{subject}, {text}."]}[position]
            yield fixture, d, v, [*fixture["itemD"][d], *body]


def test_metamorphic_qa506_qa510_corpora_every_phrase() -> None:
    """Every phrase of both corpora at one rotating position (FULL: at every position), a seeded variant per transform."""
    rng = G.Mulberry32(SEED + 1)
    tables = {}
    digest = hashlib.sha256()
    failures: list[str] = []
    for name in ("qa506", "qa510"):
        stats: Counter = Counter()
        for fixture, d, v, lines in _corpus_records(name):
            validity = read_lido_validity(fixture["validities"][v])

            def decide(body: list[str]) -> list[dict]:
                read = read_lido_schedule_field(body, validity)
                return [decide_notice_timing({"validity": validity, "schedule": read["field"], "review": read["review"]}, window)
                        for window in fixture["windows"].values()]

            _transform_record(lines, _sampled_variants(lines, rng), decide, decide(lines), stats, digest, f"{name} {d} {v}", failures)
        tables[name] = _table(stats)
    print(f"metamorphic corpora{' FULL' if FULL else ''}: {json.dumps(tables)} digest {digest.hexdigest()}")
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
    for fc in G.fuzz518_cases(SEED, count):
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
            why = G.fuzz518_verdict(fc, got, expected)
            if why and len(failures) < 25:
                failures.append(f'{fc["itemD"]} {fc["validity"]} {fc["line"]!r}: {why}')
    return failures, {"cases": count, "decisions": decisions, "caseDigest": cases.hexdigest(), "decisionDigest": digest.hexdigest()}, families


def test_fuzz_qa518_seeded_wrapped_operands_word_clocks_unknown_objects_are_reviews_wrapped_controls_stay_benign() -> None:
    pinned = FUZZ_FULL if os.environ.get("PD_TIMING_QA518_FUZZ_FULL") == "1" else FUZZ_DEFAULT
    failures, result, families = _run_fuzz(pinned["cases"])
    print(f"fuzz QA518 seed {SEED}: {json.dumps(result)} families {json.dumps(dict(sorted(families.items())))}")
    assert failures == []
    assert result == pinned, "the app pins the same cases and decisions for the same seed"
