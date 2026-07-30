# Depressurisation Profile Chart Publication Gate

**Status:** Mandatory, fail closed  
**Effective:** 30 July 2026  
**Applies to:** PilotDriven/ODSS Level 1 and Level 2 briefing artifacts

## Governing rule

When ODSS proposes an approved depressurisation profile for a High Terrain Exposure event, the briefing must visibly include the applicable chart analysis.

A profile number, source chip, citation, hyperlink or textual description alone is **not** a compliant release.

- **Level 1:** include a compact, validated decision-support analysis chart showing actual CFP exposure separately from approved chart coverage.
- **Level 2:** include the complete authoritative source chart page, with a working internal or Helpyou link from the match matrix.
- **Unmatched exposure:** remain explicitly unresolved. Never substitute a nearby, generic or visually similar chart.

## Required verification

Each proposed profile artifact records:

```json
{
  "chart_number": "10-4",
  "source_document": "A350 Depressurization Profiles",
  "source_revision": "12 JUN 2026",
  "source_page": 269,
  "source_link": "helpyou://...",
  "route_airway_match_verified": true,
  "aircraft_effectivity_verified": true,
  "chart_image_validated": true,
  "level1_analysis_chart_embedded": true,
  "level2_full_source_chart_embedded": true
}
```

## Publication failure conditions

Release is blocked when any proposed chart:

- has no registered chart artifact;
- lacks source document, revision, page or source link;
- lacks route/airway verification;
- lacks aircraft-effectivity verification;
- has not passed image validation;
- is absent from the Level 1 analysis page; or
- is absent as a full authoritative chart page in Level 2.

The release gate is implemented by:

```text
pilotdriven_odss_dashboard/app/odss/profile_chart_gate.py
```

and is invoked before `reporting.render_pdf` publishes Level 1 or Level 2.

## Source and authority boundary

The controlled A350 profile PDF and extracted chart images remain in private, tenant-authorised storage. The public repository stores only the gate, metadata contract and regression tests. AI-generated drawings are not authoritative profile charts.
