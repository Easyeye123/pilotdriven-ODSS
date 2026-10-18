"""QA510 (Codex's QA of release 510, 16 Oct 2026): the QA510 adversarial corpus, in this runtime.

The fail-closed detector still found temporal content by VALIDITY ("TWY J CLSD 2500-2600", "080O-100O", "08.00/10.00",
"FROM 18H TO 20H" matched no temporal class and read as no schedule) and the notice-duration mask hid durations attached
to the restriction ("FOR MAX 2 HOURS", "DURING THE LAST 2 HOURS", "FOR A PERIOD OF 2 HOURS"). Temporal content is now
found by SHAPE (notam_timing_rules.json scheduleField); a duration is benign only in an explicit notice, permission or
restoration context; every benign class is bound to a stated non-temporal context and may never hold, cut or abut a
clock-like range.

The corpus (tests/fixtures/notam-timing-adversarial-qa510.json.gz, LABELLED SYNTHETIC) states every phrase's relation
to Item D by construction. The app runs the same corpus (tests/notam-timing-adversarial-qa510-20261016.test.mjs) and
pins the same fixture, counts and digest: both runtimes reach the same decision on every case.
"""
from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path

from app.odss.notam_timing import decide_notice_timing, read_lido_schedule_field, read_lido_validity

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "notam-timing-adversarial-qa510.json.gz"
FIXTURE_SHA256 = "7957639640c676b9b9c2337a1858d49fb14d9c7b65b8a0d9eff410bf562c796f"
DECISIONS = 339696
# QA514 (17 Oct 2026) moved the conservative count and the digest, never a failure: bare single-digit ranges ('1-3',
# '6 TO 9') are unaccounted digits; 'BETWEEN 15 AND 30 MINUTES BEFORE ETA' is the object of BETWEEN; 'AFTER NORMAL
# BUSINESS HOURS, FOR EMERGENCY REQUESTS' right after the restriction and 'CONSIDERATION TO THE OFFICE HOURS ...' (no
# contact verb) are reviews.
# QA518 (17 Oct 2026) moved the conservative count and the digest, never a failure: punctuation no longer licenses a
# benign mask - '(24 HR PPR)', '(48HR PN)', '(1HR PPR)', '(72 HOURS PRIOR NOTICE)' and '(DAY AND NIGHT MARKINGS
# PROVIDED)' right after the restriction verb read as without their brackets: reviews.
# QA520 (18 Oct 2026) moved the conservative count and the digest, never a failure: every connective's operand is
# accounted for whole (I7/I8) - a point named only by a bare code ('EXPECT TO REACH 3000' AT GUTOR') is classified by
# no role; see output/pd-qa520-timing-20261018/work/moves-qa510.txt.
CONSERVATIVE_REVIEWS = 540
DECISION_DIGEST = "72fdede6e07ee7dfd290cec70bd3a5b97121bdbcf1434cfeca13d3bfe71a9b9c"
KEYS = ("status", "stateAtReference", "minutesDelta", "outsideBy")


def _place(subject: str, position: str, text: str) -> list[str]:
    words = text.split(" ")
    mid = max(1, len(words) // 2)
    return {
        "after": [f"{subject} {text}."],
        "before": [f"{text} {subject}."],
        "ownline": [f"{subject}.", f"{text}."],
        "wrapped": [f"{subject} " + " ".join(words[:mid]), " ".join(words[mid:]) + "."],
        "bracket": [f"{subject} ({text})."],
        "comma": [f"{subject}, {text}."],
    }[position]


def test_adversarial_qa510_every_clock_like_shape_duration_and_benign_look_alike_is_the_canonical_decision_or_a_review() -> None:
    raw = FIXTURE.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == FIXTURE_SHA256, "the app evaluates the same corpus bytes"
    fixture = json.loads(gzip.decompress(raw).decode("utf-8"))
    digest = hashlib.sha256()
    failures: list[str] = []
    decisions = conservative = 0
    canonical: dict[str, dict] = {}
    for d, v, family, relation, text in fixture["phrases"]:
        validity = read_lido_validity(fixture["validities"][v])
        key = f"{d}|{v}"
        if key not in canonical:
            canonical[key] = read_lido_schedule_field([*fixture["itemD"][d], f"{fixture['subject']}."], validity)
        canon = canonical[key]
        for position in fixture["positions"]:
            lines = [*fixture["itemD"][d], *_place(fixture["subject"], position, text)]
            read = read_lido_schedule_field(lines, validity)
            for reference, window in fixture["windows"].items():
                decisions += 1
                got = decide_notice_timing({"validity": validity, "schedule": read["field"], "review": read["review"]}, window)
                expected = decide_notice_timing({"validity": validity, "schedule": canon["field"], "review": canon["review"]}, window)
                digest.update((json.dumps([got[k] for k in KEYS], separators=(",", ":")) + "\n").encode("utf-8"))
                if expected["status"] == "outside_window" and expected["outsideBy"] == "validity":
                    ok = got["status"] == "outside_window" and got["outsideBy"] == "validity"
                elif relation in ("differs", "unreadable"):
                    ok = got["status"] == "review"
                else:
                    same = all(got[k] == expected[k] for k in KEYS)
                    ok = same or got["status"] == "review"
                    if ok and not same:
                        conservative += 1
                if not ok and len(failures) < 25:
                    failures.append(f"{d} {v} {reference} {family}/{relation} {position} {lines}: {got['status']}")
    print(f"adversarial QA510: {decisions} decisions, {conservative} conservative reviews, digest {digest.hexdigest()}")
    assert failures == []
    assert decisions == DECISIONS
    assert conservative == CONSERVATIVE_REVIEWS, "equal phrasings read as a review are counted and pinned"
    assert digest.hexdigest() == DECISION_DIGEST, "the app pins the same digest: both runtimes decide every case the same"
