# Changelog

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
