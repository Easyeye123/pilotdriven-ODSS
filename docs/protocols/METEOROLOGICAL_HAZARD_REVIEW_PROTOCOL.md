# PilotDriven Meteorological Hazard Review Protocol

**Status:** Standing companion protocol  
**Version:** 1.0  
**Effective:** 23 July 2026  
**Applies to:** ODSS and PilotDriven CFP analysis, pertinent briefs, dashboard alert cards, route-map overlays, EDTO review, airport briefing, notifications and report generation.  
**Read with:** `PERTINENT_BRIEF_EDITORIAL_AND_VAAC_PROTOCOL.md`

## 1. Purpose

This protocol adds a structured review of authoritative meteorological information outside the uploaded CFP package when that additional material can change the operational interpretation of the flight.

The objective is not to reproduce a general weather briefing. ODSS must explain how a time-specific meteorological hazard affects:

- the filed route and planned flight levels;
- departure runway, taxi, takeoff and climb;
- destination runway, approach, landing and taxi-in;
- destination and enroute alternates;
- EDTO airport suitability and diversion corridors; and
- any action or update time that is operationally pertinent.

The output is written for a trained pilot. It must state the mechanism of impact, the relevant UTC window and the affected phase of flight. It must not fill the brief with weather theory or generic reminders.

---

## 2. Authority and responsibility boundary

### 2.1 Source authority

The operational weather source remains the applicable official OPMET, SIGMET/AIRMET, tropical-cyclone advisory, significant-weather product, State meteorological authority product, dispatch package and company procedure.

Public official websites such as NOAA/NWS, the NOAA Aviation Weather Center, the National Hurricane Center, JMA/RSMC Tokyo, the Australian Bureau of Meteorology, the UK Met Office, Environment and Climate Change Canada and comparable national meteorological services may be used to retrieve or supplement authoritative products.

A public web page is not automatically controlling merely because it is official. ODSS must identify:

- the issuing authority;
- product type;
- issue UTC;
- validity period;
- forecast valid time;
- geographic area;
- vertical extent where applicable;
- update or next-advisory time; and
- whether the product is operational, experimental or explanatory.

Experimental products may support awareness but must not silently replace an operational product.

### 2.2 ODSS ownership

ODSS remains authoritative for:

- parsing the CFP route, coordinates, ACTM/EET and flight-level profile;
- retrieving and normalising weather products;
- selecting the responsible meteorological authority;
- matching each product to the route and airport operating windows;
- geospatial intersection and proximity calculations;
- airport, EDTO and diversion applicability;
- source currency and supersession;
- confidence and severity classification; and
- report generation.

PilotDriven owns presentation, navigation, source expansion, tenant context, notifications and delivery.

React and other presentation components must not independently calculate route-weather intersections, tropical-cyclone proximity, front timing, icing exposure or EDTO weather suitability.

---

## 3. Trigger conditions

### 3.1 Routine supplemental review

Run a supplemental authoritative-source weather review for:

- departure, destination and destination alternates;
- each EDTO airport during its checked period;
- any route sector containing a SIGMET, AIRMET or significant-weather feature;
- any airport or route sector for which the CFP weather coverage is incomplete, stale or unavailable; and
- any hazard flagged by dispatch, company guidance, NOTAM, the pilot or another official source.

### 3.2 Enhanced hazard review

Run an enhanced review when any of the following is present or forecast near the flight:

- tropical cyclone, typhoon, hurricane, tropical storm or tropical depression;
- cold front, warm front, occlusion, trough or rapidly deepening low;
- severe or embedded convection, squall line or mesoscale convective system;
- snowstorm, blizzard, freezing rain, freezing drizzle or significant snow accumulation;
- moderate or severe icing;
- moderate, severe or extreme turbulence, mountain wave or significant jet-stream shear;
- low-level wind shear or microburst risk;
- widespread fog, very low ceiling or reduced visibility;
- dust storm, sandstorm, smoke or widespread haze;
- extreme surface wind or crosswind risk;
- flooding, storm surge or weather-related airport closure; or
- a significant discrepancy between the CFP weather package and a newer official product.

A missing product is a data-availability condition. It is not evidence that the hazard is absent.

---

## 4. Source hierarchy

Use the most current applicable information in this order:

1. **Operational aviation products in the CFP or dispatch package**
   - METAR/SPECI;
   - TAF and amendments;
   - SIGMET, Convective SIGMET and AIRMET/G-AIRMET;
   - tropical-cyclone SIGMET;
   - WAFS/SIGWX and approved route wind/temperature data;
   - aerodrome warning, wind-shear warning and State operational products.
2. **Responsible national or regional meteorological authority**
   - NOAA/NWS Aviation Weather Center and Alaska Aviation Weather Unit;
   - NOAA National Hurricane Center or Central Pacific Hurricane Center;
   - JMA/RSMC Tokyo Typhoon Center;
   - Australian Bureau of Meteorology and relevant Tropical Cyclone Warning Centre;
   - UK Met Office, Environment and Climate Change Canada or comparable responsible service.
3. **Official radar, satellite, lightning, surface analysis, prognostic and model guidance** issued or hosted by the responsible authority.
4. **Company dispatch, flight operations and meteorological guidance.**
5. **Secondary technical explanation or LLM synthesis**, clearly separated and never allowed to override the authoritative products.

Always check whether a later METAR, SPECI, TAF amendment, SIGMET, advisory or forecast cycle supersedes the product already reviewed.

---

## 5. Product selection by hazard

### 5.1 Tropical cyclone / typhoon / tropical storm

Review, as available:

- tropical-cyclone advisory and forecast/advisory;
- current and forecast centre positions;
- direction and speed of movement;
- central pressure and intensity;
- 34-, 50- and 64-knot wind radii or the equivalent regional wind areas;
- forecast probability circle or cone;
- tropical-cyclone SIGMET;
- radar, satellite and lightning presentation;
- associated convection, precipitation and outer rainbands;
- airport warnings, storm-surge or flooding information where operationally relevant; and
- next-advisory time.

Do not treat the forecast cone or probability circle as the size of the storm or as the complete hazard envelope. Wind radii, convection, SIGMET geometry and uncertainty must be assessed separately.

Record the wind averaging basis when comparing products. For example, one authority may publish one-minute sustained winds while another uses ten-minute sustained winds. Do not compare the numerical intensity directly without identifying the basis.

### 5.2 Fronts, troughs and synoptic systems

Review:

- current surface analysis and forecast/prognostic charts;
- expected frontal position at the flight-relevant UTC;
- pressure tendency and movement;
- wind shift, gusts and likely runway change;
- embedded or frontal convection;
- turbulence and jet-stream relationship;
- freezing level and icing layers;
- precipitation type and intensity;
- visibility and ceiling trend; and
- SIGMET/AIRMET coverage.

A front must not be described as operationally significant without stating the expected effect. Examples include a crosswind increase, thunderstorm line, freezing rain, low-level wind shear, turbulence or destination runway change.

### 5.3 Snow, ice and winter storms

Review:

- METAR/SPECI and TAF precipitation type and intensity;
- snowfall rate and accumulation forecast;
- freezing rain or freezing drizzle;
- freezing level and temperature profile;
- icing SIGMET/AIRMET and approved icing guidance;
- wind, drifting or blowing snow;
- runway condition, SNOWTAM/FICON or equivalent surface report;
- braking-action information when published;
- runway/taxiway closure and snow-removal NOTAMs;
- deicing capacity or delay information where officially available; and
- alternate and EDTO airport conditions during the checked window.

Do not infer actual runway contamination or braking action solely from a forecast. Distinguish forecast weather from observed surface condition.

### 5.4 Convective weather

Review:

- SIGMET or Convective SIGMET;
- official radar, satellite and lightning trend;
- forecast movement and development;
- cloud tops and vertical extent;
- embedded, severe or line characteristics;
- associated hail, severe turbulence, icing, wind shear and heavy precipitation;
- route intersection and available lateral options;
- departure/arrival flow impact; and
- update time.

Radar is an observation, not a long-range forecast. Do not project a radar image beyond a reasonable nowcasting period without a forecast product.

### 5.5 Icing and turbulence

Review:

- SIGMET/AIRMET/G-AIRMET;
- WAFS or approved global grids;
- official icing and turbulence guidance;
- PIREP/AIREP evidence;
- freezing level;
- planned flight level and climb/descent exposure;
- holding, approach and diversion exposure; and
- mountain-wave or jet-stream context.

The report must identify the route segment, UTC, level band and expected duration. Avoid general statements such as “icing on route” without phase and altitude context.

### 5.6 Low visibility, fog, wind and wind shear

Review:

- current METAR/SPECI;
- TAF and amendments;
- aerodrome and wind-shear warnings;
- runway-specific wind where available;
- ceiling, visibility, RVR trend and approach minima relationship;
- crosswind, tailwind and gust components;
- low-level wind shear or microburst risk;
- likely runway configuration change; and
- alternate trend.

---

## 6. Route and time matching

Every hazard review must use the actual CFP:

- waypoint sequence;
- latitude and longitude;
- ACTM/EET;
- planned flight level;
- departure and arrival UTC;
- EDTO entry, ETP and exit times; and
- airport checked periods.

For each relevant forecast valid time:

1. determine the aircraft position or airport operating window;
2. use the official hazard geometry, grid or forecast field valid for that time;
3. calculate route intersection or minimum lateral distance where geometry is available;
4. compare the planned level with the hazard vertical extent;
5. identify the nearest waypoint or route segment and UTC;
6. evaluate movement relative to the aircraft and route;
7. repeat for departure, destination, alternates and EDTO airports; and
8. record the next update that occurs before the flight reaches the sector.

A static chart must not be compared with the entire route without time matching.

Interpolation between official forecast periods may be used for screening only. The output must identify it as an ODSS screening estimate and must not display the interpolated result as an official forecast polygon.

---

## 7. Operational impact model

### 7.1 Departure

State only the effects relevant to departure, such as:

- runway availability or likely runway change;
- crosswind, tailwind or gust exposure;
- thunderstorm, lightning, microburst or wind-shear risk;
- ceiling/visibility and departure-minima relationship;
- snow, freezing precipitation, deicing or contamination;
- taxi restrictions or weather-related airport closure;
- expected delay, flow restriction or slot risk when officially supported; and
- the first route hazard after departure.

### 7.2 Enroute

State:

- route intersection, proximity or non-intersection;
- affected waypoint/segment and UTC;
- vertical extent versus planned level;
- expected duration along route;
- movement relative to the aircraft;
- turbulence, icing, convection or precipitation mechanism;
- potential reroute or level-change consequence when supported by dispatch/ATC information; and
- EDTO/diversion implications.

### 7.3 Destination

State:

- hazard during the ETA-centred operating window;
- runway and approach consequence;
- crosswind/tailwind or wind-shift risk;
- thunderstorm, wind-shear or low-visibility risk;
- snow, ice, freezing precipitation or runway-condition consequence;
- likely arrival-flow or holding exposure when supported;
- destination alternate relationship; and
- next forecast or observation update before arrival.

### 7.4 Alternates and EDTO airports

For each relevant airport, assess:

- checked or required operating window;
- observed and forecast weather;
- runway, approach and minima relationship;
- weather hazard on the diversion corridor;
- snow/ice, contamination or deicing implications;
- tropical-cyclone wind field or frontal timing;
- whether a later product is due before the airport may be required; and
- whether another airport should receive greater operational attention.

An airport outside a hazard polygon may remain pertinent because the diversion route, approach area, wind field or forecast uncertainty affects it.

---

## 8. Hazard-specific pilot wording

The pertinent brief must explain **how** the weather affects the flight.

Preferred examples:

- **Tropical cyclone:** “Forecast 34-kt wind field remains south of the filed route at 1430Z; outer convective bands may affect RPLL and the departure alternate corridor. Recheck the 1200Z advisory before entering the sector.”
- **Cold front:** “Front forecast across KJFK 2130–2330Z, overlapping ETA. Wind veers from southerly to westerly with gusts, with TSRA probability and likely runway configuration change.”
- **Winter storm:** “Freezing precipitation and snow overlap the destination window. Runway contamination is not confirmed by forecast alone; monitor current field condition, braking-action and snow-removal status.”
- **Icing:** “Moderate icing forecast in cloud FL080–FL180 during descent to the alternate; no cruise-level exposure identified.”
- **Convection:** “Filed centreline intersects the eastward-moving SIGMET polygon near ABC–DEF at 1640Z, tops FL450. Route and level review required before sector entry.”

Avoid:

- “bad weather expected”;
- “typhoon may affect the route” without time, location and mechanism;
- “airport affected by snow” without distinguishing forecast from observed condition;
- “front on route” without explaining wind, convection, turbulence, icing or precipitation impact; and
- “safe” or “unaffected” when only non-intersection has been established.

---

## 9. Pilot-facing weather card

A concise hazard card should contain only:

- hazard name/type;
- issuing authority and product identifier;
- issue UTC and forecast valid time;
- affected phase, airport or route segment;
- route intersection/proximity and vertical relationship;
- departure, destination, alternate or EDTO consequence;
- operational significance; and
- next update or required action.

Detailed charts, model comparison, source hierarchy and methodology belong in expandable detail, the dashboard inspector or the audit report.

Use the existing category colour system:

- amber for weather hazard or uncertainty;
- red only for a direct critical conflict or unavailable margin;
- departure blue and destination violet remain the airport category colours even when weather is discussed inside those airport panels.

---

## 10. Tropical-cyclone review checklist

For every relevant tropical cyclone, record:

- storm name/number and basin;
- issuing RSMC/TCWC/NHC;
- advisory identifier and issue UTC;
- centre position and position confidence;
- movement and speed;
- intensity and wind averaging basis;
- wind radii or regional wind areas;
- forecast positions and uncertainty area;
- SIGMET geometry and vertical extent;
- route closest approach, segment and UTC;
- departure/destination/alternate effects;
- EDTO airport and diversion-corridor effects;
- forecast update time; and
- any official warning, airport closure or flow restriction.

The cone or probability circle is not the storm boundary. The pilot summary must not imply that locations outside the cone are unaffected.

---

## 11. Front and winter-weather checklist

For a relevant front, low or winter storm, record:

- analysis/forecast chart issue and valid UTC;
- expected frontal or low-centre position at route/airport time;
- wind shift, gusts and pressure tendency;
- convection and precipitation type;
- freezing level and icing layer;
- turbulence or jet relationship;
- airport ceiling/visibility trend;
- snow/freezing-rain timing;
- observed runway condition and closure status when available;
- departure and destination runway consequence;
- alternate and EDTO consequence; and
- next product update.

---

## 12. Data contract

The weather engine should produce a versioned structured record similar to:

```json
{
  "hazard_type": "tropical_cyclone",
  "authority": "JMA_RSMC_TOKYO",
  "product_type": "tropical_cyclone_advisory",
  "product_id": "...",
  "issued_at_utc": "...",
  "valid_from_utc": "...",
  "valid_to_utc": "...",
  "next_update_utc": "...",
  "geometry": {},
  "vertical_extent": {},
  "movement": {},
  "route_intersection": false,
  "closest_route_segment": "...",
  "closest_time_utc": "...",
  "closest_distance_nm": 0,
  "departure_effect": [],
  "destination_effect": [],
  "alternate_effects": [],
  "edto_effects": [],
  "severity": "advisory",
  "confidence": "official",
  "screening_estimate": false,
  "evidence": []
}
```

The renderer consumes this record. It does not recreate the weather analysis.

---

## 13. Prohibited anti-patterns

Do not:

- rely on an LLM summary when the official product is available;
- use a stale advisory without checking for a later cycle;
- treat a forecast cone as the storm size;
- compare one-minute and ten-minute sustained winds without qualification;
- project a radar image as a long-range forecast;
- infer airport closure, runway contamination or braking action from weather forecast alone;
- compare a static chart with the entire route without UTC matching;
- assess only the filed centreline and ignore airports or diversion corridors;
- state that a front, typhoon or winter storm “affects” the flight without explaining how;
- display superseded forecasts alongside the current conclusion in the pilot summary;
- use red for a routine weather caution; or
- crowd the pertinent brief with general meteorological explanation.

---

## 14. Automated QA and acceptance checks

Every enhanced weather review must pass:

1. **Authority:** responsible issuing authority and product type identified.
2. **Currency:** latest available cycle checked; superseded products removed from the pilot summary.
3. **Timing:** route and airport assessment matched to forecast valid UTC.
4. **Route fidelity:** actual CFP coordinates, ACTM/EET and planned levels used.
5. **Airport windows:** departure, ETA, alternate and EDTO periods assessed separately.
6. **Mechanism:** operational effect stated, not merely the hazard name.
7. **Vertical context:** route level compared with the hazard layer where applicable.
8. **Geometry:** official geometry distinguished from ODSS screening interpolation.
9. **Tropical cyclone:** cone/probability area not treated as storm boundary; wind radii assessed.
10. **Measurement basis:** sustained-wind averaging period retained where relevant.
11. **Winter weather:** forecast conditions distinguished from observed runway condition.
12. **Update action:** next advisory/forecast time displayed when it precedes sector or airport use.
13. **EDTO:** applicable airports and diversion paths assessed.
14. **Editorial fit:** concise pilot wording with no unnecessary theory or routine reminders.
15. **Audit preservation:** source text, charts, timestamps and calculations retained outside the main reading flow.

Visual and operational regression fixtures should include:

- tropical cyclone near but not intersecting the route;
- direct tropical-cyclone wind-field or SIGMET intersection;
- destination frontal passage at ETA;
- departure thunderstorm and wind-shear event;
- snow/freezing-rain destination with runway-condition updates;
- enroute icing during climb/descent only;
- severe turbulence at planned level;
- weather-driven EDTO airport degradation;
- stale CFP weather superseded by a newer official product; and
- conflicting products from adjacent authorities requiring resolution.

---

## 15. Standing instruction

Apply this protocol whenever supplemental meteorological information is operationally pertinent. The pilot-facing brief must state the flight-specific effect on route, departure, destination, alternates or EDTO. It must remain concise, current and traceable to the responsible official source.
