# PilotDriven/ODSS — Controlled CDL and Depressurisation Reference Protocol

## Status

Standing implementation and briefing protocol.

## Controlled documents

ODSS uses the following operator-controlled A350 sources when their private structured indexes are mounted:

| Source | Issue | Runtime variable |
|---|---|---|
| SIA A350 Fleet Configuration Deviation List | 05 May 2026 | `ODSS_CDL_INDEX_PATH` |
| A350 Depressurization Profiles | 12 June 2026 | `ODSS_DEPRESS_PROFILE_INDEX_PATH` |

The proprietary PDFs and complete extracted indexes must remain in PilotDriven-controlled private storage. They must not be committed to the public repository, returned to unauthorised tenants, or sent to an external model.

## Responsibility boundary

ODSS owns:

- parsing Page 1 MEL/CDL/CDDL declarations;
- resolving the exact controlled reference;
- registration and aircraft-series effectivity;
- dispatch conditions and combination limitations;
- published take-off/approach, enroute and fuel penalties;
- detection of high-MSA events;
- route, airway, direction and aircraft-effectivity matching;
- proposed depressurisation-profile coverage;
- source metadata and report findings.

PilotDriven owns authentication, tenant access, private-document storage, navigation, source expansion and presentation. React must not reproduce the deterministic matching or penalty calculations.

## CFP Page 1 CDL workflow

1. Read the deferred-item block in the upper portion of CFP Page 1.
2. Recognise Lido entries prefixed `AA`, `BB`, `CC`, `DD` or `EE`, followed by `MEL`, `CDL` or `CDDL` and the reference.
3. Preserve the complete Page 1 description and company remark.
4. For `CDL`, find the reference in the current controlled CDL index.
5. Resolve the variant against the aircraft registration before presenting the result.
6. Return:
   - item reference and title;
   - quantity installed and the stated missing condition when available;
   - dispatch conditions;
   - limitations and prohibited combinations;
   - maintenance and MEL interfaces;
   - take-off/approach, enroute and fuel penalties;
   - controlled-document issue and source page.
7. If the reference exists but has no applicable variant for the registration, show an effectivity conflict rather than selecting a generic entry.
8. If the private index is not mounted, show `controlled source not mounted`; do not substitute a model-generated answer.
9. Keep CDDL separate. Do not treat the CDL manual as authority for a CDDL item.

### Performance rules

- Use OCTO/AFM performance where the approved workflow provides a more accurate result.
- If OCTO has no data for the item, use the penalty published in the controlled CDL.
- Published penalties are cumulative unless the CDL gives a specific combination penalty.
- Apply each penalty to the corresponding most-limiting take-off/approach, enroute or landing weight.
- Carry a published fuel-consumption increase into the appropriate flight-planning/FMS fuel-penalty workflow.
- Compare performance with and without the missing item and use the more limiting result.
- Never infer the number or extent of missing components from the reference alone when Page 1 or the technical status does not state it.

## High-MSA and depressurisation workflow

### Trigger

A waypoint belongs to a high-MSA event when:

- the CFP marks its MSA with an asterisk; or
- the parsed MSA is strictly greater than 100 hundreds of feet.

An asterisk is the primary Lido signal. `100*` must not be discarded merely because its numeric value equals 10,000 ft.

### Event boundaries

For each continuous event:

1. The waypoint immediately preceding the first starred/high-MSA waypoint is the event commencement context.
2. The final starred/high-MSA waypoint is the event end.
3. Retain the first, last and maximum-MSA waypoint, ACTM and coordinates.
4. Do not merge separated high-MSA regions merely because they occur in the same FIR.

### Profile matching

For every event:

1. Search the complete current profile index, not a short hard-coded candidate list.
2. Match profile endpoint aliases against the actual CFP route order.
3. Match the published airway sequence, including `DCT`, in the flown direction.
4. Verify registration-series/aircraft effectivity (`ULR`, `LH`, `MH` or `ALL`).
5. Require profile coverage of the event commencement leg and the high-MSA route legs.
6. Select a minimal, contiguous profile chain that covers the event.
7. Suppress a nested profile when it adds no uncovered route leg, but retain it in audit metadata as an exact subprofile where useful.
8. Where two profiles sharing a critical point are needed, present both in route order.
9. If coverage is incomplete, state the uncovered route leg and require manual chart-index review.

### Pilot-facing result

For each selected profile show only:

- profile number;
- route segment and airway sequence;
- applicable ACTM interval;
- maximum MSA and waypoint;
- critical point and ACTM when present;
- profile issue/effective date;
- any urgent route-specific action.

Keep chart body text, complete provenance and matching diagnostics in expandable detail or the audit record.

## SQ24 regression case

For the filed WSSS–KJFK route using A350-941 registration 9V-SGE, the starred MSA sequence begins at TED after the preceding waypoint HAMND and continues through GKN, ORT, 63N30 and 62N20.

The minimal applicable profile chain is:

1. **11-4 — HAMND to TED, DCT; CP HAMND.** Covers the commencement leg into the starred-MSA region.
2. **11-37 — TED to 62N20, J511/J124/DCT; CP ORT.** Covers the continuous high-MSA route through the Canadian entry sector.

Profile **11-3 — 63N140W to 62N120W, DCT; CP 63N140W** is an exact nested subprofile within the latter portion. It may remain in audit detail, but it must not be added to the primary brief when 11-37 already covers the same route legs.

The SQ24 CFP used for this regression contains no Page 1 CDL declaration. Therefore, its valid result is `no CDL item parsed`, not `CDL reviewed with no penalty`.

## Regression requirements

Automated tests must cover:

- Page 1 `AA CDL <reference>` parsing;
- exact registration effectivity;
- effectivity conflict handling;
- controlled-index-not-mounted handling;
- structured CDL penalties and source pages;
- asterisk-driven MSA detection at `100*`;
- route direction and airway sequence;
- a two-profile chain sharing a boundary/critical context;
- nested-profile suppression;
- SQ24 selection of 11-4 and 11-37 only;
- a high-MSA event with no complete profile coverage.
