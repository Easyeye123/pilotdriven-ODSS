# Changelog

## Unreleased

- The combined report response now states the publication format of the PDF it served (`X-ODSS-Briefing-Format: six-page-reference-briefing-2026-09-15`, from the new `COMBINED_BRIEFING_PUBLICATION_FORMAT`). A client that stores a rendered briefing inside a saved flight pack could not otherwise tell whether that stored file still holds the format in service, so a pack saved before the six-page rebuild kept handing back its nine-page PDF. The token is deliberately coarser than `COMBINED_BRIEFING_SCHEMA_VERSION`: a wording or content correction bumps the schema version and the server's own cache key without invalidating a stored PDF's format, and only a change to the published page set bumps this one.
- A derived airport NOTAM line can no longer be a copy of the NOTAM. Release 22's mandatory private-corpus gate refused two of the 28 pinned flights - SQ326-SIN-FRA on EDDF 1A4143/26 and SQ352-SIN-CPH on EKCH 1A1353/26 - because `check_concise_pdf` found the whole source record on a published page, and `render_analysed_briefing` deletes the PDF and raises when it does: in production either notice shape made Download PDF fail outright. `derive_notam_restriction_line` now offers its line and then its source-bound shortenings, and the gate's own copy rule (the whole normalized item E at three words or more, or any 18-word run of it, with the gate's normalization and thresholds unchanged) decides which one may be published. No branch can bypass it, and the same guard is in the dashboard's `notam-restriction-line.mjs`, pinned to this one by the 1,397-vector cross-runtime differential.
- Shortens only in the source's own words, never by paraphrase: a declaration heading publishes its scope and the runways its list literally names (`OCA(H) values raised: RWY 07C, RWY 07R, RWY 25L, RWY 25C.`) instead of the first minima set; a clause is cut before its cause, its purpose preamble, its document reference or its label rather than mid-statement; and the last resort is the subject the notice names before it states anything, with the existing unresolved marker. A kept statement never loses what qualifies it - a condition is never cut short, and a time window, an aircraft limit, an exception or a civil-use qualifier is never dropped; where an outage applies may be dropped only because doing so widens the outage rather than narrowing it. A clause may only stand in for the chosen one when it bites at least as hard, so a closure is still never lost to a weaker line.
- Reads a US NOTAM's accountable location and NAV keyword as publication envelope when a runway designator names the facility (`ORD ILS RWY 28L CAT II/III NA`), exactly as the AIP supplement header above repeats its aerodrome. A location that IS the facility is kept: `SAX NAV VOR U/S` still names SAX.
- Bumped `COMBINED_BRIEFING_SCHEMA_VERSION` to `2026-09-18-non-copying-restriction-line-v57` so a saved analysis cannot keep serving a cached PDF that carries a copied line.
- Rebuilt the downloaded Flight Briefing to David's six-page reference format: OVERVIEW, DECISION ANALYSIS, PERFORMANCE / FUEL AND TECHNICAL STATUS, AIRPORTS / ALTERNATES, WEATHER / ROUTE HAZARDS and ENROUTE / INTAM / ASSURANCE, each with the navigation ribbon and the footer triplet.
- Publishes the ranked decision findings the engine already computes as severity-pilled cards with a flight-phase decision timeline; no finding is invented and nothing unevidenced is promoted.
- Relocates every published fact rather than dropping it: the surface figures and per-airport NOTAM analysis move to AIRPORTS / ALTERNATES, deferred declarations to the technical status card, the route hazard key to WEATHER / ROUTE HAZARDS, and VWS/CAT/terrain plus the review record to the closing page.
- Fails closed on capacity as before: column width and a bounded body ladder are tried first, and publication is refused rather than truncating a source-bound line or printing below the readable floor.
- Bumped `COMBINED_BRIEFING_SCHEMA_VERSION` to `2026-09-15-six-page-reference-briefing-v48` so a saved analysis cannot keep serving its cached nine-page PDF from persistent report storage after the deployment.
- Publishes the analysed consequence for the ranked deferred item instead of the declaration's block-capital company remark, and the publication gate now rejects a copied source remark on every page rather than only the technical page.
- Makes the repeated item-badge check precise instead of skippable: it matches the block-capital `REVIEW REQUIRED` badge on every analysed page, with or without an analysis view, and no longer switches itself off when analysed prose happens to say "review required".
- Names the deferred defect again on the decision, technical-status and release-gate surfaces, in sentence case rather than the declaration's block capitals: an analysed consequence that does not say what it is a consequence of is not a finding. Source shorthand (`RH`, `D4L`, `IFE`, `HST`, part numbers) is preserved, only letter case changes, and a declaration that records an interim HST repair now publishes that state without claiming how long it stays acceptable.
- Decides sentence casing with a lexicon instead of a vowel test, so an abbreviation survives publication: a block-capital source word is lowered only when it is recognised English (`app/odss/plain_english.py`, backed by a checked-in Webster's-derived word list), and everything unrecognised keeps the source's capitals. `MEL`, `NEF`, `ECP`, `ILS`, `CAT II/III`, `TCAS`, `GPU`, `IRS`, `EGT`, `EFB` and `AOG` are no longer destroyed, and a phrase is no longer half-cased word by word.
- Publishes a declaration's subject only when the OFP form cell is a statement in its own right. A cell the form cut mid-sentence ("... REMOVED AS PER", "... LOWER SEAL FOUND"), a slice out of the middle of a cell, a doubled drop-down label, an unselected "OTHERS (PLS ENTER COMMENTS)" placeholder, a manual section heading and a bare cross-reference to other paperwork are no longer published as the aircraft defect; the row keeps its declaration reference and analysed consequence instead.
- Added a reference-conformance release gate that answers David's 9 Sep 2026 question "How do you ensure that [the standard does not degenerate]???". `scripts/check_reference_conformance.py` renders corpus flights through the exact production Download PDF call (`render_combined_briefing`, no audit appendix) and compares the physical PDF with the structure minted from his own reference briefings in `tests/boss_reference_format_manifest.json` - page count, ordered section titles, the navigation ribbon and its active item, the footer identity/assurance/page triplet, the page-1 departure and destination columns, the drawn CFP route panel, the five provenance-tagged tiles, the release strip, and the page-2 severity grid and flight-phase decision timeline.
- Mints that structure from David's files rather than from ours (`scripts/mint_reference_conformance.py`), records the SHA-256 of every file it was read from, refuses to pin a structure his two renders of the same briefing disagree on, and re-verifies the pinned structure against those files on every release. The floors this codebase adds beyond his document are declared separately as `contract_extensions`, each with the reason it is ours and not his ruling.
- Enforces the same conformance inside the mandatory private-CFP corpus runner, so every corpus flight's download is checked, not only the five the standalone gate names.
- Re-pinned the SQ214 REV3 raster gate to the artefact it actually guards. It compares the internal lossless audit composition (`include_audit_appendix=True`), which no production download requests, so it can no longer be cited as the publication-format gate: its manifest must declare `artefact: internal-lossless-audit-composition`, and pointing it at a candidate short enough to be the six-page publication is now a hard error naming the conformance gate instead.
- Compares David's page-1 column field labels whole instead of on their first word. The earlier check folded each label down to its head word, so his `TAF TEMPO` destination field shrinking to a bare `TAF` passed as conformant and the gate reported `valid=True` over a live disagreement with his reference.
- Publishes his `TAF TEMPO` field in the page-1 destination column: the source TAF's temporary group verbatim, with the absent case named ("No TEMPO group in the source TAF") rather than published as an empty forecast. The departure column keeps his plain `TAF` with the full forecast. Bumped `COMBINED_BRIEFING_SCHEMA_VERSION` to `2026-09-16-destination-taf-tempo-field-v49` so a cached pre-change PDF cannot keep serving the old field.
- Keeps three statements the rebuild had dropped: the release caveat that current weather, airport surface state and operative aircraft limitations must be confirmed before use; the analysed surface/approach consequence count on the overview station columns; and the OFP VWS threshold summary alongside the VWS events.
- Redraws the airport surface figures David rejected on 9 Sep 2026 ("This is also rubbish generated" - three bare runway lines, no taxiways, no apron, no scale). The surface overlay contract now accepts the exact OSM aerodrome boundary the app already computes (`aerodromeBoundary`, optional, so a browser on the previous bundle still publishes), and the AIRPORTS / ALTERNATES figure strokes it as a dashed field outline, fits the whole field inside the panel, fills apron and stand polygons as translucent pavement areas (a marked one in its mark colour), and carries a scale bar with a round ground distance plus a north arrow. Every stroke is still a supplied feature; nothing is inferred.
- Left-aligns the "Airport surface geometry is not held in this analysis." fallback at the top of the panel and prints under it which source is missing (no overlay published by the app's surface lookup, or an extract with no report-eligible geometry) instead of one centred sentence in an empty panel ("Even the alignment is centred .. it is not what's asked").
- Pins the Amazon Location static-map `geojson-overlay` cap at 4,200 bytes (`STATIC_MAP_OVERLAY_LIMIT`) with tests, and simplifies deterministically down to it - coordinates to six decimals, unmarked context thinned then dropped - while never dropping a runway, a marked feature or its marker: when those alone do not fit, the satellite render is refused and the validated schematic stands, as before. The overlay receipt (`report_map.overlay`) records the rung taken.
- Bumped `COMBINED_BRIEFING_SCHEMA_VERSION` to `2026-09-17-surface-figure-outline-aprons-scale-v50` so a saved analysis cannot keep serving the cached pre-change figure.
- Lays AIRPORTS / ALTERNATES out as his reference does: a departure column beside a destination column, each the airport's surface figure over its analysed consequences, the alternates row under both. The column row takes every point of height the measured alternates row leaves, so the figure is sized by the page instead of a fixed 104-158 pt band (his VHHH figure on SQ882 grows from a 145 x 105 pt thumbnail to about 268 x 200 pt; a departure column is bounded only by its own consequences text).
- Strokes taxiways at 1.3 pt in their own tone instead of 0.7 pt hairlines ("no taxiways"), keeps runways at 2.4 pt and marked pavement at the 3.2 pt the state gate reads back, and prints the figure legend as a claim about the figure: "dashed: aerodrome boundary" and "shaded: apron / stand area" appear only when an outline or an apron polygon was drawn.
- Names, under the "not held" fallback, what the app's airport index says about the airport: an OFP station package recorded as unavailable or in error (so no overlay was requested), a held package whose surface lookup published no overlay, or no index at all. Read from the published index, never guessed.
- Replaces the synthetic-ring VHHH figure fixture with the report contracts the app now publishes for VHHH and WSSS, produced by the app's own provider and contract builder from a live OpenStreetMap extract (17 Sep 2026): the real aerodrome outlines, the apron multipolygon relations the app now converts (VHHH's Midfield, Passenger and Cargo Aprons), and the named taxiways inside its 256-feature bound.
- Bumped `COMBINED_BRIEFING_SCHEMA_VERSION` to `2026-09-17-surface-figure-columns-aprons-taxiways-v51` so a saved analysis cannot keep serving the cached banded figure.
- Accepts the extract provenance the app now publishes under the surface contract's `source` (`reportScopeVersion`, `stale`; both optional so a browser on the previous bundle still publishes) and, when a figure is drawn without its field outline, prints why under the geometry - "no field outline: cached extract predates it; refresh failed" for a report-scope-1 cache the app stood in for a failed refresh, "the extract predates it", "none established from OpenStreetMap", or "no field outline published" when nothing was stated. Read from the contract, never guessed; the geometry strip gives up that line's height so pavement is never drawn through it. The empty-extract fallback reason likewise says when a cached extract stood in.
- Bumped `COMBINED_BRIEFING_SCHEMA_VERSION` to `2026-09-17-surface-figure-outline-provenance-v52` so a saved analysis cannot keep serving a cached figure that omits the reason.

- Added a bounded official Météo-France Toulouse VAAC VAA/VAG connector and an authenticated WIFS global TCA connector covering all seven ICAO TCACs.
- Keeps direct advisory gaps fail-closed: TC track context never substitutes for TCA coverage, and missing WIFS credentials never become a NIL or all-clear result.
- Prints David's page-1 weather fields in his form. The METAR / TAF station columns print the held record's base-period groups with the OFP publication envelope removed (`SA 201900 11004KT 9999 FEW018 BKN300 28/23 Q1011 NOSIG=` becomes `11004KT 9999 FEW018/BKN300`; `FT 201700 2018/2200 16008KT 9999 FEW015 SCT020=` becomes `16008KT 9999 FEW015/SCT020`), every held cloud layer kept, a cut trend or change group pointed at the WEATHER page rather than dropped silently, and SCHEDULE prints the UTC clock beside the station's local clock (`0050Z / 0850 LT`) from the pinned zone registry, `LT not held` when the registry has no station. The rule lives once in `app/odss/page_one_weather.py` and is pinned token for token to the dashboard's `page1-weather.mjs` by `tests/fixtures/page1-weather-vectors.json` (every held record of the two real corpora); `overview.<role>.schedule.display_local` is published in the contract so both surfaces print one value.
- Publishes the observation a METAR-only station assessment was built from as its `forecast_source` (`record_type: METAR`, `raw_text`, `observed_at_utc`, the NOAA/OFP reference fields). The WEATHER page prints `Basis: METAR observation <time>; <source>.` for that shape, never a forecast validity it does not hold, and the audit appendix's fallback label is now `Forecast source not published by this analysis` - never "details unavailable", the sentence David photographed on 9 Sep 2026. Bumped `COMBINED_BRIEFING_SCHEMA_VERSION` to `2026-09-17-page1-weather-groups-local-time-v53` so a cached page 1 cannot keep printing the envelope.
- Prints the SIGMET card's verdict in words on the FLIGHT HAZARD KEY (David, 9 Sep 2026, on the SQ882 key: "hazard analysis okay. But not WX ... that is for what???"). Each OFP SIGMET line now says whether the filed route crosses the area and whether it does so inside the product's validity - `crosses route 0215-0247Z inside validity`, `crosses route 0241-0319Z outside validity (starts 81 min after latest crossing)`, `route does not cross area`, or the unresolved case in plain words - instead of one `flight relevance unverified` for a promoted and an unpromoted crossing alike. The time-validity decision is one shared function for the card and the key (`briefing._sigmet_time_state`), the key event carries the card's `disposition`, a held verdict the current geometry contradicts is published as a disagreement, and `check_concise_pdf` refuses a page whose key words and card verdict differ (`ROUTE_HAZARD_KEY_DISPOSITION_PARITY`). No disposition badge is printed on the key.
- Sets `level_matched` for OFP SIGMET events from held evidence only: the SIGMET's stated layer (`SFC/FL100`, `FL250/400`, geometric heights, or a top alone for the surface-based TS/DS/SS/TC phenomena, the convention the live matcher already applies) against the OFP planned level profile over the crossing legs, widened by one fix so a step climb at the crossing is inside the band. Inside the layer is conservative and completes the `affects flight: route/time/level match` verdict; outside is asserted only for a crossing between the held TOC and TOD, and otherwise the level stays `not verified`. The overview map draws a hazard area solid only when route, time and level all match.
- Bumped `COMBINED_BRIEFING_SCHEMA_VERSION` to `2026-09-17-route-hazard-key-disposition-v54` so a saved analysis cannot keep serving a cached key that reads the same for every crossing.

## 0.6.1 - route-aware volcanic-ash review

- Added an auditable NOAA Aviation Weather Center international-SIGMET snapshot and route/time/planned-flight-level intersection engine for volcanic ash.
- Treats boundary contact as an intersection and handles route and advisory geometry across the antimeridian.
- Fails closed to `review_required` when the source is unavailable, stale, incomplete, or does not cover the complete flight window; CFP text such as `No Wx data available` is never presented as a clear result.
- Adds a colour-coded fourth Level 1 page for affected or unresolved volcanic-ash reviews while retaining the three-page report for verified non-applicability.
- Omits the BOBCAT label and content when a flight has no BOBCAT allocation.
- Adds verified hazard GeoJSON to map contract 1.1 and the schematic, MapLibre, Amazon Location static, React and print renderers.
- Preserves source URL, retrieval time, response hash, record counts and match evidence in the canonical analysis JSON.
- Corrects abbreviated Lido coordinate waypoint parsing so planned level changes such as `63N140W/410` can be matched to route entries such as `63N40`.

## 0.6.0 — authoritative service integration

- Mounted the handoff map reference inside the working ODSS FastAPI application.
- Added Bearer-authenticated `/v1` analysis, briefing, timing, map and report endpoints for PilotDriven.
- Added tenant/user/workspace/flight context fields for audit while keeping commercial identity in PilotDriven.
- Stored one canonical map contract and route hash for dashboard, fallbacks and report capture.
- Added the Playwright report worker and image embedding in Level 1/Level 2 reports.
- Added compact Amazon Location static-map overlays with deterministic route simplification.
- Added service API, fallback, report-worker, static-overlay and external golden regression coverage.
- Added SQ303 and SQ304 command-line golden runners for core and service boundaries.
- Rebuilt Level 1 as a reviewed three-page landscape brief with a colour-coded summary map, operational detail and route/contingency pages.
- Reduced routine route labels and added collision-aware PDF placement so long-haul maps remain legible.
- Added a bundled public-domain Natural Earth 1:110m land layer so offline URL/PDF reports retain geographic context when the live Amazon Location renderer is unavailable.
- Corrected Lido `GND  MILES` / `AIR  MILES` parsing when the labels contain variable whitespace.
- Changed the report banner to `REVIEW REQUIRED` whenever the deterministic result contains warnings, unknowns or manual-review gates.
- Added configurable departure and arrival NOTAM windows, with destination and alternate defaulting to ETA plus or minus two hours.
- Preserved the last completed reports when a rerun fails and made duplicate service requests idempotent.
- Moved support JSON behind a disclosure, added visible personal-note placement preview and made ATOT entry available before notes with offline capture.
- Labelled bundled MEL, communications and depressurisation matches as manual-review candidates instead of approved operational data.

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
