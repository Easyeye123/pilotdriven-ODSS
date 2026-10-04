"""Page-1 weather fields - the boss's reference form of a held METAR / TAF.

His reference page 1 (SQ910_21AUG2026_Flight_Briefing.pdf) prints

    METAR  11004KT 9999 FEW018
    TAF    16008KT 9999 FEW015/SCT020

for records the OFP holds as ``SA 201900 11004KT 9999 FEW018 BKN300 28/23
Q1011 NOSIG=`` and ``FT 201700 2018/2200 16008KT 9999 FEW015 SCT020=``. The
rule below is what turns the one into the other, stated once so both surfaces
print the same thing:

1. The publication envelope is removed from the front of the record - the
   report word (METAR/SPECI/TAF), AMD/COR/AUTO, the LIDO record type
   (SA/SP/FT/FC), the station ICAO when the ICAO form carries one, the
   DDHHMM(Z) time and the DDHH/DDHH validity - and the ``=`` terminator from
   the end. None of these is a weather group.
2. EVERY group that follows is printed verbatim, in source order. Consecutive
   cloud layers are joined with ``/``, the way his TAF field joins
   FEW015/SCT020; nothing else is altered and nothing is dropped.
3. Nothing is cut, so nothing is pointed elsewhere.

RULE CHANGE, 21-22 Sep 2026 (v1 -> v2). v1 stopped at the first token that was
not base-period weather: a METAR lost its temperature/dew point, QNH and trend,
and a departure TAF lost every change group behind
"· change groups: WEATHER page". David, 21 Sep 21:22 with the KUL card
photographed: the METAR is shortened too much; 22 Sep 13:38: "TAF Tempo is
truncated why????". His current instruction outranks the 21 Aug reference form
those stops were minted from, so the stops are gone. What the envelope rule
removes is unchanged - none of it is weather.
4. A record the source itself declares empty (NIL, WX NOT AVAILABLE) is
   printed as the source states it. Nothing held prints "Not held".

The same rule is implemented token for token in the dashboard
(``web/src/lib/page1-weather.mjs``); ``tests/fixtures/page1-weather-vectors.json``
pins the two to each other on every record of the real corpora.
"""
from __future__ import annotations

import re
from typing import Any

PAGE1_WEATHER_RULE = "page1-weather-groups-v2"
NOT_HELD = "Not held"

_REPORT_WORD = re.compile(r"^(?:METAR|SPECI|TAF)$")
_ENVELOPE_WORD = re.compile(r"^(?:AMD|COR|RTD|AUTO)$")
_LIDO_RECORD_TYPE = re.compile(r"^(?:SA|SP|FT|FC|FX)$")
_STATION = re.compile(r"^[A-Z]{4}$")
_RECORD_TIME = re.compile(r"^\d{6}Z?$")
_VALIDITY = re.compile(r"^\d{4}/\d{4}$")

_CLOUD = re.compile(
    r"^(?:(?:FEW|SCT|BKN|OVC)(?:\d{3}|/{3})(?:CB|TCU|/{3})?"
    r"|VV(?:\d{3}|/{3})|NSC|NCD|SKC|CLR|/{6}|/{3}\d{3})$"
)


def held_text(value: Any) -> str:
    """Held text, whitespace-normalised, terminator removed; accepts ``{text}``."""
    raw = value.get("text") if isinstance(value, dict) else value
    if raw is None or isinstance(raw, bool):
        return ""
    joined = " ".join(str(raw).split())
    return re.sub(r"\s*=+\s*$", "", joined).strip()


def _strip_envelope(tokens: list[str]) -> tuple[list[str], list[str]]:
    envelope: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        previous = envelope[-1] if envelope else ""
        following = tokens[index + 1] if index + 1 < len(tokens) else ""
        is_station = bool(_STATION.match(token)) and (
            bool(_REPORT_WORD.match(previous))
            or bool(_ENVELOPE_WORD.match(previous))
            or bool(_RECORD_TIME.match(following))
        )
        if (
            _REPORT_WORD.match(token)
            or _ENVELOPE_WORD.match(token)
            or _LIDO_RECORD_TYPE.match(token)
            or _RECORD_TIME.match(token)
            or _VALIDITY.match(token)
            or is_station
        ):
            envelope.append(token)
            index += 1
            continue
        break
    return envelope, tokens[index:]


def page_one_weather_groups(record: Any, kind: str) -> dict[str, Any]:
    """``{held, groups, more, envelope, tail}`` for one held record.

    ``kind`` is ``"metar"`` or ``"taf"``.
    """
    text = held_text(record)
    if not text:
        return {"held": False, "groups": "", "more": False, "envelope": [], "tail": []}
    envelope, body = _strip_envelope(text.split(" "))
    if not body:
        return {"held": True, "groups": " ".join(envelope), "more": False,
                "envelope": envelope, "tail": []}

    kept: list[list[Any]] = []  # [text, is_cloud]
    for token in body:
        cloud = bool(_CLOUD.match(token))
        if cloud and kept and kept[-1][1]:
            kept[-1][0] += "/" + token
        else:
            kept.append([token, cloud])
    # ``more`` stays in the shape for callers and vectors; nothing is cut any
    # more, so it is always False and no pointer is ever printed.
    return {
        "held": True,
        "groups": " ".join(item[0] for item in kept),
        "more": False,
        "envelope": envelope,
        "tail": [],
    }


# RULE CHANGE, 23 Sep 2026 (v2 -> v3, the FIELDS only). David, 23 Sep 20:22,
# photographing the SIA312 WSSS / EGKK cards: "You need to give the full METAR
# / TAF for WSSS and EGKK." The page-1 field is now the record exactly as the
# OFP holds it - the envelope (SA/FT, issue time, validity), every group and
# the terminator - whitespace-normalised and nothing else. The groups rule
# above is unchanged and still pinned by the vectors; it is no longer what the
# station fields print. The dashboard's page1-weather.mjs carries the same rule.
PAGE1_WEATHER_FIELD_RULE = "page1-weather-record-v3"


def page_one_weather_record(record: Any) -> str:
    """The held record verbatim, whitespace-normalised; '' when nothing is held."""
    raw = record.get("text") if isinstance(record, dict) else record
    if raw is None or isinstance(raw, bool):
        return ""
    return " ".join(str(raw).split())


def page_one_metar_field(record: Any, pointer: str | None = None) -> str:
    """The page-1 METAR field: the full original coded record.

    ``pointer`` is kept, unused, so existing call sites stay valid.
    """
    return page_one_weather_record(record) or NOT_HELD


def page_one_taf_field(record: Any, pointer: str | None = None) -> str:
    """The page-1 TAF field: the full original coded record, every change group."""
    return page_one_weather_record(record) or NOT_HELD


# A TAF change group starts at one of these markers and runs to the next one.
_TAF_GROUP_MARKER = re.compile(
    r"\b(?:PROB(?:30|40)(?:\s+TEMPO)?\s+\d{4}/\d{4}|TEMPO\s+\d{4}/\d{4}|BECMG\s+\d{4}/\d{4}"
    r"|INTER\s+\d{4}/\d{4}|FM\d{6})\b"
)
# Page 1 is a physical page. When the whole TAF cannot be fitted on it at any
# column width or readable type size (SQ24 SIN-JFK: a 326-character KJFK TAF
# beside its PERTINENT lines), the column prints the record's largest whole-
# group prefix and says so with this marker; the WEATHER page prints the whole
# record. Never a silent cut, never a cut inside a group, and only after every
# full-record layout has been tried (operational_format.plan_page_flexible).
TAF_CONTINUATION = "(cont. WEATHER page)"


def page_one_taf_change_groups(record: Any) -> tuple[str, list[str]]:
    """``(base, change groups)`` of the verbatim record; the base keeps the envelope."""
    text = page_one_weather_record(record)
    starts = [match.start() for match in _TAF_GROUP_MARKER.finditer(text)]
    if not starts:
        return text, []
    base = text[: starts[0]].strip()
    bounds = list(zip(starts, starts[1:] + [len(text)]))
    return base, [text[start:end].strip() for start, end in bounds]


def page_one_taf_field_continued(record: Any, drop_groups: int) -> str:
    """The page-1 TAF field with its last ``drop_groups`` change groups deferred
    to the WEATHER page behind ``TAF_CONTINUATION``; the full field when
    nothing is dropped or the record has no change group to drop."""
    base, groups = page_one_taf_change_groups(record)
    if not base and not groups:
        return NOT_HELD
    drop = max(0, min(int(drop_groups), len(groups)))
    if drop == 0:
        return page_one_taf_field(record)
    kept = groups[: len(groups) - drop]
    return f"{' '.join([base, *kept]).strip()} {TAF_CONTINUATION}"


def forecast_source_line(source: dict[str, Any]) -> str:
    """One WEATHER-page line naming the assessment's published source.

    A forecast source prints its issue and validity times; an observation
    basis (a METAR source) prints its observation time and never an invented
    validity; a source without times says so. The dashboard's
    ``forecastProvenanceLine`` is the same statement for the same shapes.
    """
    from .operational_format import utc_label

    label = str(
        source.get("display_title")
        or ("Uploaded OFP" if source.get("source_type") == "uploaded_cfp" else "")
        or source.get("provider")
        or "Source not held"
    )
    if source.get("issued_at_utc") or source.get("valid_from_utc") or source.get("valid_to_utc"):
        return (
            f"{label}; issued {utc_label(source.get('issued_at_utc'))}; "
            f"valid {utc_label(source.get('valid_from_utc'))}-{utc_label(source.get('valid_to_utc'))}."
        )
    if source.get("observed_at_utc"):
        kind = str(source.get("record_type") or "METAR").upper()
        return f"Basis: {kind} observation {utc_label(source.get('observed_at_utc'))}; {label}."
    return f"{label}; issue and validity times not held."


__all__ = [
    "NOT_HELD",
    "PAGE1_WEATHER_FIELD_RULE",
    "PAGE1_WEATHER_RULE",
    "TAF_CONTINUATION",
    "forecast_source_line",
    "held_text",
    "page_one_metar_field",
    "page_one_taf_change_groups",
    "page_one_taf_field",
    "page_one_taf_field_continued",
    "page_one_weather_groups",
    "page_one_weather_record",
]
