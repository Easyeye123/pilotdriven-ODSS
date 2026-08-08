# PilotDriven Flight Briefing Publication Protocol v1.3

**Effective:** 8 August 2026  
**Status:** Mandatory for all newly generated PilotDriven Flight Briefing artifacts  
**Supersedes for current-facing publication:** `ODSS_BRIEFING_PUBLICATION_PROTOCOL_V1_2.md`  
**Historical repository note:** the repository name may retain `ODSS`; new product-facing text shall use **Flight Briefing**.

## 1. Foundational principle

> Flight Briefing computes and never guesses. Helpyou retrieves and never invents. PilotDriven presents — and the pilot always decides.

PilotDriven does not ask the pilot to trust AI. Every material operational claim must resolve to an authoritative source or a deterministic Flight Briefing calculation. Missing or stale coverage is declared; it is never converted into a benign finding.

## 2. One combined Flight Briefing

Each analysis publishes one pilot-facing PDF:

```text
<FLIGHT>_<DDMMMYYYY>_Flight_Briefing.pdf
```

Example:

```text
SQ365_07AUG2026_Flight_Briefing.pdf
```

The PDF begins with the concise flight-specific briefing and continues into the supporting operational evidence. The following terms are prohibited in current-facing PDF titles, section labels and filenames:

- `Level 1`;
- `Level 2`;
- `Pertinent Brief`;
- `Pertinent Briefing`;
- `Evidence Level`; and
- `Evidence Brief`.

Legacy API routes may remain temporarily for compatibility, but the primary service link and dashboard download must point to the combined Flight Briefing.

The complete uploaded CFP must not be appended, embedded or attached unless the pilot expressly requests it. Authoritative evidence is presented through selected source crops, exact source links and source metadata.

## 3. Information architecture and duplication control

The report uses one evidence ladder without repeating the same operational statement:

1. **Flight overview and decision gates** — only the flight-specific trigger, margin, time or consequence.
2. **Operational evidence** — calculation, applicability and source support.
3. **Authoritative source crop** — the exact relevant table, paragraph or chart when required.

Every material fact has one primary display location. Later pages may provide supporting calculation or source evidence, but must not restate the same conclusion. The manifest records a stable `fact_id`, its `primary_location` and any `supporting_locations`.

Repeated page-orientation data is limited to flight number, route, date, aircraft type, registration and page number.

## 4. Page 1 scan path

Page 1 is designed for a natural left-to-right pilot scan:

- **Left:** flight identity, CFP Page 1 planning basis, Departure, Destination, preferred Alternate, fuel/mass summary and decision gates.
- **Right:** whole-flight route map and route-linked markers.

The route map must not displace critical Page 1 information or force detailed text below the operational reading size.

### 4.1 Airport cards

Departure, Destination and preferred Alternate cards shall:

- use equal width and height;
- use the same title baseline, internal padding and text hierarchy;
- use horizontal alignment consistently;
- use vertical middle alignment for the complete text block;
- identify runway/procedure, weather at the applicable time and the principal airport consequence; and
- avoid explanatory text intended for a lay reader.

The preferred flight-planning alternate and its weather are mandatory Page 1 items.

### 4.2 CFP Page 1 critical-item coverage

Page 1 analysis shall account for, when present:

- aircraft type and registration;
- route, runway and planned level profile;
- scheduled UTC and local times;
- block time;
- ground and air distance;
- cruise component;
- burn-off and statistical contingency;
- preferred alternate fuel and holding fuel;
- taxi fuel;
- PZFW, PTOW and PLWT;
- flight-plan fuel requirement and fuel in tanks;
- excess-fuel quantity and allocation;
- destination-hold and EDTO top-up;
- MEL, CDL and CDDL entries;
- BOBCAT or other flow allocation; and
- planning sensitivities printed on Page 1.

## 5. Typography and density

The v1.3 baseline increases detailed content and operational numerics by at least 20 percent over the v1.2 minimum:

- minimum normal detailed text: **8.4 pt**;
- minimum normal operational numeric text: **8.4 pt**;
- headings and primary values shall scale proportionately;
- wrapped table and card text shall remain vertically middle-aligned;
- row and card height shall grow with content; and
- text must never be reduced merely to preserve a fixed panel.

A report fails publication for any clipped text, overlapping text, duplicate text layer, source crop covering another object, or unbalanced cell padding.

## 6. PilotDriven logo

The report uses the approved forward-flight PilotDriven mark. An `X` or crossed-line symbol is prohibited as the product logo. The logo asset identifier and hash are recorded in the publication manifest.

## 7. Decision gates and evidence links

Each Page 1 decision gate must be an internal PDF hyperlink to its correct evidence destination. Applicable categories include:

- BOBCAT / flow timing;
- EDTO or non-EDTO status;
- MEL/CDL/CDDL;
- High Terrain Exposure / depressurisation;
- SIGMET / operational hazards;
- departure, destination and alternate airports;
- performance / fuel; and
- FIR communications.

The link destination must exist, resolve correctly and contain the evidence for that gate. A decorative button without a valid destination fails release.

`TECH` is prohibited as a category label. Use **MEL/CDL** and include CDDL within the same technical-status evidence section when applicable.

## 8. Authoritative source crops

The combined report must embed a tightly cropped relevant source section for each applicable category below:

### 8.1 MEL/CDL/CDDL

Show the exact controlling item or the precise unresolved-source statement. The crop records:

- document title;
- revision or effective date;
- item/reference;
- source page;
- crop box;
- aircraft effectivity status; and
- live source destination.

Do not replace a missing controlled CDDL source with a generic MEL statement.

### 8.2 EDTO

For an EDTO flight, show the relevant checked-period table or source section containing entry/exit, ETP, alternates, approaches, minima and checked periods. For a non-EDTO flight, state the deterministic non-EDTO status once and do not create a fictional EDTO section.

### 8.3 Depressurisation

When an approved profile is matched, show:

- a concise flight-specific High Terrain Exposure analysis;
- actual route/airway/direction match;
- aircraft effectivity;
- critical point and maximum MSA;
- the cropped authoritative profile chart; and
- unresolved exposures separately.

A chart number or hyperlink alone is not compliant. Do not substitute a nearby or generic profile for an unmatched event.

## 9. High Terrain Exposure

The automatic trigger is MSA **strictly greater than `100*`**. Exactly `100*` is a boundary and does not qualify.

Each event records:

- first waypoint above threshold;
- first subsequent waypoint at or below threshold;
- ACTM start/end and duration;
- UTC estimate and time basis;
- maximum MSA and waypoint;
- filed airway sequence and direction;
- matched profile or unresolved status; and
- authoritative chart source when matched.

Discrete CFP MSA values must not be converted into a decorative mountain profile.

## 10. Mandatory Operational Hazard Assessment

Every uploaded CFP is screened against the supplied and available authoritative hazardous-weather products, including SIGMET, tropical cyclone, volcanic ash, frontal weather and clear-air turbulence products.

Each reported product must retain, where issued:

- product type and issuing authority;
- sequence/advisory number;
- issue and validity times;
- observed or forecast status;
- exact phenomenon;
- intensity or the statement `intensity not specified by issuing authority`;
- horizontal position or polygon;
- base/top or vertical band;
- movement and trend;
- filed-route relationship;
- projected UTC/ACTM entry and exit;
- flight-level relationship;
- exposure duration;
- operational consequence; and
- disposition with deterministic reason codes.

Allowed dispositions are:

- `SIGNIFICANT`;
- `RELEVANT`;
- `MONITOR`;
- `NOT_PROMOTED`; and
- `COVERAGE_GAP`.

`COVERAGE_GAP` is not a hazard finding and must never be interpreted as NIL. A weather product is not promoted merely because it exists; authoritative, temporal, spatial, vertical and operational-consequence gates must be satisfied.

Hazard reporting is written for a trained professional pilot. Generic phrases such as `bad weather`, `dangerous storm`, `rough conditions` or `exercise caution` are prohibited.

## 11. Release manifest

A release candidate shall carry a machine-readable publication manifest containing at least:

```json
{
  "protocol_version": "1.3.0",
  "report": {
    "mode": "combined",
    "filename": "SQ365_07AUG2026_Flight_Briefing.pdf",
    "full_cfp_appended": false,
    "embedded_files": []
  },
  "layout": {
    "page_format": "A4 landscape",
    "information_side": "left",
    "map_side": "right",
    "detail_font_scale": 1.2,
    "minimum_detail_font_pt": 8.4,
    "minimum_numeric_font_pt": 8.4,
    "text_overlap_count": 0,
    "clipped_text_count": 0
  },
  "release_checks": {
    "airport_card_geometry": true,
    "decision_gate_links": true,
    "source_crops": true,
    "fact_deduplication": true,
    "hazard_completeness": true,
    "source_link_integrity": true,
    "visual_preflight": true
  }
}
```

## 12. Fail-closed release gate

Publication is blocked when any of the following occurs:

- prohibited report terminology appears;
- the filename does not follow the Flight Briefing convention;
- the full CFP is appended or attached without explicit instruction;
- Page 1 map/information sides are reversed;
- airport cards differ materially in geometry or alignment;
- detailed text or numerics are below the v1.3 minimum;
- an `X` mark is used as the logo;
- a decision gate does not resolve to evidence;
- `TECH` is used instead of MEL/CDL;
- an applicable source crop is absent or lacks provenance;
- a matched depressurisation profile lacks its cropped chart;
- a fact has more than one primary display location;
- a promoted hazard lacks exact source, position, time or level data;
- a coverage gap is rendered as NIL;
- text, arrows or source crops overlap;
- text is clipped; or
- source links fail.

## 13. Compatibility and migration

The legacy Level 1/Level 2 artifacts and endpoints may remain temporarily for regression compatibility. They are not the primary product output. New UI, API and download links shall expose the combined Flight Briefing first.

No user CFP, generated operational report, proprietary company manual or controlled source content is committed with this protocol. Tests use synthetic or redacted fixtures only.
