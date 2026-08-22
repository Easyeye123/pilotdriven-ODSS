# PilotDriven / ODSS Briefing Publication Protocol v1.2

**Effective:** 28 July 2026  
**Status:** Mandatory for ODSS report manifests and generated Level 1, Level 2 and Level 3 briefing artifacts  
**Minimum visual standard:** SQ24 professional briefing standard  
**Accepted current baseline:** SQ23 Level 1 and Level 2 authoritative-source-first package with enlarged detailed text and vertically centred table cells

## 1. Foundational principle

> PilotDriven does not ask the pilot to trust AI. It asks the pilot to trust the authoritative source. AI identifies, organises and connects relevant evidence so the pilot can make an informed operational decision.

ODSS remains authoritative for deterministic aviation calculations. Helpyou retrieves controlled source material. PilotDriven presents the findings and source links. Neither the LLM nor the browser may replace a missing controlling source with model knowledge.

## 2. Report hierarchy

### Level 1 - Pertinent Brief

- Maximum three A4 landscape pages.
- Flight-specific triggers, timing, margins, exposure and operational consequence only.
- No policy dump, methodology explanation, generic reminder or repeated evidence.

### Level 2 - Operational Evidence Brief

- Deterministic finding.
- Authoritative source evidence.
- Calculation and applicability.
- Missing data or uncertainty.
- Promotion criteria for a policy-aware decision review.

### Level 3 - Decision Brief

- Applicable controlling policy.
- Exact source reference and actual paragraph.
- Live link to the controlled source location.
- Decision frame, margin and unresolved inputs.
- No system verdict; the pilot remains the decision maker.

## 3. Authoritative-source contract

Every operational claim must carry at least one approved source record:

```json
{
  "source_id": "SRC-OM-EDTO-01",
  "authority_class": "company_manual",
  "source_mode": "direct_extract",
  "document_title": "Operations Manual",
  "revision": "Rev 32",
  "reference": "12.3.5(2)",
  "page": "12.18",
  "paragraph_text": "Actual applicable paragraph...",
  "live_link": "helpyou://document/.../page/12.18"
}
```

Approved source classes are:

- company manual;
- licensed manual;
- official regulator;
- official AIP;
- official NOTAM;
- official weather product;
- operational flight plan; and
- approved company bulletin.

AI-generated text is not a source. Derived reasoning must be labelled `AI synthesis` and identify all supporting authoritative source IDs.

A failed or missing link, revision, page, paragraph or effectivity match leaves the item unresolved.

## 4. Flight identity and time-header contract

Level 1 and Level 2 Page 1 title headers must contain:

- flight number;
- route;
- month and year;
- aircraft type;
- registration;
- scheduled departure UTC;
- scheduled arrival UTC;
- block time;
- departure local time and UTC offset; and
- arrival local time and UTC offset.

Aircraft type and registration must remain visible on every report page.

Block time is:

```text
scheduled arrival - scheduled departure
```

It is not airborne time or CFP EET.

## 5. Publication profile

- A4 landscape.
- Detailed operational text at least 2 points larger than the superseded compact baseline.
- Normal table body text: minimum 7 pt.
- Normal card detail text: minimum 7 pt.
- Table headings and body text: vertical alignment `middle`.
- Row height: content-aware.
- Top and bottom cell padding: balanced.
- Text overflow/clipping: publication failure.
- Duplicate text/table overlays: prohibited.
- Source-navigation strip must not cover the final data row.

The renderer centres the complete wrapped text block using the cell bounds and font metrics. It must not use a bottom baseline offset that leaves wording at the base of the cell.

## 6. High Terrain Exposure

The automatic Level 1/2 trigger is MSA **strictly greater than `100*`**.

An MSA of exactly `100*` is the threshold boundary and is not itself a qualifying `>100*` event.

For each qualifying event, ODSS records:

- first waypoint above threshold;
- first subsequent waypoint at or below threshold;
- ACTM start/end and duration;
- scheduled-departure-anchored UTC estimate;
- maximum MSA and waypoint;
- approved depressurisation profile; and
- coverage or unresolved status.

Isolated events remain separate. Do not merge events across a waypoint at or below the threshold. Do not create a continuous mountain profile from discrete CFP MSA values.

## 7. Manifest fields

A release candidate must include:

```json
{
  "header": {
    "flightNumber": "SQ23",
    "route": "KJFK-WSSS",
    "monthYear": "JUL 2026",
    "aircraftType": "A350-941",
    "registration": "9V-SGE",
    "scheduledDepartureUtc": "0215Z",
    "scheduledArrivalUtc": "2130Z",
    "blockTime": "19:15",
    "blockTimeBasis": "scheduled_arrival_minus_scheduled_departure",
    "departureLocalTime": "24 JUL 2215",
    "departureUtcOffset": "UTC-4",
    "arrivalLocalTime": "26 JUL 0530",
    "arrivalUtcOffset": "UTC+8",
    "aircraftIdentityRepeatedOnEveryPage": true
  },
  "publicationProfile": {
    "pageFormat": "A4 landscape",
    "detailFontIncrementPt": 2,
    "minimumTableBodyFontSizePt": 7,
    "minimumCardDetailFontSizePt": 7,
    "tableCellVerticalAlignment": "middle",
    "tableRowHeightPolicy": "content-aware",
    "cellPaddingPolicy": "balanced",
    "textOverflowPolicy": "fail"
  }
}
```

## 8. Release gate

The following must be recorded as `pass` before publication:

- spacing;
- hierarchy;
- alignment;
- readability;
- typography;
- table-cell alignment;
- text clipping;
- header identity;
- graphic accuracy;
- duplication; and
- source-link integrity.

The PDF must be rendered and visually checked at operational viewing size. A valid data result with a crushed, clipped or misaligned presentation is not a valid release.

## 9. Responsibility boundary

ODSS owns:

- deterministic findings;
- timing and margin calculations;
- source IDs and applicability;
- high-terrain segmentation;
- report manifest; and
- generated report content.

PilotDriven owns:

- user-facing navigation;
- responsive document presentation;
- live-link handling;
- source navigator; and
- commercial deployment.

React or browser code must not recalculate aviation findings.

## 10. Regression requirements

Add or retain regression tests for:

- Level 1 maximum of three pages;
- aircraft type, registration and month/year in the title header;
- type and registration on every page;
- correct block-time basis;
- local times with UTC offsets;
- minimum detailed font sizes;
- vertical middle alignment in all table cells;
- content-aware row height and balanced padding;
- no clipped text or duplicate overlays;
- live source links resolving to the intended paragraph/page;
- no AI source authority;
- High Terrain Exposure strictly greater than `100*`; and
- isolated MSA events separated after a threshold break.

No user CFP, generated operational report, company manual or proprietary source content is committed with this protocol.
