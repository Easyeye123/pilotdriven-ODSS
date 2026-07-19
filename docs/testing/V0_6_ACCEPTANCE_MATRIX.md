# ODSS v0.6 acceptance matrix

## Functional

| Test | Expected |
|---|---|
| SQ303 route order | Matches EBBR–WSSS CFP order |
| SQ304 route order | Matches WSSS–EBBR CFP order |
| Route hash rerun | Stable for unchanged route |
| Route change | Produces a new hash |
| Dashboard/PDF | Same hash and label candidates |
| ATOT update | UTC changes, ACTM does not |
| Waypoint ATA | Derived ATOT and route UTC are correct |
| BOBCAT | Marker and timing remain visible |
| MSA/VWS | Only grouped events and critical markers |
| No key | Explicit fallback, no blank map |
| Static failure | Schematic label shown |
| Cross-flight isolation | No route/finding carryover |

## Visual

- realistic satellite/labelled basemap;
- departure/destination correctly positioned;
- map at least half Page 1 usable area;
- no substantial empty regions;
- no clipped panels;
- PZFW, PLDW, PTOW visible;
- priority labels readable;
- attribution visible;
- `not for navigation` visible;
- Page 1 links reach correct destinations;
- tablet and desktop layouts remain usable.

## Security

- key absent from analysis JSON;
- key absent from logs and PDF metadata;
- authorized analysis access required;
- print endpoint not public;
- output path isolated by tenant;
- source PDF not embedded in handoff artifacts.

## Performance targets

Initial development targets:

| Operation | Target |
|---|---:|
| map-contract build | < 250 ms |
| interactive map first useful render | < 5 s on normal broadband |
| Playwright capture | < 20 s |
| static fallback | < 10 s |
| report generation with primary map | < 45 s |

These are engineering targets, not operational guarantees.
