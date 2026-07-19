# Changelog

## 0.6.0 — integration handoff reference

- Preserved the v0.5 schematic implementation on `archive/odss-v0.5-schematic-baseline`.
- Added the complete Phase 1–7 implementation and PilotDriven combination guide.
- Added canonical route/marker GeoJSON, bounds, route hash and priority-label reference code.
- Added a provider-neutral `MapRenderer` contract and renderer chain.
- Added Amazon Location Hybrid / MapLibre interactive reference code.
- Added Playwright map-element capture for PDF parity.
- Added Amazon Location GetStaticMap fallback and labelled schematic fallback.
- Added FastAPI map endpoints, print-map template and map assets.
- Added a React/Next.js PilotDriven map component and TypeScript contract types.
- Added AWS setup, Playwright, API, testing and acceptance documentation.
- Added a GitHub Actions workflow that validates and packages the complete handoff bundle.
- No API keys, source CFPs, generated reports or proprietary manuals are included.

## 0.5.0

- Added a dark PilotDriven-style visual briefing dashboard for completed CFP analyses.
- Added route-coordinate extraction from the Lido CFP log and an offline schematic route-map renderer.
- Added the canonical `view.briefing` contract shared by the web dashboard, PDF output and future PilotDriven frontend.
- Changed Level 1 to a fixed three-page A4 landscape format:
  - Page 1 visual route briefing;
  - Page 2 operational detail; and
  - Page 3 route and contingency detail.
- Added clickable Page 1 PDF links to airport, operational, communications, EDTO and route sections.
- Added the visual route briefing as the first page of Level 2 before the expanded deterministic analysis.
- Kept PZFW, PLDW, PTOW, fuel, trip and destination fuel visible at the top of the visual brief in integer kg.
- Added actual-time UTC values to the visual communication timeline after ATOT or waypoint-ATA anchoring.
- Added longitude unwrapping and priority-label selection for long-haul routes and dateline-safe plotting.
- Added visual PDF sample artifacts and render-regression checks to GitHub Actions.
- Added a formal PilotDriven integration and map-adapter specification.

## 0.4.0

- Added persistent personal pilot notes for each flight workspace.
- Added report-placement choices for a separate section, departure airport, destination airport, and enroute ATC/communications.
- Added independent Level 1 and Level 2 inclusion controls for every note.
- Added edit and delete actions with automatic report and canonical JSON regeneration after changes.
- Kept personal notes separate from system processing-status messages and labelled them as pilot-entered, non-validated content.
- Added automatic SQLite personal-notes table creation and foreign-key cleanup.
- Added personal-note CRUD, report placement, level filtering and PDF regression tests.

## 0.3.1

- Added a prominent first-page mass strip to both Level 1 and Level 2 pertinent briefs.
- The strip displays PZFW, PLDW and PTOW in integer kilograms.
- PLDW is populated from the canonical CFP planned landing weight / PLWT field.
- Added PDF regression coverage for all three labels and values.

## 0.3.0

- Added a required operational-clock form for absolute UTC calculations.
- Added actual takeoff time (ATOT) as the normal time-zero reference.
- Added optional waypoint ATA re-anchoring.
- Added calculated UTC tables for pertinent events, early calls, FIR crossings and route waypoints.
- Added automatic date rollover and scheduled-departure variance.
- Added actual-time findings to Level 1, Level 2 and canonical analysis JSON.
- Added automatic SQLite migration for timing-reference fields.

## 0.2.1

- Corrected airport-specific NOTAM applicability using validity and supported schedules.
- Added controlled PDF validation, upload limits and incomplete-CFP failure handling.
- Corrected report pagination, timing values and repeated headers.
- Added upload, engine, reporting and workflow regression tests.

## 0.2.0

- Replaced the placeholder action with the deterministic ODSS core.
- Added Lido parsing, MEL/CDDL, BOBCAT, performance, EDTO, terrain, VWS, communications and depressurisation engines.
- Added selected weather and pertinent NOTAM extraction.
- Added Level 1 and Level 2 PDF generation.
- Added canonical JSON and organised findings.

## 0.1.0

- Initial upload/dashboard prototype with placeholder analysis action.
