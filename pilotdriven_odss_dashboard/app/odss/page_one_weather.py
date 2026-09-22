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


def page_one_metar_field(record: Any, pointer: str) -> str:
    """The page-1 METAR field; ``pointer`` names the page holding the full record."""
    result = page_one_weather_groups(record, "metar")
    if not result["held"]:
        return NOT_HELD
    return f"{result['groups']} · trend: {pointer}" if result["more"] else result["groups"]


def page_one_taf_field(record: Any, pointer: str) -> str:
    """The page-1 departure TAF field: the base period, change groups pointed at."""
    result = page_one_weather_groups(record, "taf")
    if not result["held"]:
        return NOT_HELD
    return f"{result['groups']} · change groups: {pointer}" if result["more"] else result["groups"]


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
    "PAGE1_WEATHER_RULE",
    "forecast_source_line",
    "held_text",
    "page_one_metar_field",
    "page_one_taf_field",
    "page_one_weather_groups",
]
