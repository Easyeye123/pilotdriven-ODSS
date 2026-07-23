# SQ24 Sheveluch VAAC Case Study

**Status:** Historical regression case  
**Flight:** SQ24 · WSSS–KJFK · 22 July 2026  
**Volcano:** Sheveluch · 300270 · N5639 E16122  
**Purpose:** Preserve the operational-analysis lessons from the SQ24 volcanic-ash review.

This document is a historical test case. It is not a current volcanic-ash advisory.

## 1. Trigger

The uploaded LIDO weather package contained:

```text
Volcanic Ash SIGMETs:
No Wx data available
```

The correct interpretation was:

```text
source unavailable / coverage gap
```

It was not:

```text
no volcanic ash
```

## 2. Route sector

The filed north-Pacific/Alaska sequence included:

```text
AMOND
ELLES
CREMR
PUGGY
SELDM
HAMND
TED
GKN
ORT
63N140W
63N130W
62N120W
```

The review used CFP coordinates, ACTM/EET and the planned FL390/FL410 profile.

## 3. Advisory sequence lesson

The operational review required the latest responsible product, not the first product found.

For a Kamchatka eruption moving eastward, this meant checking:

- Tokyo VAAC products near the volcano and western North Pacific;
- Anchorage VAAC products as the cloud entered its responsibility area; and
- the receiving VAAC when responsibility transferred further east.

The Anchorage advisory identified by the user was:

```text
FVAK21 PAWU 220700
```

The review had to retain issue time, valid/forecast times, ash altitude, movement, polygons and next-advisory time.

## 4. Time-matched screening lesson

A static route-over-polygon image was insufficient.

The analysis had to determine:

1. aircraft position at each advisory forecast time;
2. official polygon valid at that time;
3. route/polygon intersection or closest approach;
4. nearest route segment and UTC;
5. planned level versus ash base/top; and
6. EDTO/diversion consequences.

The result under the reviewed advisory was not a filed-centreline penetration. Proximity near the HAMND–TED/GKN area remained operationally pertinent and therefore required the next update before the aircraft reached the sector.

## 5. PANC lesson

PANC could not be assessed only as a point outside the polygon.

The review also had to consider:

- the diversion route from the ETP/route;
- approach, missed-approach and holding area;
- forecast ash movement during the checked period;
- weather and runway/approach availability; and
- whether another suitable airport should receive greater planning priority.

## 6. Interpolation lesson

The aircraft reached the relevant area between official forecast times.

Linear interpolation between official forecast polygons was acceptable only as a screening estimate. The result had to be labelled as estimated and visually distinguished from official VAG geometry.

## 7. Vertical lesson

Planned flight level above the published ash top did not establish an acceptable route.

The report could state the numerical relationship, but it could not present vertical separation alone as the mitigation.

## 8. Wording lesson

Use:

```text
No direct intersection identified with the filed centreline.
Closest estimated proximity approximately ___ NM near ___ at ___Z.
```

Do not use:

```text
Unaffected.
Safe above ash.
```

## 9. Supersession and retrospective-use lesson

A later advisory issued after SQ24's planned passage was useful for audit and delayed-flight analysis.

It could not be used retrospectively as proof of the cloud's earlier position.

Every result must therefore retain:

- the advisory used;
- its issue time;
- the route reference time;
- whether the geometry was official or interpolated; and
- whether the result was recalculated for a delay or actual takeoff time.

## 10. Regression requirements

The SQ24 case should pass the following tests:

- `No Wx data available` produces `review_required` or equivalent unavailable state.
- A complete, current, non-intersecting advisory may produce `not_applicable`, but only for the checked route/time/level scope.
- A direct four-dimensional intersection produces `affected`.
- The output records closest route segment, UTC and lateral distance.
- The output records planned level and ash base/top.
- EDTO airports and diversion corridors are checked.
- Next-advisory time is promoted when it precedes the relevant sector.
- A later advisory does not overwrite the historical result without a new analysis version.
- ATOT or route changes force recalculation.
- Level 1 uses concise pilot wording; full methodology remains in audit data.
