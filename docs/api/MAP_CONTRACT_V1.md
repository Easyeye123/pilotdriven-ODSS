# ODSS map contract v1

## Design goals

- stable between dashboard and PDF;
- independent of map provider;
- preserves source route order;
- carries operational significance without recalculating it in the frontend;
- contains no secrets;
- supports realistic, static and schematic renderers.

## Top-level fields

```json
{
  "schema_version": "1.1",
  "provider": "aws-location",
  "style": "Hybrid",
  "route_hash": "<sha256>",
  "route_geojson": {},
  "markers_geojson": {},
  "hazards_geojson": {},
  "bounds": {
    "west": 0,
    "south": 0,
    "east": 0,
    "north": 0
  },
  "priority_labels": [],
  "attribution": [],
  "warnings": [],
  "fallback": {
    "static_available": true,
    "schematic_available": true
  },
  "metadata": {}
}
```

## Route feature

The route is one `LineString` or `MultiLineString` feature.

```json
{
  "type": "Feature",
  "id": "planned-route",
  "geometry": {
    "type": "LineString",
    "coordinates": [[103.99, 1.36], [104.5, 3.0]]
  },
  "properties": {
    "flight_number": "SQ303",
    "departure": "EBBR",
    "destination": "WSSS",
    "not_for_navigation": true
  }
}
```

## Marker feature

```json
{
  "type": "Feature",
  "id": "wp-0042",
  "geometry": {
    "type": "Point",
    "coordinates": [67.45, 32.775]
  },
  "properties": {
    "name": "DUDEG",
    "source_name": "DUDEG",
    "role": "depressurisation_critical",
    "roles": ["depressurisation_critical"],
    "priority": 75,
    "actm_minutes": 354,
    "airway_in": "L750",
    "fir_boundary": null,
    "msa_hundreds_ft": 166,
    "vws": 1,
    "source_page": 11,
    "not_for_navigation": true
  }
}
```

## Hazard feature

`hazards_geojson` is an empty `FeatureCollection` unless ODSS has a verified
positive route/time/flight-level volcanic-ash intersection. It contains the
same source-derived geometry used by the dashboard and report renderers. A
`review_required` state is carried in analysis metadata and never invents a
polygon.

```json
{
  "type": "Feature",
  "id": "RJJJ-A1-1784700000",
  "geometry": {
    "type": "Polygon",
    "coordinates": [[[140.0, 40.0], [145.0, 40.0], [145.0, 45.0], [140.0, 40.0]]]
  },
  "properties": {
    "hazard": "volcanic_ash",
    "valid_from_utc": "2026-07-22T04:00:00+00:00",
    "valid_to_utc": "2026-07-22T10:00:00+00:00",
    "lower_flight_level": 0,
    "upper_flight_level": 350,
    "not_for_navigation": true
  }
}
```

## Route hash

The hash is SHA-256 over a canonical list containing:

- normalized waypoint name;
- longitude;
- latitude;
- ACTM.

It must not include:

- generated time;
- API key;
- selected map provider;
- visual colour;
- user-interface state.

This lets PilotDriven verify that dashboard and report images represent the same route.

## Security

The map contract must never contain:

- AWS API key;
- S3 credentials;
- user/session token;
- internal filesystem path;
- proprietary source PDF text beyond necessary evidence identifiers.
