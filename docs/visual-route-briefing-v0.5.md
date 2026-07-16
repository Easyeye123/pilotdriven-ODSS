# PilotDriven ODSS Visual Route Briefing v0.5

## Purpose

This specification defines the integration-ready visual briefing layer that sits above the deterministic ODSS analysis engines. It is designed for the current personal FastAPI dashboard and for later incorporation into the wider PilotDriven product without rewriting the operational logic.

The visual layer consumes the canonical ODSS analysis JSON. It does not parse the Lido PDF itself and it does not make new operational decisions.

## Product boundary

The same `briefing` view model drives:

1. the completed-flight web dashboard;
2. Page 1 of the Level 1 pertinent brief;
3. the visual cover of the Level 2 expanded brief; and
4. future PilotDriven React/Next.js components.

The current implementation uses an offline schematic route-map adapter. A future PilotDriven deployment may replace only the map renderer with MapLibre, Mapbox, an approved aeronautical base map, or another provider while preserving the view model and report contracts.

## Canonical data flow

```text
Lido CFP PDF
  -> parser
  -> canonical flight JSON
  -> deterministic findings
  -> briefing view model
  -> web dashboard / Level 1 PDF / Level 2 PDF
```

## Level 1 report standard

Level 1 becomes a fixed three-page A4 landscape briefing.

### Page 1 - Visual route briefing

The first page follows a dashboard composition:

- application/flight header;
- flight summary strip;
- departure airport panel;
- central route map plotted from CFP waypoint coordinates;
- destination airport panel;
- enroute exceptions strip;
- FIR/communication timeline panel;
- EDTO panel;
- enroute weather panel; and
- clickable navigation to Page 2 and Page 3.

The page remains a decision-support summary. It deliberately avoids reproducing the original Lido CFP.

### Page 2 - Operational detail

Page 2 contains:

- PZFW, PLDW and PTOW in integer kg;
- fuel and take-off performance summary;
- all Page 1 MEL and CDL/CDDL items;
- departure airport weather and pertinent NOTAM;
- destination airport weather and pertinent NOTAM;
- destination alternate information; and
- pilot-entered departure/destination notes when selected.

Page 1 airport buttons link to the corresponding Page 2 destinations.

### Page 3 - Route and contingency

Page 3 contains:

- early ATC/FIR calls;
- ACTM and calculated UTC timeline when an ATOT/waypoint ATA reference exists;
- EDTO entry, ETP, exit and airport suitability summary;
- continuous MSA greater than 100* events;
- continuous VWS greater than 4 events;
- route-matched depressurisation profiles;
- BOBCAT/Kabul controls when applicable; and
- pilot-entered communications/enroute notes when selected.

Page 1 communication, EDTO and route links target Page 3.

## Level 2 report standard

Level 2 uses the same visual Page 1 and then continues with the complete expanded ODSS sections. The existing deterministic details and parser warnings remain available. The visual cover must never hide an unresolved or unknown finding.

## Dashboard screen structure

The completed-flight workspace contains a dark visual briefing shell before the existing edit and audit tools.

### Header

- PilotDriven ODSS mark;
- flight number;
- route and flight date;
- briefing status;
- generated timestamp;
- NOTAM count;
- weather record count; and
- report/download controls.

### Main briefing region

- left rail: Briefing, Route, Airports, FIR/Comm, NOTAMs, EDTO, Documents and Settings anchors;
- departure airport card;
- central route map;
- destination airport card;
- exception cards; and
- lower communication, EDTO and weather cards.

### Existing tools retained below

- analysis/rerun controls;
- actual-time operational clock;
- personal notes;
- organised findings;
- parser warnings; and
- manual report override.

## Route map contract

Every parsed route point may contain:

```json
{
  "name": "DUDEG",
  "actm_minutes": 354,
  "latitude": 32.775,
  "longitude": 67.45,
  "fir_boundary": null,
  "airway_in": "L750",
  "msa_hundreds_ft": 166,
  "vws": 1
}
```

The current map renderer:

- unwraps longitudes to prevent dateline jumps;
- fits the route to the available viewport;
- draws latitude/longitude reference lines;
- draws the complete route polyline;
- highlights airports, FIR boundaries, BOBCAT, EDTO entry/exit, TOC/TOD and terrain-critical points;
- labels only priority points to avoid clutter; and
- works without an internet connection or external tile service.

## Safety and terminology

- ACTM remains accumulated flight time from take-off.
- Calculated UTC equals actual take-off UTC plus ACTM.
- Waypoint ATA mode derives actual take-off UTC from the entered waypoint ATA minus the waypoint ACTM.
- Map positions come from the Lido route coordinates and are for briefing orientation, not navigation.
- All fuel, weight and performance mass quantities are displayed in integer kg.
- `PLDW` is the report label for the canonical planned landing weight parsed from the Lido `PLWT` value.
- Approved operational documents, current dispatch information, ATC instructions and PIC judgement remain controlling.

## PilotDriven integration boundary

The later PilotDriven application should consume the `view.briefing` object from the canonical analysis result rather than recreating operational logic in the frontend. The frontend may change layout, mapping and interaction, but it should not alter deterministic findings or calculate independent operational conclusions.
