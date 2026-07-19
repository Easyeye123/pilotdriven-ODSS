# ADR-006 — ODSS v0.6 realistic map and PDF capture architecture

**Status:** Accepted reference architecture  
**Decision:** Amazon Location Service Hybrid + MapLibre GL JS + Playwright map capture  
**Baseline:** ODSS v0.5 schematic renderer retained as a labelled fallback  
**Target:** Integration into the wider PilotDriven application without rewriting deterministic aviation logic

## Context

ODSS v0.5 proves that the Lido route can be parsed, normalised and plotted from waypoint coordinates. Its schematic renderer is useful offline but does not meet the agreed realistic PilotDriven visual standard.

A single canonical route and briefing model must drive:

- the current FastAPI dashboard;
- the Level 1 visual brief;
- the Level 2 visual cover;
- the future PilotDriven frontend; and
- every fallback renderer.

## Decision

1. **Amazon Location Service Hybrid** is the primary realistic basemap.
2. **MapLibre GL JS** renders the dashboard route, markers and labels.
3. **Playwright** captures the same print-map page for the PDF.
4. **Amazon Location GetStaticMap** is the first fallback, using Satellite or Standard because Hybrid is dynamic-only.
5. The existing **schematic renderer** is the final offline fallback.
6. Every downgrade is explicitly labelled; a blank map or silent substitution is not permitted.
7. The map is for briefing orientation only and is not for navigation.

## Why this design

- Amazon Location Maps V2 supplies MapLibre-compatible style descriptors.
- Hybrid combines satellite imagery with geographic labels.
- MapLibre renders GeoJSON route and marker layers without moving operational logic into the frontend.
- Playwright can capture the exact map element used in the dashboard.
- Static and schematic fallback modes keep report generation resilient.

## Consequences

### Positive

- Dashboard and PDF can use the same route hash, map bounds, labels and style.
- The PilotDriven frontend can replace the current Jinja UI while consuming the same contract.
- AWS deployment and secrets management remain straightforward.
- Operational logic stays server-side and auditable.

### Trade-offs

- Playwright introduces a browser runtime in the report worker.
- Hybrid map rendering requires network access to Amazon Location.
- API-key and origin restrictions require careful configuration.
- Map capture must wait for an explicit ready signal to avoid incomplete tiles or labels.

## References

- Amazon Location maps: https://docs.aws.amazon.com/location/latest/developerguide/maps.html
- AWS map styles: https://docs.aws.amazon.com/location/latest/developerguide/map-styles.html
- AWS API-key authentication: https://docs.aws.amazon.com/location/latest/developerguide/using-apikeys.html
- GetStaticMap: https://docs.aws.amazon.com/location/latest/APIReference/API_geomaps_GetStaticMap.html
- MapLibre GL JS: https://maplibre.org/maplibre-gl-js/docs/
- Playwright screenshots: https://playwright.dev/python/docs/screenshots
