# Changelog

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
- Added optional waypoint ATA re-anchoring: derived ATOT equals entered waypoint ATA minus the waypoint CFP ACTM.
- Added calculated UTC tables for pertinent events, early ATC/FIR calls, FIR crossings and all parsed route waypoints.
- Added automatic date rollover and scheduled-departure variance.
- Added actual-time findings to Level 1, Level 2 and canonical analysis JSON outputs.
- Added automatic SQLite migration for timing-reference fields.
- Added ATOT and waypoint-ATA web workflow regression tests.
- Changed normal local startup guidance to run without reload and documented `.venv` exclusion for development reload.

## 0.2.1

- Corrected airport-specific NOTAM applicability using B/C validity and supported Item D schedules.
- Removed per-airport pre-filter truncation and prioritized critical destination and alternate findings in Level 1.
- Added controlled PDF validation, upload limits and incomplete-CFP failure handling.
- Made reruns clear stale artifacts and generate uniquely named JSON and PDF outputs before publication.
- Corrected canonical flight identity, severity aggregation, timeline values and repeated PDF headers and page numbers.
- Updated FastAPI and Starlette and added upload, engine, reporting and workflow regression tests.

## 0.2.0

- Replaced the placeholder analysis action with the working deterministic ODSS core.
- Added Lido CFP parsing, MEL/CDDL matching, BOBCAT, performance, EDTO, terrain, VWS, communications and depressurisation engines.
- Added selected weather and pertinent airport NOTAM extraction.
- Added automatic Level 1 and Level 2 PDF generation.
- Added canonical analysis JSON storage and organised findings in the flight workspace.
- Added visible failure diagnostics and automatic SQLite schema migration.

## 0.1.0

- Initial upload/dashboard prototype with placeholder analysis action.
