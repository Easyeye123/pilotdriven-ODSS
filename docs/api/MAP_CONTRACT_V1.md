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
  "schema_version": "1.0",
  "provider": "aws-location",
  "style": "Hybrid",
  "route_hash": "<sha256>",
  "route_geojson": {},
  "markers_geojson": {},
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
