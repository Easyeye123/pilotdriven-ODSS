# PilotDriven / ODSS Durable Project Memory

**Status:** Standing project knowledge  
**Version:** 1.0  
**Effective:** 24 July 2026  
**Purpose:** Preserve approved product decisions, operational-analysis lessons and known failure modes across development sessions.

This file is durable project documentation. It records agreed behaviour and lessons for the PilotDriven and ODSS repositories. It does not replace current company manuals, State AIP, NOTAM, meteorological products or approved operational documents.

## 1. Product identity

PilotDriven is not another chart browser or raw-NOTAM viewer.

Its primary question is:

> What operationally matters on this flight, at the applicable time, and which source supports the conclusion?

The active flight is the organising object for:

- briefing;
- navlog;
- departure and destination;
- alternates and EDTO;
- FIR communications;
- weather and volcanic ash;
- terrain/VWS/depressurisation;
- MEL/CDL/CDDL;
- documents; and
- HelpMe company-first search.

## 2. Responsibility boundary

### PilotDriven owns

- authentication and tenants;
- flight selection and navigation;
- responsive UI;
- durable storage;
- notifications;
- offline package state;
- document and HelpMe presentation; and
- commercial deployment.

### ODSS remains authoritative for

- CFP/OFP parsing;
- MEL/CDL/CDDL;
- NOTAM applicability;
- weather and volcanic-ash applicability;
- performance;
- BOBCAT;
- EDTO;
- ACTM/UTC;
- communications;
- terrain/VWS;
- depressurisation profile matching;
- canonical route/marker/hazard GeoJSON; and
- report generation.

Do not duplicate deterministic aviation calculations in React or browser JavaScript.

## 3. Pilot-briefing editorial memory

The pilot-facing pertinent brief is written for a trained pilot who understands raw operational content.

### Required behaviour

- Highlight pertinent facts and actions.
- Use operational language, not tutorial language.
- Preserve raw values where they are useful to the pilot.
- Use short sentences and compact tables.
- Keep the Level 1 brief to three A4 landscape pages unless operational content genuinely requires otherwise.
- Use content-driven floating spacing.
- Collapse absent sections completely.
- Centre the top two flight-data rows horizontally and vertically.
- Measure text before drawing to prevent overlap.
- Preserve source details in expandable or higher-level views rather than dominating Level 1.

### Prohibited regressions

Do not:

- convert the pilot brief into a management report;
- explain normal aviation concepts;
- use large decorative whitespace;
- use equal-height cards that contain empty space;
- add a generic `Review required` or `Briefing complete` banner;
- add a Level 1 source/review-gate page;
- repeat generic reminders throughout the document;
- present a methodology essay instead of operational content;
- use the same colour for departure and destination; or
- allow raw text, badges or borders to overlap.

### Urgent reminders

Retain only flight-specific, action-bearing reminders, for example:

- zero/negative performance margin;
- an airport or runway closure overlapping the operating window;
- destination weather affecting ETA;
- loss of EDTO suitability;
- direct volcanic-ash conflict;
- time-defined communication action; or
- aircraft limitation changing dispatch capability.

## 4. Standing category colours

| Category | Token |
|---|---:|
| Departure | `#2F80ED` |
| Destination | `#7C4DFF` |
| EDTO / alternates | `#2EAD74` |
| Weather / VAAC | `#D99116` |
| FIR / communications | `#0F8B8D` |
| Terrain / contingency | `#D97706` |
| Critical action | `#C62828` |
| Neutral / reference | `#64748B` |

Colour identifies category. Urgency is communicated separately with wording, icon and alert treatment.

## 5. Volcanic-ash advisory memory

### 5.1 Missing data is not NIL

A CFP statement such as:

```text
Volcanic Ash SIGMETs: No Wx data available
```

is a data-availability gap. It is not evidence that volcanic ash is absent.

### 5.2 Source and supersession sequence

Use:

1. responsible VAAC VAA/VAG;
2. applicable volcanic-ash SIGMET;
3. State/ANSP operational notices and NOTAM;
4. company dispatch/operations guidance; and
5. secondary or LLM context only as clearly separated support.

Always verify whether a later advisory supersedes the product already reviewed. Review adjacent VAACs when the cloud crosses or approaches a VAAC boundary.

### 5.3 Four-dimensional route review

Use the actual:

- CFP waypoint sequence;
- coordinates;
- ACTM/EET;
- planned flight levels;
- EDTO checked periods; and
- diversion routes.

For each official advisory valid time:

- determine aircraft position;
- use the official observed/forecast polygon;
- calculate intersection or closest lateral proximity;
- identify closest route segment and UTC;
- compare planned level with ash base/top;
- assess EDTO airports and diversion tracks; and
- show the next-advisory time when it occurs before the relevant route sector.

### 5.4 Interpolation

Interpolation between official forecast polygons may be used only as a labelled ODSS screening estimate.

Never present interpolated geometry as an official VAG.

### 5.5 Wording

Acceptable:

```text
No direct intersection identified with the filed centreline.
Closest estimated proximity 110 NM near HAMND at 1532Z.
```

Not acceptable:

```text
Route unaffected.
```

Do not use a small vertical difference above the forecast ash top as the sole mitigation.

### 5.6 Delay and actual-time logic

Recalculate the volcanic-ash result whenever:

- off-block/takeoff time changes;
- the route changes;
- a new VAA/VAG or VA SIGMET is issued; or
- an EDTO airport/diversion plan changes.

A later advisory must not be used retrospectively as proof of an earlier cloud position.

## 6. SQ24 / Sheveluch historical lesson

The SQ24 WSSS–KJFK case established the following durable lessons:

- The LIDO package reported no volcanic-ash data; this triggered an external authoritative review.
- The route required a Tokyo/Anchorage transition review for Sheveluch 300270.
- The Anchorage advisory `FVAK21 PAWU 220700` required time matching against the HAMND–TED/GKN sector and the PANC EDTO window.
- Screening found no direct filed-centreline penetration under that advisory, but proximity remained operationally pertinent.
- PANC had to be reviewed together with the diversion corridor, not only by airport point location.
- The next-advisory time occurred before the aircraft reached the relevant sector and therefore became an operational update action.
- A later advisory issued after the planned passage could not prove what the ash position had been earlier.

This is a historical case study, not a current hazard status.

## 7. Broader meteorological-hazard memory

Supplement the CFP with the responsible official authority when the CFP is stale, incomplete, unavailable or superseded.

Potential authorities include NOAA/NWS/AWC/NHC, JMA/RSMC Tokyo, BOM/TCWC, UK Met Office, ECCC and comparable State services.

Analyse the effect on:

- departure runway/taxi/takeoff;
- route segment and flight level;
- destination runway/approach/landing;
- alternates;
- EDTO airports and diversion corridors; and
- update/advisory time.

Do not merely state that a hazard exists. State the operational mechanism and UTC window.

Examples:

- tropical-cyclone wind field, convection and uncertainty;
- frontal wind shift/runway change;
- snow/freezing precipitation versus observed runway condition;
- icing level versus planned level;
- turbulence/mountain-wave segment; and
- visibility/ceiling against airport use.

## 8. MEL / CDL / CDDL memory

- Detect Page 1 MEL/CDL/CDDL references.
- Keep MEL, CDL and CDDL separate.
- Resolve CDL by exact reference and aircraft registration/effectivity.
- Present only operationally pertinent conditions, limitations and penalties in Level 1.
- Keep proprietary manuals and complete indexes in private controlled storage.
- If the controlled index is not mounted, show `controlled source not mounted`; do not invent a result.
- Do not show an empty MEL/CDL/CDDL section when no item exists.

## 9. Terrain / depressurisation memory

Use the LIDO asterisk as the primary high-MSA trigger, including `100*`.

For each continuous starred-MSA region:

1. include the waypoint preceding the first starred waypoint;
2. identify the full route/airway sequence;
3. match endpoints, direction and aircraft effectivity;
4. propose the minimal approved profile chain;
5. retain critical points and diversion references; and
6. suppress nested profiles that add no route coverage from the pilot summary.

SQ24 regression expectation:

- Profile 11-4 · HAMND–TED;
- Profile 11-37 · TED–62N20/62N120W;
- shorter nested subprofile retained only in audit data.

## 10. NOTAM and airport-geometry memory

- The official NOTAM is authoritative for operational state.
- ODSS determines applicability and affected segment.
- OSM or another geometry source supplies candidate airport geometry only.
- MapLibre renders ODSS-provided geometry; it does not resolve the closure.
- Plot a closure X only when the feature/segment match is confirmed or explicitly probable.
- Do not guess geometry.
- Whole-taxiway, between-intersection, behind-stand, directional and aircraft-code restrictions require separate deterministic match methods.
- Unmapped closures remain visible as text/manual-review items.
- Preserve source timestamp, object IDs and geometry confidence.

## 11. UI/UX memory

The preferred application design is a hybrid:

- Aviator-style modular information architecture;
- PilotDriven map-first active-flight dashboard; and
- Apple-inspired adaptive sidebar/tab/sheet behaviour.

Primary modules:

```text
Flights
Briefing
Navlog
Airports
Documents
Tools
```

Global HelpMe replaces a standalone Search page.

The active flight header remains persistent across modules. The existing briefing layout remains unchanged.

## 12. HelpMe memory

HelpMe is company-first.

Priority order:

1. applicable company manual;
2. company notice/bulletin;
3. official operational source;
4. supporting LLM result.

Every result must expose:

- source;
- revision/effective date;
- page/section;
- quoted content where authorised;
- applicability; and
- `Open source`.

External LLM content is visibly secondary and cannot override company guidance.

## 13. Testing memory

Add regression coverage for:

- three-page Level 1 output;
- no generic status/source-gate content;
- departure/destination colour separation;
- no text collisions or clipping;
- conditional collapse of empty sections;
- missing volcanic-ash data treated as unavailable;
- advisory supersession and next-advisory logic;
- route/time/level/geometry VAAC matching;
- delay/ATOT recalculation;
- EDTO/diversion ash review;
- CDL registration effectivity;
- starred-MSA profile-chain selection;
- map geometry confidence and unmapped fallback; and
- no client-side deterministic aviation calculation.

## 14. Updating this memory

Update this file only when a project decision or repeated failure mode has been reviewed and accepted.

For each material change:

1. update the relevant detailed protocol;
2. update this memory summary;
3. add or amend regression tests where possible;
4. identify whether the change belongs to PilotDriven UI or ODSS logic; and
5. preserve proprietary source material outside the public repository.
