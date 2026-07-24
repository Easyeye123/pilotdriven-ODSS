# PilotDriven / ODSS Ranked Goals and Business Scope

**Status:** standing project knowledge  
**Version:** 1.0  
**Effective:** 24 July 2026

## 1. Ranked goals

### Goal 1 - primary: analyse uploaded LIDO CFP/OFP flight plans

The primary responsibility is to analyse each supported user-uploaded LIDO CFP/OFP accurately and produce readable operational briefs for a trained pilot.

The standard output hierarchy is:

- **Level 1:** concise pertinent brief, normally three A4 landscape pages;
- **Level 2:** expanded operational brief retaining useful raw content;
- **Level 3:** source, provenance, applicability and audit evidence.

Required behaviour:

- preserve actual CFP route, ACTM/EET, flight level, mass, fuel, EDTO, FIR and airport context;
- identify only flight-applicable NOTAM, weather, volcanic ash, communications, terrain, MEL/CDL/CDDL and company-manual content;
- use trained-pilot language rather than tutorials or management-report prose;
- retain urgent, action-bearing items and collapse empty or irrelevant sections;
- distinguish source fact, deterministic calculation, screening estimate and unresolved condition;
- recalculate when time, route, aircraft, advisory, NOTAM or operating context changes;
- fail closed when authoritative coverage or a controlled reference is unavailable.

This goal has priority over visual experimentation, feature expansion and commercial presentation.

### Goal 2 - secondary: develop PilotDriven with ODSS as the engine

PilotDriven is the airline-facing flight-centred workspace. ODSS remains the authoritative deterministic analysis service.

PilotDriven owns:

- authentication, tenants and roles;
- active-flight and multi-leg context;
- responsive hybrid UI/UX;
- navigation, documents, HelpMe, notifications and offline package;
- durable commercial storage, administration and deployment.

ODSS owns:

- CFP/OFP parsing;
- MEL/CDL/CDDL;
- NOTAM applicability;
- meteorological and volcanic-ash applicability;
- performance, BOBCAT and EDTO;
- ACTM/UTC and communications;
- terrain, VWS and depressurisation matching;
- canonical briefing and GeoJSON contracts;
- report generation.

Do not duplicate deterministic aviation calculations in React or browser JavaScript.

## 2. Decision rule when goals compete

When a product-development decision conflicts with the primary analysis mission, apply this priority order:

1. operational correctness and source integrity;
2. pilot readability and scanability;
3. deterministic reproducibility and auditability;
4. availability and fallback behaviour;
5. responsive usability;
6. visual polish and commercial differentiation.

The approved pilot-briefing layout is a protected operational surface. UI work may improve the shell around it, but must not silently rearrange the information hierarchy or alter ODSS findings.

## 3. Business-product scope

The commercial product is an operational briefing workstation built around one active flight. Expected modules are:

```text
Flights
Briefing
Navlog
Airports
Documents
Tools
HelpMe
```

The approved design direction combines:

- Aviator-style modular information architecture;
- PilotDriven map-first active-flight dashboard; and
- Apple-inspired adaptive sidebar, tab, sheet and focus behaviour.

## 4. Expected commercial features

### Core flight intelligence

- supported LIDO CFP/OFP ingestion;
- Level 1, Level 2 and Level 3 brief generation;
- active-flight map and chronological event ribbon;
- NOTAM, weather, VAAC, EDTO, FIR, terrain and communication applicability;
- MEL/CDL/CDDL and company-manual integration;
- ATOT and waypoint-ATA recalculation;
- change-since-briefing notifications;
- offline flight package.

### Company-first HelpMe

Search priority:

1. applicable company manual;
2. company notice or bulletin;
3. official operational source;
4. supporting external LLM context.

Every result must expose source, revision/effective date, page/section, applicability and an open-source action. External LLM content is secondary and cannot override company guidance.

### Airport Intelligence Compiler

The planned compiler creates flight-specific airport general, departure and arrival briefs from authorised content.

Potential inputs:

- licensed Jeppesen charts, APIs or operator-authorised chart content;
- State AIP/eAIP AD 2, ENR, AIP supplements and AIC;
- NOTAM and airport weather;
- company airport briefs and manuals;
- aircraft, runway, procedure and flight context.

Expected outputs:

- airport general brief;
- runway, surface, hotspot and low-visibility information;
- departure runway, SID, terrain, EOSID/noise and communication considerations;
- arrival STAR, approach, minima, missed approach, runway-exit and taxi-in considerations;
- State procedural differences and source effectivity;
- concise pilot wording with source-linked evidence.

The compiler must not scrape, reproduce or train on licensed chart content without rights. Commercial use requires a licensed API/SDK/content agreement, operator-authorised content or another legally reviewed delivery model.

## 5. Commercial positioning

PilotDriven should complement approved charting, dispatch and EFB systems rather than initially replace them.

Its differentiation is:

- the CFP as the organising context;
- operator-specific synthesis across company manuals, State requirements, NOTAM, weather and hazards;
- route, time, level, aircraft and phase applicability;
- source-controlled conclusions;
- deterministic ODSS auditability;
- provider-neutral integration potential.

Initial market priority:

- long-haul airlines;
- international operators with EDTO and complex State requirements;
- flight operations engineering, dispatch/OCC, safety and EFB programme teams.

## 6. Safety and governance

- Current approved manuals, AIP, NOTAM, meteorological products, dispatch information, ATC instructions and commander judgement remain controlling.
- Proprietary manuals and full controlled indexes remain in private governed storage.
- Missing data is not converted to NIL.
- Unsupported geometry remains textual rather than guessed.
- Screening estimates are labelled and never presented as official source geometry.
- Every material output must be reproducible from the same source set and flight context.

## 7. Maintenance

Update this file only after the user and project have accepted a material change to ranked goals or commercial scope. Detailed implementation and safety rules remain in the standing protocols and `PILOTDRIVEN_PROJECT_MEMORY.md`.