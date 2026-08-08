# Flight Briefing Publication Memory — 8 August 2026

This file records accepted standing decisions for future PilotDriven Flight Briefing development. It contains no user CFP, generated operational report, proprietary manual page or controlled source index.

## Product naming

- New product-facing text uses **Flight Briefing**.
- The historical repository name may retain `ODSS` for traceability.
- The governing doctrine is: **Flight Briefing computes and never guesses. Helpyou retrieves and never invents. PilotDriven presents — and the pilot always decides.**

## Primary report

- Publish one combined Flight Briefing PDF.
- Filename: `<FLIGHT>_<DDMMMYYYY>_Flight_Briefing.pdf`.
- Do not expose `Level 1`, `Level 2`, `Pertinent Brief`, `Pertinent Briefing`, `Evidence Level` or `Evidence Brief` in the current-facing PDF.
- Do not append or embed the complete CFP unless explicitly requested.
- Present a concise flight overview first, followed by supporting evidence and selected authoritative source crops.
- Apply one-fact-one-primary-location deduplication.

## Page 1 layout

- Operationally pertinent information is on the left.
- The whole-flight route map is on the right.
- Departure, Destination and preferred Alternate cards have equal dimensions, padding and text alignment.
- Preferred alternate weather is analysed on Page 1.
- Page 1 covers critical CFP planning data, masses, fuel, excess allocation and deferred items.

## Typography and visual release

- Detailed content and operational numerics are at least 20 percent larger than the v1.2 minimum.
- Normal detail and numeric minimum: 8.4 pt.
- Complete wrapped text blocks are vertically middle-aligned.
- Any text overlap, clipping, duplicate layer or source-image collision blocks publication.
- The SQ365 QA draft exposed overlapping secondary weather lines in two Page 1 airport cards; this is now a regression failure condition.

## Logo and navigation

- Use the approved forward-flight PilotDriven mark.
- Do not use an X-shaped mark as the PilotDriven logo.
- Each applicable decision gate links to the exact supporting evidence destination.
- Use `MEL/CDL`, not `TECH`.

## Source crops

- MEL/CDL/CDDL, EDTO and depressurisation evidence use tightly cropped relevant source sections when applicable.
- Crops retain source document, revision/effective date, reference, page, crop box and destination link.
- A matched depressurisation profile requires a flight-specific analysis and the cropped authoritative chart.
- Unmatched High Terrain Exposure remains unresolved; do not substitute a nearby chart.

## Hazard assessment

- Review SIGMET, tropical cyclone, volcanic ash, frontal weather and CAT coverage for every CFP.
- Preserve exact product, issuer, validity, phenomenon, intensity, position, vertical extent, movement, trend and route/time/level relationship.
- Promote only when authoritative, temporal, spatial, vertical and consequence gates are satisfied.
- Missing coverage is a `COVERAGE_GAP`, never NIL.
- Write for a trained professional pilot; no lay explanation or exaggerated hazard wording.

## Release principle

A correct calculation presented with unreadable typography, broken links, missing source crops, duplicated facts or overlapping objects is not a valid Flight Briefing release.
