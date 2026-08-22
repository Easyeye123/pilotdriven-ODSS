# WSSS OpenStreetMap surface-geometry source

This proof of concept uses a bounded, one-time OpenStreetMap/Overpass snapshot for Singapore Changi Airport surface geometry. The official NOTAM remains the operational source; OSM only supplies candidate geometry.

## Bounded extraction

[Download the filtered WSSS airport-surface JSON snapshot](https://overpass-api.de/api/interpreter?data=%5Bout%3Ajson%5D%5Btimeout%3A90%5D%3B%0A%28%0A%20%20way%5B%22aeroway%22~%22%5E%28taxiway%7Ctaxilane%7Crunway%7Capron%29%24%22%5D%281.315%2C103.965%2C1.385%2C104.020%29%3B%0A%20%20node%5B%22aeroway%22~%22%5E%28holding_position%7Cparking_position%29%24%22%5D%281.315%2C103.965%2C1.385%2C104.020%29%3B%0A%29%3B%0Aout%20body%20geom%3B)

Bounding box, in south/west/north/east order used by Overpass QL:

```text
1.315,103.965,1.385,104.020
```

Included OSM objects:

- `aeroway=taxiway`
- `aeroway=taxilane`
- `aeroway=runway`
- `aeroway=apron`
- `aeroway=holding_position`
- `aeroway=parking_position`

## Attribution and limitations

- Data: © OpenStreetMap contributors, ODbL.
- Snapshot geometry is for briefing orientation only, not navigation.
- Before production use, compare the reference coverage against the current State aerodrome and ground-movement charts.
- Do not query public Overpass infrastructure for each user request; production should ingest and version controlled extracts.
