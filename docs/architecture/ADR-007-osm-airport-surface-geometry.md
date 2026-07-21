# ADR-007 — Versioned OpenStreetMap airport-surface geometry for graphical NOTAMs

**Status:** Proof-of-concept accepted for WSSS  
**Scope:** Taxiway/taxilane/runway closure and restriction overlays  
**Depends on:** ADR-006 realistic map rendering  
**Operational authority:** The official NOTAM, current State AIP and approved charts remain controlling

## Context

PilotDriven and ODSS can already identify runway and taxiway references in ICAO NOTAM text, but the legacy WSSS registry is a deliberately simplified approximation. It cannot support professional, segment-accurate graphical closure overlays at airport scale.

OpenStreetMap contains detailed WSSS runways, taxiways, taxilanes, parking positions and holding positions. It can therefore supply candidate vector geometry while ODSS remains authoritative for NOTAM parsing, applicability, aircraft-code evaluation and confidence.

## Decision

1. Use a **bounded, versioned OSM extract** as the WSSS proof-of-concept geometry source.
2. The official NOTAM determines whether a surface is closed, restricted, shortened or unavailable.
3. ODSS resolves NOTAM references against a server-side airport-surface graph and emits a versioned `SURFACE_MAP_CONTRACT_V1`.
4. MapLibre renders only ODSS-provided GeoJSON. React does not parse NOTAMs or calculate affected segments.
5. A mapped overlay is promoted only when its resolution method and confidence meet the configured threshold.
6. Unresolved or ambiguous items remain text-only and keep the original NOTAM accessible.
7. Production must use controlled extracts or a managed provider. Public Overpass and public OSM tile servers are not queried per user request.
8. Every interactive map, static image and PDF displays `© OpenStreetMap contributors` and `not for navigation`.

## Surface resolution methods

- exact whole-surface reference;
- exact target surface between two intersecting surface references;
- stand-to-surface projection for `behind stand` wording;
- stand-range projection;
- included-junction markers;
- aircraft-code restriction applicability.

## Confidence states

| State | Meaning | Default display |
|---|---|---|
| `high` | Exact ref and unambiguous graph intersections | Solid red/amber line and X symbols |
| `medium` | Exact ref with more than one candidate, or low-error stand projection | Visible with confidence badge |
| `low` | Geometry resolved by a weak but bounded projection | Manual verification styling |
| `unmapped` | Missing ref, disconnected graph or excessive projection error | Text only; no X |

`mapped` describes the geometry match only. It does not certify the NOTAM, airport data or operational suitability.

## Data flow

```text
Official NOTAM + flight time + selected aircraft
    ↓
ODSS NOTAM parser and applicability engine
    ↓
Versioned WSSS OSM surface graph
    ↓
Deterministic segment resolver and confidence
    ↓
Surface-map contract / GeoJSON
    ├── MapLibre airport view
    ├── Playwright report capture
    └── text-only fallback
```

## Production promotion gate

An airport may be marked `chart-checked` only after:

1. taxiway and runway references are compared with the current State airport and ground-movement charts;
2. disconnected and duplicate OSM refs are reviewed;
3. parking-position coverage is measured;
4. regression NOTAMs for whole, intersection-range and stand-range closures pass;
5. OSM snapshot timestamp and object IDs are retained;
6. any material discrepancy is quarantined.

## Consequences

### Positive

- professional airport-scale closure graphics;
- broad open-data coverage;
- exact evidence and source IDs;
- same contract can drive dashboard and PDF;
- deterministic aviation logic remains in ODSS.

### Trade-offs

- OSM completeness and freshness vary;
- stand-based wording is inherently less certain than shared-node intersections;
- ODbL attribution and database-distribution obligations require governance;
- surface snapshots require scheduled ingestion and chart review.

## WSSS proof-of-concept acceptance

- fetch and version the bounded WSSS snapshot;
- resolve historical A0783/25 R7/R5 closures;
- draw red lines and repeated X symbols;
- preserve inactive findings but suppress them from the active overlay;
- evaluate an aircraft-code restriction;
- return text-only when a surface ref is absent;
- display source timestamp, confidence, original NOTAM and safety warning.
