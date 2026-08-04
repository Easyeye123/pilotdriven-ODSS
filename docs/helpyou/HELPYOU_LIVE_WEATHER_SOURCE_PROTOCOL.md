# Helpyou Live Weather Source Protocol

**Status:** Controlled prototype source policy  
**Date:** 04.08.26  
**Owner:** ODSS weather service; Helpyou consumes immutable snapshots

## 1. Approved public official sources

Live METAR, TAF, SIGMET and satellite products for CFP-grounded Helpyou scenarios are obtained from:

- NOAA/NWS Aviation Weather Center;
- Japan Meteorological Agency (JMA);
- Australian Bureau of Meteorology (BoM);
- Hong Kong Observatory (HKO).

The machine-readable registry is:

```text
integration/helpyou/fixtures/live_weather_source_registry.json
```

The deterministic policy is:

```text
integration/helpyou/helpyou_core/live_weather_policy.py
```

## 2. System boundary

ODSS owns:

- network acquisition;
- product parsing;
- issue, validity and retrieval timestamps;
- route/time intersection of SIGMET;
- projected-arrival matching of METAR and TAF;
- conflict detection;
- weather snapshot versioning.

Helpyou Chat does not fetch, decode, merge or recalculate live weather. It receives a source-labelled immutable ODSS weather snapshot and uses it to facilitate the pilot discussion.

## 3. Source precedence

1. Use the issuing aerodrome meteorological authority or Meteorological Watch Office for its own airport/FIR product.
2. Use NOAA Aviation Weather Center as the global machine-readable copy or fallback where an official local public feed is unavailable.
3. Preserve both copies when sources disagree. Do not average, silently reconcile or overwrite the issuing authority.
4. Show issue time, validity, retrieval time and source on every flight-material product.

Regional defaults registered for the prototype:

- Fukuoka FIR `RJJJ`: JMA, then NOAA AWC;
- Australian FIRs `YBBB` and `YMMM`: BoM, then NOAA AWC;
- Hong Kong FIR `VHHK`: HKO, then NOAA AWC.

## 4. Product rules

### METAR/SPECI

Preserve the raw report, observation time, station, source and retrieval time. A decoded representation may be added but cannot replace the raw report.

### TAF

Preserve the complete raw forecast and validity period. ODSS selects the forecast segment applicable to the projected arrival time and retains BECMG, TEMPO, PROB and amendment/correction status.

### SIGMET

Use the issuing MWO product as authority. ODSS checks FIR/route geometry, vertical limits and validity against the aircraft's projected position and time. A global monitor or aggregator is a cross-check, not a replacement for the issuing MWO.

### Satellite

Satellite imagery supports situational awareness, convective development and projection ahead. It cannot independently establish:

- airport operating minima;
- METAR or TAF conditions;
- SIGMET validity;
- runway suitability;
- landing performance.

The displayed image must include provider, capture time, selected area/band and retrieval time.

## 5. Provider allocation

### NOAA Aviation Weather Center

Use the public Data API for worldwide METAR, TAF and international SIGMET. Respect bounded queries, provider rate limits and user-agent requirements. The AWC GFA observation layer may provide satellite imagery.

### JMA

Use JMA as issuing authority for Japanese aerodrome products and Fukuoka FIR SIGMET. Use Himawari imagery for Asia-Pacific satellite support.

### BoM

Use BoM for Australian aerodrome products, Australian FIR SIGMET and regional satellite/weather packages. BoM's public aviation pages state that flight-planning information should be obtained through Airservices Australia; production PilotDriven must preserve this warning and continue to treat the operator's approved briefing channel as controlling.

### HKO

Use HKO as issuing authority for VHHH METAR/TAF and Hong Kong FIR SIGMET. HKO regional/global monitoring displays may be used to check availability and broaden the weather picture, but do not replace the issuing MWO.

## 6. Frozen SQ23 regression case

The SQ23 case dated 25.07.26 remains a reproducible historical fixture. Its CFP weather stays frozen in the golden test unless an archived official product snapshot is deliberately added. It must not be described as live weather.

A live execution of the same scenario would create a new ODSS source snapshot from the approved official sources, compare it with the CFP planning weather and then regenerate the scenario options.

## 7. Pilot-facing presentation

The default weather card shows only:

```text
CURRENT / PROJECTED CONDITION
Material METAR/TAF/SIGMET finding

TREND
What is improving, deteriorating or uncertain

OPERATIONAL EFFECT
Which option or safety margin is affected

SOURCE TIME
Provider | issue/capture time | validity | retrieved time
```

Satellite imagery is expandable. Helpyou avoids narrating obvious weather symbols and surfaces only the weather factor that affects the decision.

## 8. Fail-closed conditions

Helpyou/ODSS must state an evidence gap when:

- the product cannot be retrieved;
- the issue or capture time is missing;
- the TAF does not cover projected arrival;
- the SIGMET validity or geometry cannot be established;
- an official source conflict is unresolved;
- a historical product is being presented as current;
- satellite imagery is the only support for an operational weather claim.
