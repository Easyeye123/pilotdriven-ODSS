# ODSS surface map contract v1

## Purpose

`SURFACE_MAP_CONTRACT_V1` carries a flight-time-specific graphical airport-surface briefing from ODSS to PilotDriven. It is independent of the basemap provider and contains no API keys, session tokens or client-side aviation calculations.

## Example

```json
{
  "schema_version": "1.0",
  "airport": "WSSS",
  "briefing_time_utc": "2025-03-04T18:30:00Z",
  "geometry_source": {
    "provider": "openstreetmap-overpass",
    "dataset_timestamp": "2026-07-21T00:00:00Z",
    "airport_review_state": "proof-of-concept-unreviewed",
    "attribution": "© OpenStreetMap contributors",
    "licence": "ODbL-1.0"
  },
  "surface_geojson": {
    "type": "FeatureCollection",
    "features": []
  },
  "notam_overlays_geojson": {
    "type": "FeatureCollection",
    "features": []
  },
  "findings": [],
  "unmapped_items": [],
  "warnings": [],
  "not_for_navigation": true
}
```

## Surface features

Base features may contain:

```json
{
  "osm_id": 123,
  "aeroway": "taxiway",
  "ref": "P7",
  "surface": "concrete",
  "source": "openstreetmap",
  "not_for_navigation": true
}
```

## Overlay line properties

```json
{
  "notam_id": "A0783/25",
  "airport": "WSSS",
  "surface_type": "taxilane",
  "surface_ref": "R7",
  "operational_state": "closed",
  "applicability": "active",
  "affects_selected_aircraft": null,
  "match_method": "exact_ref_intersection_path",
  "match_confidence": "high",
  "effective_from": "2025-03-04T18:00:00Z",
  "effective_to": "2025-03-04T19:00:00Z",
  "source_osm_ids": [123456],
  "symbol": "surface-overlay-line",
  "display": true,
  "not_for_navigation": true
}
```

Point features use:

- `symbol=closure-x` for repeated closure crosses;
- `symbol=included-junction` for a specifically included junction.

## Endpoints in the proof of concept

```text
GET  /v1/airports/WSSS/surface-geometry
POST /v1/airports/WSSS/surface-resolve
```

Request body:

```json
{
  "notam_text": "A0783/25 NOTAMN ...",
  "briefing_time_utc": "2025-03-04T18:30:00Z",
  "aircraft_code": "F",
  "include_surface_geometry": true
}
```

## Required client behaviour

- render only features where `display=true` in the active briefing layer;
- retain inactive and unaffected findings in the detail/audit view;
- show confidence and match method;
- show attribution and `not for navigation`;
- provide one-click access to the original NOTAM;
- never infer or extend geometry in React;
- never hide an `unmapped_item` from the briefing completeness state.
