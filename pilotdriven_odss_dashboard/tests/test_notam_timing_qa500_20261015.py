"""QA500 (Codex's independent QA of release 500, 15 Oct 2026, output/pd-500-codex-qa-20261015).

The shared reader treated "I could not account for the schedule text" as a certain answer. A leading Item D wrapped
over two lines ("AUG 16" then "1800-2000") was discarded because its first line held no time, so the record had "no
schedule" and was published ACTIVE all day (QA500-01); a field it did accept silenced free text stating other hours
("DLY 0800-1000" / "TWY Y CLSD DAILY 1800-2000", QA500-02); and "FEB 30" was "outside the window" (QA500-04). The rules
now read the field whole, need the grammar to read all of it, check the free text against it, and check every date
against the calendar. The app runs the same property (tests/notam-timing-qa500-20261015.test.mjs) and pins the same
count and digest, so both runtimes reach the same decision on every variant.
"""
from __future__ import annotations

from collections import Counter
from datetime import timedelta
import hashlib
import json
from pathlib import Path
import re

from app.odss.enrichment import _parse_airport_notams
from app.odss.notam_timing import decide_lido_record, iso_ms, notice_timing_input, parse_ms, read_lido_schedule_field, read_lido_validity

ROOT = Path(__file__).resolve().parents[1]
VECTORS = json.loads((ROOT / "tests" / "fixtures" / "notam-timing-vectors.json").read_text(encoding="utf-8"))


def test_every_shared_item_d_field_case_reads_the_same_field_and_review() -> None:
    failures = []
    for vector in VECTORS["fieldCases"]:
        read = read_lido_schedule_field(vector["lines"], read_lido_validity(vector["validity"]))
        got = {"field": read["field"], "review": bool(read["review"])}
        if got != vector["expect"]:
            failures.append(f"{vector['id']}: {got} ({read['review']})")
    assert failures == []


def test_every_shared_decision_case_decides_the_same_through_the_shared_reader_alone() -> None:
    failures = []
    for vector in VECTORS["decisionCases"]:
        decision = decide_lido_record(vector["validity"], vector["lines"], {**vector["window"], "referenceAt": vector["referenceAt"]})
        expected = {key: value for key, value in vector["expect"].items() if key != "referenceInterval"}
        got = {"status": decision["status"], "stateAtReference": decision["stateAtReference"], "minutesDelta": decision["minutesDelta"]}
        if got != expected:
            failures.append(f"{vector['id']}: {got} {decision.get('reason') or ''}")
    assert failures == []


def test_the_held_record_carries_the_review_the_reader_found_so_the_engine_never_decides_on_the_field_alone() -> None:
    # QA500-02 through enrichment: the record keeps Item D "DLY 0800-1000" with schedule_review, and the engine's input
    # is a review - not the field's 0800-1000, which would publish TWY Y active at 0900Z.
    block = "\n".join(["Z5104/26 VALID: 01-AUG-26 0000 - 31-AUG-26 2359", "DLY 0800-1000",
                       "TWY Y CLSD DAILY 1800-2000. SYNTHETIC QA500 CONFLICTING-SCHEDULE CASE."])
    record = _parse_airport_notams("EGKK", block, None, include_all=True)[0]
    assert (record["schedule"], record["schedule_review"]) == ("DLY 0800-1000", True)
    held = notice_timing_input(record)
    assert held["schedule"] == "DLY 0800-1000"
    assert held["review"] == "The LIDO record states schedule hours in its free text that its Item D does not account for; the timing is unresolved."


# ---------------------------------------------------------------------------------------------------------------
# Property: a schedule the reader can read on one line decides the same when its text is wrapped, re-dashed,
# re-cased or restated - or it is a timing review. It is never active with no schedule, and never outside the window
# when the one-line schedule is not. Forms the rules do not accept (HH:MM, '/', a D) label, a schedule inside the free
# text, a second schedule in the free text) must be a review. Same generator, order, count and digest as the app.
# ---------------------------------------------------------------------------------------------------------------
MONTH = "01-AUG-26 0000 - 31-AUG-26 2359"
PROPERTY_CANONICALS = [
    ("DATED_EVENING", MONTH, "AUG 16 1800-2000"),
    ("DLY", MONTH, "DLY 0800-1000"),
    ("DAILY_CROSS_MIDNIGHT", MONTH, "DAILY 2130-0330"),
    ("WEEKDAY_RANGE", MONTH, "MON-FRI 0500-1500"),
    ("DAY_LIST", MONTH, "AUG 12 14 16 0200-0900"),
    ("DAY_RANGES", MONTH, "AUG 01-05 16-18 1100-2300"),
    ("CROSS_MONTH", "20-JUL-26 0000 - 30-SEP-26 2359", "JUL 20-SEP 30 0400-1600"),
    ("MONTHLESS_ENTRIES", "01-AUG-26 0000 - 28-AUG-26 0000", "16 1800-2200, 21 1400-1500"),
    ("WEEKDAY_ENTRIES", MONTH, "TUE-FRI 0600-2300, SUN 1200-2300"),
    ("BARE_RANGE", MONTH, "2130-0330"),
    ("WEEKDAYS_H24", MONTH, "FRI SUN H24"),
    ("TWO_MONTH_ENTRIES", "01-AUG-26 0000 - 30-SEP-26 2359", "AUG 16 0130-1000, SEP 14 15 0530-0930"),
    ("MULTI_PERIOD", MONTH, "WED 0530-0830 1930-2130, SUN 0530-0830"),
    ("COLON_SEPARATED", MONTH, "SAT, SUN: 0800-1000"),
]
PROPERTY_REFERENCES = ["2026-08-16T09:00:00.000Z", "2026-08-16T19:00:00.000Z", "2026-08-16T23:00:00.000Z",
                       "2026-08-17T03:00:00.000Z", "2026-08-21T14:30:00.000Z", "2026-08-12T05:00:00.000Z"]
BODY = "TWY Z9 CLSD. SYNTHETIC PROPERTY CASE."
# Refinement 2: under a readable validity wholly outside the window every variant - readable or not - is excluded by
# validity exactly as a record with no schedule is.
OUTSIDE_VALIDITIES = ["01-JAN-26 0000 - 31-JAN-26 2359", "01-OCT-26 0000 - 31-OCT-26 2359"]
# QA502: schedule-bearing qualifiers in the body - daylight, exception and holiday words, day words, dates and clocks in
# any connective form. With the field they must agree with it; with no field they are a review. (kind, text, with-field
# expectation): a day word or a date alone may restate one of the field's own day parts.
BODY_QUALIFIERS = [
    ("sr-ss", "DAILY SR-SS", "review"), ("hj", "HJ", "review"), ("hn", "DLY HN", "review"), ("sunrise-sunset", "SUNRISE TO SUNSET", "review"),
    ("daylight", "DRG DAYLIGHT", "review"), ("night", "AT NIGHT", "review"), ("exc-weekday", "EXC SUN", "review"),
    ("exc-date", "EXCEPT AUG 16", "review"), ("exc-hol", "EXC HOL", "review"), ("holidays", "ON PUBLIC HOLIDAYS", "review"),
    ("from-until", "FROM 0001 UNTIL 0002", "review"), ("fm-til", "FM 0001 TIL 0002", "review"), ("btn-and", "BTN 0001 AND 0002", "review"),
    ("between-and", "BETWEEN 0001 AND 0002", "review"), ("before", "BEFORE 0002", "review"), ("after", "AFTER 2358", "review"),
    ("slash", "0001/0002", "review"), ("colon", "00:01-00:02", "review"), ("weekday", "WED", "equal_or_review"),
    ("month-day", "AUG 17", "equal_or_review"), ("dated-narrower", "FROM 20 AUG 2026 TO 21 AUG 2026", "review"),
]
# QA502: validities that cross leap days, bounded and open-ended, with references on and around 29 FEB 2028.
LONG_VALIDITIES = ["01-JAN-26 0000 - 31-DEC-28 2359", "01-JAN-26 0000 - UFN"]
LONG_REFERENCES = ["2027-08-16T09:00:00.000Z", "2028-02-29T09:00:00.000Z", "2028-02-28T23:30:00.000Z"]
LEAP_REFERENCE = "2028-02-29T00:01:30.000Z"
DASH_VARIANTS = ["‐", "‑", "‒", "–", "—", "―", "−"]
# The count and digest the app pins too (same generator, same order).
# QA506 moved the digest: a restated hours-only or days-only body is now a review unless it equals Item D on its own,
# and all seven weekdays are daily.
PROPERTY_COUNT = 32908
PROPERTY_DIGEST = "c00f8a4ad26f9be8ccb1223c4537313c2960f0ebdfb1db4f6925fb0d1be60e2d"


def _cuts(text: str) -> list[dict]:
    """Line-break positions: every space (consumed), and before and after every '-'."""
    cuts = []
    for index, char in enumerate(text):
        if char == " ":
            cuts.append({"start": index, "end": index + 1, "kind": "space"})
        if char == "-":
            cuts.append({"start": index, "end": index, "kind": "before"})
            cuts.append({"start": index + 1, "end": index + 1, "kind": "after"})
    return cuts


def _apply(text: str, cuts: list[dict]) -> list[str] | None:
    lines, at = [], 0
    for cut in cuts:
        lines.append(text[at:cut["start"]])
        at = cut["end"]
    lines.append(text[at:])
    return None if any(not line.strip() for line in lines) else lines


def _shift_hours(text: str) -> str:
    return re.sub(r"\b(\d{2})(\d{2})\b", lambda m: f"{(int(m.group(1)) + 5) % 24:02d}{m.group(2)}", text)


def property_variants(schedule: str) -> list[tuple[str, str, list[str]]]:
    """(kind, expectation, lines) for one canonical one-line schedule; expectation is exact | review | equal_or_review."""
    variants: list[tuple[str, str, list[str]]] = []

    def add(kind: str, expectation: str, lines: list[str] | None) -> None:
        if lines:
            variants.append((kind, expectation, lines))

    cuts = _cuts(schedule)

    def exact_cut(items: list[dict]) -> bool:
        return all(cut["kind"] != "before" for cut in items)

    for cut in cuts:
        lines = _apply(schedule, [cut])
        add(f"split:{cut['kind']}@{cut['start']}", "exact" if exact_cut([cut]) else "equal_or_review", lines and [*lines, BODY])
        if lines and exact_cut([cut]):
            add(f"split+en-dash@{cut['start']}", "exact", [*(line.replace("-", "–") for line in lines), BODY])
        if lines:
            add(f"split-into-free-text@{cut['kind']}{cut['start']}", "equal_or_review", [lines[0], f"{lines[1]} {BODY}"])
    for i in range(len(cuts)):
        for j in range(i + 1, len(cuts)):
            if cuts[i]["end"] > cuts[j]["start"] or cuts[i]["start"] == cuts[j]["start"]:
                continue
            pair = [cuts[i], cuts[j]]
            lines = _apply(schedule, pair)
            add(f"split2:{cuts[i]['kind']}@{cuts[i]['start']}+{cuts[j]['kind']}@{cuts[j]['start']}",
                "exact" if exact_cut(pair) else "equal_or_review", lines and [*lines, BODY])
    for dash in DASH_VARIANTS:
        if "-" in schedule:
            add(f"dash:U+{ord(dash):x}", "exact", [schedule.replace("-", dash), BODY])
    if "-" in schedule:
        add("spaced-hyphen", "exact", [schedule.replace("-", " - "), BODY])
    add("lower-case", "exact", [schedule.lower(), BODY])
    add("trailing-stop", "exact", [f"{schedule}.", BODY])
    utc = re.sub(r"\b(\d{4})\b", r"\1UTC", schedule)
    if utc != schedule:
        add("utc-suffix", "exact", [utc, BODY])
    zulu = re.sub(r"\b(\d{4})\b", r"\1Z", schedule)
    if zulu != schedule:
        add("z-suffix", "exact", [zulu, BODY])
    add("restated-in-free-text", "exact", [schedule, f"TWY Z9 CLSD {schedule}."])
    colon = re.sub(r"\b(\d{2})(\d{2})\b", r"\1:\2", schedule)
    if colon != schedule:
        add("colon-clock", "review", [colon, BODY])
    slash = re.sub(r"\b(\d{4})-(\d{4})\b", r"\1/\2", schedule)
    if slash != schedule:
        add("slash-range", "review", [slash, BODY])
    # Refinement 1: a zero-length range (start = end) is a review, never 24 hours.
    zero = re.sub(r"\b(\d{4})-(\d{4})\b", r"\1-\1", schedule)
    if zero != schedule:
        add("zero-length-range", "review", [zero, BODY])
    add("d-label-prefix", "review", [f"D) {schedule}", BODY])
    add("d-label-line", "review", ["D)", schedule, BODY])
    add("inside-free-text", "review", [f"{schedule} {BODY}"])
    add("free-text-other-hours", "review", [schedule, "TWY Z9 CLSD DAILY 0001-0002."])
    shifted = _shift_hours(schedule)
    if shifted != schedule:
        add("free-text-shifted-hours", "review", [schedule, f"TWY Z9 CLSD {shifted}."])
    for kind, text, with_field in BODY_QUALIFIERS:
        add(f"body-{kind}", with_field, [schedule, f"TWY Z9 CLSD {text}."])
        add(f"body-only-{kind}", "review", [f"TWY Z9 CLSD {text}."])
    first = re.search(r"\b(\d{4})-(\d{4})\b", schedule)
    if first:
        add("restated-from-until", "equal_or_review", [schedule, f"TWY Z9 CLSD FROM {first.group(1)} UNTIL {first.group(2)}."])
        add("restated-btn-and", "equal_or_review", [schedule, f"TWY Z9 CLSD BTN {first.group(1)} AND {first.group(2)}."])
    return variants


def _window(reference_at: str) -> dict:
    reference = parse_ms(reference_at)
    return {"startsAt": iso_ms(reference - 120 * 60 * 1000), "endsAt": iso_ms(reference + 120 * 60 * 1000), "referenceAt": reference_at}


def _verdict(decision: dict) -> str:
    interval = decision["referenceInterval"]
    return "|".join([decision["status"], decision["stateAtReference"], "-" if decision["minutesDelta"] is None else str(decision["minutesDelta"]),
                     f"{interval['startsAt']}/{interval['endsAt'] or '-'}" if interval else "-"])


def test_property_wrapped_redashed_recased_and_restated_item_d_decides_as_its_one_line_form_or_is_a_review() -> None:
    """Also: a zero-length range is a review, and under a validity outside the window every variant is excluded."""
    failures: list[str] = []
    counts: Counter = Counter()
    digest = hashlib.sha256()
    canonical_states: set[str] = set()
    total = 0
    for case_id, validity, schedule in PROPERTY_CANONICALS:
        variants = property_variants(schedule)
        for reference_at in PROPERTY_REFERENCES:
            window = _window(reference_at)
            canonical = decide_lido_record(validity, [schedule, BODY], window)
            if canonical["status"] == "review":
                failures.append(f"{case_id} @{reference_at}: the canonical form is a review ({canonical.get('reason')})")
            canonical_states.add(f"{canonical['status']}:{canonical['stateAtReference']}")
            for kind, expectation, lines in variants:
                decision = decide_lido_record(validity, lines, window)
                total += 1
                counts[expectation] += 1
                digest.update(f"{case_id}|{reference_at}|{kind}|{chr(10).join(lines)}|{_verdict(decision)}\n".encode("utf-8"))
                where = f"{case_id} @{reference_at} {kind} {lines}: {_verdict(decision)} vs {_verdict(canonical)} {decision.get('reason') or ''}"
                same = _verdict(decision) == _verdict(canonical)
                if decision["status"] == "affecting" and not decision["schedule"]:
                    failures.append(f"ACTIVE WITHOUT SCHEDULE {where}")
                if decision["status"] == "outside_window" and canonical["status"] != "outside_window":
                    failures.append(f"OUTSIDE INSTEAD {where}")
                if expectation == "exact" and not same:
                    failures.append(f"NOT EXACT {where}")
                if expectation == "review" and decision["status"] != "review":
                    failures.append(f"NOT REVIEW {where}")
                if expectation == "equal_or_review" and not same and decision["status"] != "review":
                    failures.append(f"NEITHER {where}")
            for outside in OUTSIDE_VALIDITIES:
                excluded = decide_lido_record(outside, [BODY], window)
                if excluded["status"] != "outside_window":
                    failures.append(f"{case_id} @{reference_at} {outside}: the validity alone is not outside the window")
                for kind, _, lines in [("canonical", "exact", [schedule, BODY]), *variants]:
                    decision = decide_lido_record(outside, lines, window)
                    total += 1
                    counts["outside_validity"] += 1
                    digest.update(f"{case_id}|{reference_at}|{outside}|{kind}|{chr(10).join(lines)}|{_verdict(decision)}\n".encode("utf-8"))
                    if _verdict(decision) != _verdict(excluded):
                        failures.append(f"NOT EXCLUDED BY VALIDITY {case_id} @{reference_at} {outside} {kind} {lines}: "
                                        f"{_verdict(decision)} vs {_verdict(excluded)}")
        # QA502: the same invariants under validities that cross leap days (no sampling horizon).
        for long_validity in LONG_VALIDITIES:
            for reference_at in LONG_REFERENCES:
                window = _window(reference_at)
                canonical = decide_lido_record(long_validity, [schedule, BODY], window)
                for kind, expectation, lines in variants:
                    decision = decide_lido_record(long_validity, lines, window)
                    total += 1
                    counts["long_validity"] += 1
                    digest.update(f"{case_id}|{long_validity}|{reference_at}|{kind}|{chr(10).join(lines)}|{_verdict(decision)}\n".encode("utf-8"))
                    where = f"{case_id} {long_validity} @{reference_at} {kind} {lines}: {_verdict(decision)} vs {_verdict(canonical)} {decision.get('reason') or ''}"
                    same = _verdict(decision) == _verdict(canonical)
                    if decision["status"] == "affecting" and not decision["schedule"]:
                        failures.append(f"ACTIVE WITHOUT SCHEDULE {where}")
                    if decision["status"] == "outside_window" and canonical["status"] != "outside_window":
                        failures.append(f"OUTSIDE INSTEAD {where}")
                    if expectation == "exact" and not same:
                        failures.append(f"NOT EXACT {where}")
                    if expectation == "review" and decision["status"] != "review":
                        failures.append(f"NOT REVIEW {where}")
                    if expectation == "equal_or_review" and not same and decision["status"] != "review":
                        failures.append(f"NEITHER {where}")
            # The body adds 29 FEB 2028 0001-0002. Accepted only if the field already holds that minute; else a review.
            window = _window(LEAP_REFERENCE)
            canonical = decide_lido_record(long_validity, [schedule, BODY], window)
            lines = [schedule, f"TWY Z9 CLSD {schedule}, FEB 29 0001-0002."]
            decision = decide_lido_record(long_validity, lines, window)
            total += 1
            counts["leap_day"] += 1
            digest.update(f"{case_id}|{long_validity}|leap|{chr(10).join(lines)}|{_verdict(decision)}\n".encode("utf-8"))
            if decision["status"] != "review" and not (_verdict(decision) == _verdict(canonical)
                                                       and canonical["stateAtReference"] == "active_at_reference"):
                failures.append(f"LEAP DAY NOT ACCOUNTED {case_id} {long_validity} {lines}: {_verdict(decision)} vs {_verdict(canonical)}")
    assert failures[:40] == [], f"{len(failures)} property failures"
    for state in ["affecting:active_at_reference", "affecting:begins_after_reference", "affecting:ended_before_reference",
                  "outside_window:begins_after_reference"]:
        assert state in canonical_states, f"no canonical decision is {state}: {canonical_states}"
    print(f"property: {total} variant decisions {dict(counts)} digest {digest.copy().hexdigest()}")
    assert total == PROPERTY_COUNT
    assert digest.hexdigest() == PROPERTY_DIGEST, "the app pins the same digest: both runtimes decide every variant the same"


def test_a_zero_length_runway_regime_is_not_read_as_a_24_hour_closure() -> None:
    # Refinement 1 in the dated runway-regime reader (SYNTHETIC text in the genuine SX120/25 form): "BTN 1700UTC TO
    # 1700UTC" states no period; it yields no runway state, as an invalid clock does, while the 1700-2200 control does.
    from datetime import datetime, timezone
    from app.odss.runway_closure_schedule import assess_runway_closure_schedule
    reference = datetime(2026, 8, 16, 19, 0, tzinfo=timezone.utc)  # a Sunday
    text = "RWY 02L/20R WILL BE CLSD BTN 1700UTC TO {end} EV SUN AND WED FM 01AUG26 TO 31AUG26 FOR MAINT. SYNTHETIC."
    control = assess_runway_closure_schedule(text.format(end="2200UTC"), role="destination", reference_time=reference)
    zero = assess_runway_closure_schedule(text.format(end="1700UTC"), role="destination", reference_time=reference)
    assert control and [statement["stateAtReference"] for statement in control["statements"]] == ["active_at_reference"]
    assert zero is None or not zero.get("statements")
