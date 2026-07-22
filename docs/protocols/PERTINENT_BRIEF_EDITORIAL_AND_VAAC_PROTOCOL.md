# PilotDriven Pertinent Brief Editorial and Volcanic-Ash Review Protocol

**Status:** Standing project protocol  
**Version:** 1.0  
**Effective:** 23 July 2026  
**Applies to:** ODSS and PilotDriven pilot-facing pertinent briefs, dashboard summaries, PDF reports, route-map alert cards, and future automated report generation.

## 1. Purpose

This protocol records the operating and editorial lessons established during the SQ24 WSSS–KJFK review. It is the default standard for future PilotDriven pertinent briefs unless superseded by a later approved protocol.

The pilot-facing product must be:

- operationally concise;
- route- and time-specific;
- readable at normal PDF size;
- free of unnecessary status commentary and repeated reminders;
- explicit about urgent or critical items;
- supported by a complete audit trail outside the main pilot reading flow.

The brief is written for a trained pilot. It is not a tutorial, a data-quality report, or a methodology paper.

---

## 2. Standing output contract

### 2.1 Default report format

Use a compact three-page A4 landscape format unless the operational content genuinely requires another page.

- **Page 1 — Flight control and principal exceptions**
  - flight identity and timing;
  - route and level summary;
  - mass and fuel summary;
  - departure considerations;
  - destination considerations;
  - principal enroute exceptions;
  - urgent crew actions.

- **Page 2 — Airport, weather, NOTAM and alternate detail**
  - departure surface/runway items;
  - destination runway/approach/surface items;
  - destination and alternate weather;
  - pertinent enroute airport closures or restrictions;
  - MEL/CDL/CDDL only when present and operationally relevant.

- **Page 3 — EDTO, FIR communication, terrain, contingency and volcanic ash**
  - EDTO periods, ETPs and airport suitability;
  - FIR communication and early-contact events;
  - MSA/VWS and depressurisation profile matches;
  - volcanic-ash review when relevant;
  - only the contingency items that affect the flight.

### 2.2 No visible review-status bureaucracy

Do **not** include the following in the pilot-facing brief:

- “Level 1 review status”;
- “review required” banners used as a generic document state;
- a “source/review gates” section;
- repeated “not an operational release” reminders;
- repeated instructions to check normal operational sources;
- generic reminders that a trained pilot already understands.

Source provenance, parser confidence, document revision, effective date and audit evidence must remain available in ODSS/PilotDriven metadata, hyperlinks, expandable detail, or the Level 2/audit view. They must not dominate the pertinent brief.

### 2.3 Retain urgent critical reminders

Critical reminders remain prominent when they are flight-specific and action-bearing. Examples include:

- zero or negative displayed takeoff-performance margin;
- runway or airport closure overlapping the operating window;
- destination thunderstorm or low-visibility risk at ETA;
- an EDTO airport falling below the required planning condition;
- an active or forecast volcanic-ash conflict;
- a communication action with a defined time or boundary;
- an unresolved aircraft limitation that changes dispatch or operating capability.

Routine reminders are omitted. Critical reminders use direct action language.

---

## 3. Editorial and readability standard

### 3.1 Floating-spacing concept

Panels and sections must use content-driven height rather than equal-height cards.

- Do not reserve blank vertical space for absent content.
- Collapse empty sections completely.
- Allow each panel to grow only to the measured height of its content.
- Use approximately 4–5 pt internal paragraph spacing.
- Use approximately 6–8 pt between related blocks.
- Use approximately 10–14 pt between major page zones.
- Avoid forced page breaks that leave substantial unused areas.

The objective is compact readability, not maximum density and not decorative whitespace.

### 3.2 Top two rows

The top two flight-information rows must be:

- horizontally centred within each cell;
- vertically centred within each cell;
- aligned to a consistent baseline;
- displayed using consistent number formatting;
- free of left-biased labels or uneven padding.

Typical fields include flight number, route, date, ETD, ETA, aircraft, cruise level, alternate, trip time, PZFW, PTOW, PLDW and fuel.

### 3.3 Sentence and line spacing

- Use real text measurement before drawing or exporting.
- Do not use fixed-height text boxes for variable narrative.
- Use word-boundary wrapping.
- Maintain a minimum line-height ratio of approximately 1.15 for body text.
- Keep headings visually separate from the first sentence.
- Prevent any body line, badge, border or footer from overlapping another object.
- Run visual regression at normal PDF scale and at print scale.
- Inspect every generated page for clipping, orphan headings and collisions.

### 3.4 Writing style

- Prefer one operational fact or action per sentence.
- Use short, active constructions.
- State the time window and affected object early.
- Use exact values where they matter.
- Avoid repeating raw NOTAM wording when a concise operational interpretation is sufficient.
- Retain the original text one action away in the interactive product or audit view.
- Do not explain normal aviation concepts to the trained reader.
- Distinguish fact, calculation and screening estimate explicitly.

### 3.5 Tables and cards

- Use tables for comparable items such as EDTO airports, alternates and communication events.
- Use cards for exceptions or actions, not for every data field.
- Do not create a card merely to decorate information.
- Keep table row height content-driven.
- Use subtle rules and restrained borders.
- Do not hide critical values inside prose.

---

## 4. Colour-coding standard

Colour identifies the **information category**. Urgency is conveyed separately by wording, icon, border weight and alert treatment.

| Category | Colour | Recommended token | Meaning |
|---|---|---:|---|
| Departure airport | Blue | `#2F80ED` | Origin runway, SID, departure weather, pushback and taxi-out |
| Destination airport | Violet | `#7C4DFF` | Arrival runway, approach, destination weather and taxi-in |
| EDTO / alternates | Green | `#2EAD74` | EDTO sectors, ETPs, alternates and suitability |
| Weather / VAAC | Amber | `#D99116` | Meteorological hazards, volcanic ash and forecast uncertainty |
| FIR / communications | Teal | `#0F8B8D` | FIR transitions, CPDLC/HF/voice and early contact |
| Terrain / contingency | Orange | `#D97706` | MSA, VWS, depressurisation and route contingency |
| Critical action | Red | `#C62828` | Immediate action, unavailable margin or direct operational conflict |
| Neutral / reference | Slate grey | `#64748B` | Times, context and non-urgent supporting data |

Rules:

1. Departure and destination must never share the same category colour.
2. Red is reserved for a genuine critical action or conflict; it is not a general attention colour.
3. Amber indicates weather/VA or caution, not necessarily a direct conflict.
4. Colour must never be the only cue. Every coloured object also requires a heading, label or icon.
5. Text/background combinations must meet accessible contrast targets.
6. The colour legend belongs in the design standard, not as a repeated legend in every pertinent brief.

---

## 5. Volcanic-ash advisory review protocol

### 5.1 Trigger

Run a volcanic-ash review when any of the following applies:

- a VAA/VAG or VA SIGMET is active near the route or a diversion area;
- a volcano lies within the broad route corridor and is erupting or emitting ash;
- the CFP weather package states that volcanic-ash data is unavailable;
- dispatch, company information, NOTAM or weather material identifies a relevant eruption;
- an EDTO airport or diversion route may be affected.

“Volcanic Ash SIGMETs: No data available” is a **data-availability gap**, not evidence that no ash exists.

### 5.2 Source order

Use the most current material in this order:

1. responsible VAAC VAA and VAG;
2. applicable volcanic-ash SIGMET;
3. State/ANSP operational notices and NOTAMs;
4. company dispatch or flight-operations guidance;
5. secondary meteorological or LLM explanation only as supporting context.

Record:

- WMO header, for example `FVAK21 PAWU`;
- issue UTC;
- advisory number;
- volcano name and identifier;
- volcano position;
- observed and forecast ash levels;
- movement and speed;
- observed and forecast polygons;
- next-advisory time;
- cancellation or “no further advisories” status.

Always check whether a later advisory supersedes the one already reviewed.

### 5.3 Responsible VAAC and overlapping coverage

Do not stop at the first advisory found. Determine which VAAC is responsible for the observed or forecast ash area at the flight-relevant time. Review adjacent VAAC products when ash crosses or approaches a VAAC boundary.

For a Kamchatka/Aleutian event, this can require reviewing both Tokyo and Anchorage products and selecting the latest advisory that governs the forecast cloud near the route.

### 5.4 Route and time matching

The route review must use the actual CFP waypoint sequence, coordinates, ACTM/EET and planned flight level.

For each relevant advisory time:

1. interpolate the aircraft position along the filed route using route leg distance/time;
2. use the official observed or forecast polygon for that valid time;
3. calculate great-circle distance from the route position/segment to the polygon boundary and interior;
4. identify the closest waypoint or route segment and UTC;
5. compare the planned level with the published ash base/top;
6. repeat for EDTO airports and credible diversion corridors.

Handle longitude crossing at 180° correctly. Normalise malformed but unambiguous coordinates only when the normalisation is recorded. Do not silently repair an ambiguous advisory.

### 5.5 Interpolation between forecast periods

Linear interpolation between official forecast polygons may be used for **screening only** when the aircraft reaches the area between published forecast times.

The output must say that the result is an estimated, time-matched screening calculation. It must not display the interpolated polygon as an official VAG.

Official polygons and interpolated screening geometry must use visibly different line styles and labels on the map.

### 5.6 Horizontal and vertical interpretation

Use precise wording:

- “No direct intersection identified with the filed centreline” is acceptable when supported by the calculation.
- Do not say “unaffected” merely because the route does not enter the polygon.
- Report the measured or estimated minimum lateral distance, closest segment and time.
- Report the planned flight level and ash top/base.
- Do not imply that a small vertical difference makes flight over or under ash acceptable.
- Do not invent a universal safe lateral threshold. Apply an operator-approved threshold when available; otherwise report the measured proximity and operational context.

### 5.7 EDTO and diversion review

A volcanic-ash review is incomplete until it checks:

- each EDTO airport during its checked period;
- diversion route from the ETP/route to the airport;
- arrival, missed-approach and holding areas where relevant;
- forecast ash proximity at the diversion time;
- weather, runway and approach availability together with ash;
- whether another suitable airport should receive greater planning priority.

An EDTO airport outside the ash polygon may still be operationally pertinent when the polygon is close to the airport or diversion corridor.

### 5.8 Update timing

When the next VAA is due before the aircraft reaches the affected sector:

- display the next-advisory UTC as an action time;
- re-run the route and EDTO screening after receipt;
- supersede the earlier result rather than accumulating conflicting summaries;
- retain the prior advisory only in the audit trail.

### 5.9 Pilot-facing VAAC card

The pertinent brief should show only:

- volcano and advisory identifier;
- issue time and forecast validity;
- ash level range;
- direct route-intersection result;
- closest route segment/time and lateral estimate;
- EDTO/diversion consequence;
- next update or required action.

Methodology, source hierarchy and full coordinate lists belong in expandable detail or the audit report.

---

## 6. Operational wording and confidence

Use these distinctions consistently:

- **Official fact:** directly stated in the CFP, VAA, SIGMET, NOTAM, AIP or company manual.
- **ODSS calculation:** deterministic result from official inputs, such as UTC conversion or geodesic distance.
- **Screening estimate:** interpolation or approximation used where no official intermediate product exists.
- **Unresolved:** insufficient or conflicting information; no conclusion is manufactured.

Examples:

- “Anchorage VAAC forecasts ash SFC–FL370 at 1855Z.”
- “ODSS calculated the closest filed-route distance as approximately 100 NM near the TED–GKN sector.”
- “This distance uses interpolation between official forecast polygons and is a screening estimate.”

Do not combine these into one unqualified sentence.

---

## 7. Lessons learned and prohibited anti-patterns

### 7.1 Volcanic ash

Do not:

- interpret “no VA data available” as no hazard;
- reuse an older advisory without checking for a later issue;
- rely on a static map without matching route and ash by UTC;
- assess only the route centreline and ignore EDTO/diversion airports;
- present interpolated geometry as official;
- treat altitude above the forecast ash top as the sole mitigation;
- retain superseded findings alongside the current finding in the pilot summary;
- declare the route “unaffected” when only non-intersection has been established.

### 7.2 Editorial layout

Do not:

- use equal-height cards that create large blank interiors;
- place departure and destination in the same colour;
- use fixed-height narrative boxes that can overlap;
- repeat generic disclaimers on every page;
- include a source/review-gate page in the pilot brief;
- add a document-level review-status banner that competes with real alerts;
- use red for non-critical information;
- leave an empty section visible;
- hide a critical action in a paragraph;
- fill pages for the sake of page count.

---

## 8. Automated QA and acceptance checks

Each generated pertinent brief must pass:

1. **Content fit:** no clipped or overlapping text, badges, borders, headers or footers.
2. **Whitespace:** no substantial unused card area caused by fixed heights.
3. **Alignment:** top two rows centred horizontally and vertically.
4. **Colour:** departure and destination visibly distinct; red used only for critical action.
5. **Urgency:** all flight-specific critical actions appear on Page 1 or in the first visible exception area.
6. **Redundancy:** no generic review-status or source-gate section.
7. **Route fidelity:** route sequence, coordinates and levels match the uploaded CFP.
8. **VA currency:** latest applicable VAA/VAG and VA SIGMET checked when volcanic ash is relevant.
9. **VA timing:** route and ash compared at matching UTC; closest segment/time recorded.
10. **EDTO:** volcanic ash and other hazards assessed against EDTO airport windows and diversion paths.
11. **Map distinction:** official advisory geometry and screening estimates clearly differentiated.
12. **Pilot readability:** readable at normal PDF size without zooming into every paragraph.
13. **Audit preservation:** sources, revisions and calculations retained outside the main pilot reading flow.

Visual-regression fixtures should include:

- a short-haul brief with minimal exceptions;
- a long-haul EDTO brief;
- a brief with multiple airport surface closures;
- a brief with destination weather at ETA;
- a brief with a volcanic-ash non-intersection but close approach;
- a brief with direct volcanic-ash intersection;
- a brief with no MEL/CDL/CDDL content;
- a brief with long wrapped sentences to test collision handling.

---

## 9. Implementation ownership

ODSS remains authoritative for:

- CFP parsing and route timing;
- current flight-level profile;
- NOTAM and weather applicability;
- volcanic-ash route/EDTO geometry calculations;
- confidence classification;
- report data and PDF generation.

PilotDriven owns:

- navigation and responsive presentation;
- tenant and flight context;
- interactive expansion of source evidence;
- notifications and update prompts;
- commercial storage and delivery.

React and other presentation components must not independently reproduce volcanic-ash, EDTO, timing or route calculations.

---

## 10. Standing instruction

Apply this protocol to every future pertinent brief unless the user explicitly requests a different format or an approved later protocol supersedes it.
