"""QA514 (Codex's QA of release 514, 17 Oct 2026, output/pd-514-codex-qa-20261017), in this runtime.

Three findings, one cause: the timing accounting trusted SHAPES, both ways. Temporal content counted only when a temporal
class recognised its shape, so "08000-10000", "8:3-9:3", "1.5H", "FROM EIGHT TO TEN", "AT 1,200" matched nothing and
read as no schedule (QA514-02); and a benign mask was licensed by its own words, never by what governs them - "OFFICE
HOURS" was masked although DURING/OUTSIDE tied it to the restriction (QA514-01), "121.9" although UNTIL governs it, while
a genuine contact clause ("CONTACT CAA DURING NORMAL OFFICE HOURS") was not recognised (QA514-03).

Invariants checked directly (the same in the app, tests/notam-timing-qa514-20261017.test.mjs):
  I1 every digit and every temporal token left after masking lies in a statement the grammar reads whole and that is
     accounted for; otherwise a review;
  I2 a benign mask never consumes the object of a temporal connective unless it is self-evidently not a time;
  I3 an office's hours are benign only when a contact verb governs them;
  I4 the decision is always the canonical decision (the record without the added text) or a review.
The compositional matrix and the seeded fuzzer come from tests/notam_timing_qa514_generators.py; both runtimes pin the
same digests. The labelled QA514 forms also run through every surface (card, PDF pages, PDF text, app records, chart)
in tests/test_notam_timing_qa500_surfaces_20261015.py and the parity census, from the synthetic injection fixture.
"""
from __future__ import annotations

import hashlib
import json
import os
import re

from app.odss.notam_timing import (
    decide_notice_timing,
    explain_schedule_free_text,
    read_lido_schedule_field,
    read_lido_validity,
)
from tests import notam_timing_qa514_generators as G

KEYS = ("status", "stateAtReference", "minutesDelta", "outsideBy")
COMPOSITION = {"records": 71595, "decisions": 357975, "caseDigest": "4424e73331c2b9bfbca8c8ce145d5a01faa43301e3055fc79f324d7bf6c8135a", "decisionDigest": "994926520ae975a6ecb384e46a6cf17f613a586c328758ae4227602c914653d0"}
FUZZ_SEED = 20261017
FUZZ_DEFAULT = {"cases": 20000, "decisions": 100000, "caseDigest": "1e3385675a5801211aa85178160173a0eb64e3e0dfa630da946c821d5abb47aa", "decisionDigest": "c75d4b2eae988a28c78c0a22287d0b2f504bf335ec7a6ade257de53806b4c2d6"}
FUZZ_FULL = {"cases": 200000, "decisions": 1000000, "caseDigest": "740cb12c03dd79681cf804cc118514afc3131c5cd6e0220d5883e8cdff2d5911", "decisionDigest": "c4c58d6d57d34e964bd23ec86ece1917c4cc69d01420180a95154eb27482e475"}

_A = re.ASCII
# I2, independently: what a span after a temporal connective must show to be benign (QA514 G2: a unit or a head noun
# after the number - 25 THR, 121.605 FREQUENCY, 2.2 TO SSYEM, a DME fix 4D, a legal title 49 USC).
_CONNECTIVE_BEFORE = re.compile(r"(?:^|[^A-Z0-9])(DURING|DRG|OUTSIDE|UNTIL|TILL|TIL|FROM|FM|BEFORE|BFR|AFTER|BTN|BETWEEN|AT|BY|"
                                r"WEF|TO|THRU|THROUGH|SINCE)(?: (?:THE|A|AN))?:? ?[(+#.]? ?$", _A)
_VALUE_LEAD = re.compile(r"(?:^|[^A-Z])(?:UP|SUBJECT|CHANGED|AMENDED|UPDATE|UPDATED|SET|REDUCED|INCREASED|REPLACED|VALUE|"
                         r"LIMITED|READ) $", _A)
_TIME_LED = re.compile(r"(?:[+(]? ?\d|(?:ONE|TWO|THREE|FOUR|FIVE|SIX|SEVEN|EIGHT|NINE|TEN|ELEVEN|TWELVE|NOON|MIDNIGHT|NIGHT|"
                       r"DAY|DAYS|HOURS?|HRS?|H|MIN|MAY|SUN|MON|TUE|WED|THU|FRI|SAT|JAN|FEB|MAR|APR|JUN|JUL|AUG|SEP|OCT|NOV|"
                       r"DEC|SR|SS|OFFICE|BUSINESS|WORKING|NORMAL)(?![A-Z0-9]))", _A)
_SELF_EVIDENT = re.compile(r"\d ?-?(?:FT|FEET|M|NM|KM|SM|KG|T|KT|KTS|DEG|DEGREES|PCT|%|AMSL|AGL|MSL|DME|FTAMSL)(?![A-Z0-9])"
                           r"|\bFL ?\d|\d ?FL\b|\d[NS] ?/? ?\d{3,8}(?:\.\d+)?[EW]\b|^\d{6,7}(?:\.\d+)?[NSEW]$|^\d{3,4} ?/? ?\("
                           r"|^SUN ?(?:REFLECTIONS?|GLARE|LIGHT)|^\d{1,2} (?:CFR|FAR)\b|^\d{1,3}(?:\.\d{1,2})? [A-Z]{2,4} DME$"
                           r"|\d ?-?(?:CM|TAC)(?![A-Z0-9])|^(?:0?[1-9]|[12]\d|3[0-6])[LRC]? THR$|^\d{2,3}\.\d{1,3} FREQUENCY$"
                           r"|^\d{1,3}(?:\.\d{1,2})? TO [A-Z]{5}$|^\d{1,2}D(?:\([A-Z]{3,4}\))?$|^\d{1,2} USC$", _A)


def _pick(decision: dict) -> str:
    return json.dumps([decision.get(key) for key in KEYS], separators=(",", ":"))


def _governance_breaches(text: str) -> list[str]:
    breaches = []
    for span in explain_schedule_free_text(text)["spans"]:
        value = text[span["start"]:span["end"]]
        before = text[:span["start"]]
        connective = _CONNECTIVE_BEFORE.search(before)
        if not (_TIME_LED.match(value) and connective) or _SELF_EVIDENT.search(value):
            continue
        if connective.group(1) in {"TO", "FROM", "FM", "BY"} and _VALUE_LEAD.search(before[:connective.start(1)]):
            continue
        breaches.append(f'{span["class"]}: "{value}" in "{text}"')
    return breaches


def test_compositional_qa514_the_outcome_the_syntax_gives_in_both_orders_six_joiners_with_and_without_item_d_at_every_edge() -> None:
    cases, digest = hashlib.sha256(), hashlib.sha256()
    failures: list[str] = []
    records = decisions = 0
    for c in G.compositions():
        cases.update((json.dumps([c["itemD"], c["lines"]], separators=(",", ":"), ensure_ascii=False) + "\n").encode())
        for text in G.VALIDITIES.values():
            validity = read_lido_validity(text)
            read = read_lido_schedule_field([*G.ITEM_D[c["itemD"]], *c["lines"]], validity)
            canon = read_lido_schedule_field([*G.ITEM_D[c["itemD"]], *c["base"]], validity)
            records += 1
            for reference, window in G.WINDOWS.items():
                decisions += 1
                got = decide_notice_timing({"validity": validity, "schedule": read["field"], "review": read["review"]}, window)
                expected = decide_notice_timing({"validity": validity, "schedule": canon["field"], "review": canon["review"]}, window)
                digest.update((_pick(got) + "\n").encode())
                if expected.get("status") == "outside_window" and expected.get("outsideBy") == "validity":
                    ok = got.get("status") == "outside_window" and got.get("outsideBy") == "validity"
                elif c["expect"] == "review":
                    ok = got.get("status") == "review"
                elif c["expect"] == "canonical":
                    ok = _pick(got) == _pick(expected)
                else:
                    ok = _pick(got) == _pick(expected) or got.get("status") == "review"
                if not ok and len(failures) < 25:
                    failures.append(f'{c["itemD"]} {text} {reference} {c["kind"]}/{c["order"]}/{c["joiner"]} {c["lines"]}: {got.get("status")}, want {c["expect"]}')
    print(f"compositional QA514: {records} records, {decisions} decisions, cases {cases.hexdigest()}, decisions {digest.hexdigest()}")
    assert failures == []
    assert {"records": records, "decisions": decisions, "caseDigest": cases.hexdigest(), "decisionDigest": digest.hexdigest()} == COMPOSITION, \
        "the app pins the same matrix and digests: both runtimes decide every composition the same"


def _run_fuzz(count: int) -> tuple[list[str], dict]:
    cases, digest = hashlib.sha256(), hashlib.sha256()
    failures: list[str] = []
    canonical: dict[tuple, dict] = {}
    decisions = 0
    for fc in G.fuzz_cases(FUZZ_SEED, count):
        cases.update((json.dumps([fc["itemD"], fc["validity"], fc["line"]], separators=(",", ":"), ensure_ascii=False) + "\n").encode())
        validity = read_lido_validity(G.VALIDITIES[fc["validity"]])
        read = read_lido_schedule_field([*G.ITEM_D[fc["itemD"]], fc["line"]], validity)
        key = (fc["itemD"], fc["validity"], fc["base"])
        if key not in canonical:
            canonical[key] = read_lido_schedule_field([*G.ITEM_D[fc["itemD"]], fc["base"]], validity)
        canon = canonical[key]
        line = fc["line"].upper()
        spans = explain_schedule_free_text(line)["spans"]
        for window in G.WINDOWS.values():
            decisions += 1
            got = decide_notice_timing({"validity": validity, "schedule": read["field"], "review": read["review"]}, window)
            expected = decide_notice_timing({"validity": validity, "schedule": canon["field"], "review": canon["review"]}, window)
            digest.update((_pick(got) + "\n").encode())
            why = G.fuzz_verdict(fc, line, spans, got, expected)
            if why and len(failures) < 25:
                failures.append(f'{fc["itemD"]} {fc["validity"]} {fc["line"]!r}: {why}')
    return failures, {"cases": count, "decisions": decisions, "caseDigest": cases.hexdigest(), "decisionDigest": digest.hexdigest()}


def test_fuzz_qa514_seeded_an_unmasked_digit_is_a_review_a_masked_one_fits_its_class_the_decision_is_canonical_or_a_review() -> None:
    pinned = FUZZ_FULL if os.environ.get("PD_TIMING_QA514_FUZZ_FULL") == "1" else FUZZ_DEFAULT
    failures, result = _run_fuzz(pinned["cases"])
    print(f"fuzz QA514 seed {FUZZ_SEED}: {json.dumps(result)}")
    assert failures == []
    assert result == pinned, "the app pins the same cases and decisions for the same seed"


def test_i2_qa514_no_benign_span_is_the_object_of_a_temporal_connective_unless_self_evidently_not_a_time() -> None:
    breaches: list[str] = []
    for c in G.compositions():
        breaches += _governance_breaches(" ".join(c["lines"]))
    for fc in G.fuzz_cases(FUZZ_SEED, FUZZ_DEFAULT["cases"]):
        breaches += _governance_breaches(fc["line"].upper())
    assert list(dict.fromkeys(breaches))[:25] == []


def test_qa516_a_clock_in_digits_of_any_script_is_never_read_as_a_value_free_text_item_d_or_validity_is_a_review() -> None:
    """I1: a digit is any Unicode decimal digit (str.isdecimal()); Arabic-Indic, Extended Arabic-Indic, Devanagari,
    Bengali, Thai or Adlam digits, or ASCII mixed with them, are never read as values."""
    august = read_lido_validity("01-AUG-26 0000 - 31-AUG-26 2359")
    clocks = ["\u0660\u0668\u0660\u0660-\u0661\u0660\u0660\u0660", "\u06F0\u06F8\u06F0\u06F0-\u06F1\u06F0\u06F0\u06F0",
              "\u0966\u096E\u0966\u0966-\u0967\u0966\u0966\u0966", "\u09E6\u09EE\u09E6\u09E6-\u09E7\u09E6\u09E6\u09E6",
              "\u0E50\u0E58\u0E50\u0E50-\u0E51\u0E50\u0E50\u0E50",
              "\U0001E950\U0001E958\U0001E950\U0001E950-\U0001E951\U0001E950\U0001E950\U0001E950", "08\u06600-1000"]
    for clock in clocks:
        for lines in ([f"TWY J CLSD {clock}."], ["DLY 0800-1000", f"TWY J CLSD {clock}."], [f"DLY {clock}", "TWY J CLSD."],
                      [f"TWY J CLSD BTN {clock}."]):
            assert read_lido_schedule_field(lines, august)["review"], lines
        if not clock[0].isascii():
            assert read_lido_validity(f"{clock[:2]}-AUG-26 0000 - 31-AUG-26 2359") is None, clock
    # full-width digits are folded to ASCII by NFKC and read as the clock they are
    assert read_lido_schedule_field(["DLY 0800-1000", "TWY J CLSD \uFF10\uFF18\uFF10\uFF10-\uFF11\uFF10\uFF10\uFF10."], august)["review"] is None


def test_qa514_codex_forms_are_reviews_with_and_without_item_d_and_a_separate_contact_instruction_is_not() -> None:
    august = read_lido_validity("01-AUG-26 0000 - 31-AUG-26 2359")
    for body in ["TWY J CLSD DURING THE OFFICE HOURS OF THE CAA.", "TWY J CLSD OUTSIDE THE OFFICE HOURS OF THE CAA.",
                 "TWY J CLSD IN THE BUSINESS HOURS OF THE AIRPORT AUTHORITY.", "TWY J CLSD DURING: OFFICE HOURS OF THE CAA.",
                 "TWY J CLSD. OFFICE HOURS APPLY.", "OUTSIDE OFFICE HOURS TWY J CLSD, CONTACT TWR.", "TWY J CLSD UNTIL 121.9.",
                 "TWY J CLSD 08000-10000.", "TWY J CLSD 8:3-9:3.", "TWY J CLSD 8.3-9.3.", "TWY J CLSD FOR 1.5H.",
                 "TWY J CLSD FROM EIGHT TO TEN.", "TWY J CLSD AT 1,200.", "TWY J CLSD .0800-.1000.", "TWY J CLSD #0800-#1000.",
                 "TWY J CLSD UNTIL +24 HR.", "TWY J CLSD. TERMINAL 8-10."]:
        assert read_lido_schedule_field([body], august)["review"], body
        assert read_lido_schedule_field(["DLY 1800-2000", body], august)["review"], f"DLY 1800-2000 / {body}"
    for body in ["TWY J CLSD. CONTACT CAA DURING NORMAL OFFICE HOURS.", "TWY J CLSD, CONTACT CAA DURING NORMAL OFFICE HOURS.",
                 "TWY J CLSD. FOR INFO CTC THE OFFICE HOURS OF THE CAA.", "AFTER HOURS CTC TEL +65 6789 1234. TWY J CLSD.",
                 "TWY J CLSD. FREQ 122.850 MHZ.", "TWY J CLSD. TWR FREQ CHANGED TO 118.705.",
                 "TWY J CLSD. TERMINAL 2 RAMP. YUKON 1-5. 3 BOATS. 1. TWY K. REF AIP AD 2.", "TWY J CLSD FOR 90 MIN."]:
        assert read_lido_schedule_field([body], august)["review"] is None, body
