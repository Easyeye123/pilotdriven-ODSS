# PilotDriven Airport Intelligence & Pilot Notes Protocol v25

## Master Protocol, Decision Flow and Handover Standard

Status: baseline architecture for scaling Pilot Notes to hundreds of airports.
Audience: PilotDriven/Helpyou developers, aviation SMEs and future ChatGPT conversations.
Primary record: Airport.
Pilot-facing product: Pilot Notes.
Supersedes: v24 and earlier fragments.

## 1. System boundary

Pilot Notes is part of Helpyou.

Helpyou -> Airport Intelligence Library -> Pilot Notes

Current-Day Overlay -> NOTAM / AIP SUP / weather / RCR / RWYCC / SNOWTAM / active outages

Pilot Notes is the curated pilot-facing view. Airport Intelligence Library is the structured knowledge source. PDF is an output product, not the primary database.

Pilot Notes shall not alter PilotDriven core logic, ODSS, ODSS Level 1, ODSS Level 2, existing flight-plan briefing logic or core Helpyou.

## 2. Core scalability rule

One airport = one complete Airport Intelligence record and one Pilot Notes package.

Do not create separate operational libraries for noise, holding, approach category, pavement, de-icing, A-CDM, LVP, occurrences or approach notes.

AIRPORT -> RUNWAY / SURFACE / PROCEDURE -> THREAT -> EVIDENCE -> SOURCE -> CHART

The airport is the primary record for all future scaling.

## 3. Three knowledge layers

Layer A - STATIC / CONTROLLED:
airport geometry; permanent hotspots; PANS-OPS/TERPS basis; permanent noise/speed/holding requirements; procedure characteristics; aircraft-size restrictions; pavement; recurring terrain/weather characteristics.

Layer B - EVIDENCE:
accidents; serious incidents; incursions; altitude deviations; unstable approaches; go-arounds; wildlife/FOD; drone events; pilot experience.

Layer C - CURRENT-DAY:
NOTAM; active AIP SUP; closures; temporary construction; crane; NAVAID outage; de-icing configuration; RCR/RWYCC; SNOWTAM; current SIGMET/windshear.

Never permanently merge Layer C into Layer A.

## 4. Source hierarchy

AUTHORITATIVE:
1. State AIP/eAIP.
2. AIP SUP / AIC / NOTAM.
3. Official aerodrome/SID/STAR/holding/approach chart.
4. CAA / FAA.
5. ANSP.
6. Airport operator official safety/operations material.
7. National investigation body.
8. ICAO / EASA / FAA regulatory material.
9. Manufacturer-controlled material.
10. Operator-controlled material where supplied.

CORROBORATED PILOT EXPERIENCE: multiple credible professional-pilot sources consistent with authority.
UNOFFICIAL / SINGLE-SOURCE: research cue or clearly labelled awareness item.
CONFLICTING / OBSOLETE: exclude from current guidance.

Authoritative information controls.

## 5. Decision flow - new airport

STEP 1 IDENTIFY
Confirm ICAO/IATA/name, State, official AIS/CAA/FAA source and current cycle.
If official source cannot be established -> UNRESOLVED SOURCE GAP.

STEP 2 BUILD AIRPORT RECORD
Retrieve GEN 1.7, ENR 1.5/relevant ENR, AD 2, AIP SUP/AIC, official airport/hotspot and pertinent SID/STAR/IAP/holding charts.

STEP 3 DETERMINE PROCEDURE BASIS
PANS-OPS / TERPS / State-modified PANS-OPS / national criteria / Doc 9905 RNP AR. Check criteria mismatch.

STEP 4 BUILD SAFETY EVIDENCE
Review rolling six-month occurrences, enduring historical events, hotspots, investigation material and credible pilot reports.

STEP 5 EXTRACT AIRPORT OPERATIONS
A-CDM/TOBT/TSAT; start-up/pushback/DCL; de-icing; speed control; holding; noise; LVP; ARFF; GRF; aircraft/pavement; units. Unavailable -> NIL.

STEP 6 BUILD PROCEDURE OBJECTS
Exact title, runway, waypoints, restrictions, design basis, threats, occurrences, pilot experience, chart and missed approach.

STEP 7 CLASSIFY RISKS
CONFIRMED COMPATIBILITY / STATE DIFFERENCE REQUIRING ATTENTION / POTENTIAL CRITERIA MISMATCH / UNRESOLVED SOURCE GAP / NO CLASH IDENTIFIED.

STEP 8 RENDER
Hybrid chart-adjacent Pilot Notes.

STEP 9 QA
Verify source, cycle, units, chart, procedure suffix, event status and note/chart adjacency.

STEP 10 RELEASE
DRAFT -> SOURCE VERIFIED -> SME REVIEWED -> RELEASED.

## 6. Decision flow - Helpyou retrieval

A. Resolve intent:
airport; phase; runway; procedure; aircraft type if relevant; static versus current-day request.

B. Retrieve minimum relevant objects.
Example VHHH ILS25R: procedure object + authoritative sources + chart + linked occurrences + pilot-experience notes + missed approach + current-day overlay if relevant.

Do not retrieve the complete airport unless needed.

C. Apply precedence:
AUTHORITATIVE > CORROBORATED PILOT EXPERIENCE > SINGLE-SOURCE.

D. Compose:
1. Threat.
2. Exact position/procedure.
3. Controlling requirement.
4. Occurrence evidence if relevant.
5. Pilot experience if useful.
6. Current-day item if applicable.
7. Official chart/source.

E. Expand on demand:
Airport overview -> procedure -> threat -> occurrence -> source/chart.

## 7. Layout decision flow

Is information tied to a chart?
YES -> chart-adjacent analytical page.
NO -> compact airport-data page.

Chart-adjacent: hotspot, SID, STAR, ILS/LOC, RNP, VOR/NPA, missed approach.
Compact: A-CDM, de-icing, holding, noise, ARFF, pavement, units.

Does portrait reduce chart readability?
YES -> retain landscape/native chart orientation.
NO -> portrait permitted.

Operational readability overrides orientation consistency.

## 8. Mandatory airport content

1. Airport operational profile.
2. Occurrence / accident evidence.
3. Ground movement / hotspots.
4. SID / departure.
5. STAR / arrival.
6. Instrument / non-precision approach.
7. Landing / missed approach.
8. Airport Operations - AIP.
9. Airport-Specific Limitations.
10. Aircraft / Aerodrome Compatibility.
11. Operational Threat Summary.
12. Source / revision status.

No Procedure Review Checklist.

## 9. Occurrence decision flow

Authoritative investigation/safety source -> AUTHORITATIVE.
Otherwise corroborated by multiple credible professional sources -> CORROBORATED PILOT EXPERIENCE.
Otherwise -> SINGLE-SOURCE or exclude.

Check current relevance against runway geometry, taxiway geometry, procedure, NAVAID and operating method.

Each retained event:
date; exact position/procedure; type; authority; report status; operational fact; current applicability.

Do not force Top 3.
Do not state incident rate without denominator.

## 10. Procedure / chart flow

1. Confirm exact chart title/effective cycle.
2. Identify design basis.
3. Identify runway/transition.
4. Extract material altitude/speed/navigation restrictions.
5. Identify IAF/IF/FAF/FAP/MAPt as relevant.
6. Extract missed approach.
7. Check circling only if published.
8. Link occurrences.
9. Link pilot-experience challenge.
10. Place note adjacent to official chart.

Waypoint: WAYPOINT(PROCEDURE-RWY).

Never transfer missed approach, minima, waypoint restriction, DME source or limitation from another procedure.

## 11. PANS-OPS / TERPS compatibility flow

For each airport/procedure:
1. State standard.
2. GEN 1.7.
3. ENR 1.5.
4. AD 2.
5. Chart annotation.
6. Holding.
7. Circling.
8. Missed approach.
9. Obstacle-clearance basis.
10. Surveillance/minimum-altitude basis.
11. Foreign-procedure/operator acceptance where relevant.

Doc 4444 is ATM/ATC context, not the primary IFP design standard.
Do not describe an obstacle itself as PANS-OPS or TERPS.
Risk = wrong design assumptions, not automatic proof of unsafe procedure.

## 12. Holding

Display authenticated State/chart requirement only.

FAA / TERPS:
MHA-6,000 ft: 200 KIAS MAX.
6,001-14,000 ft: 230 KIAS MAX.
14,001 ft and above: 265 KIAS MAX.
Lower charted speed controls.

PANS-OPS States:
State AIP -> current chart -> current/licensed ICAO Doc 8168 where required.
Lower State/chart value controls.

No generic holding explanation in airport notes.

## 13. Noise

State only:
source; runway/time applicability; NADP1/NADP2 or State THR RED/ACC; mandatory SID/track/altitude; CDA/CDO if applicable; landing-flap restriction; reverse-thrust restriction; APU/engine-run restriction if material.

No airport-specific requirement -> NIL.
Aircraft execution remains manufacturer/operator controlled unless State explicitly prescribes it.

## 14. Airport Operations - AIP

Compact table:
A-CDM / TOBT / TSAT; start-up/pushback/DCL; de-icing/anti-icing/ice shedding; arrival speed; departure speed; holding; noise departure/landing; approach specifics; departure specifics; LVP; ARFF/RFFS; GRF/runway condition; aircraft/pavement; units.

Unavailable/not applicable -> NIL.

## 15. Dynamic information flow

Can the value change operationally without permanent AIP revision?
YES -> CURRENT-DAY.

Examples:
RWYCC; RCR; SNOWTAM; active de-icing pad; closure; NAVAID outage; crane; temporary construction; current SIGMET.

At response time retrieve current-day source and overlay on static knowledge. Do not write it permanently into the static airport record.

## 16. Aircraft / aerodrome compatibility

Keep inside airport package:
approach category/minima; PANS-OPS/TERPS basis; circling if published; ICAO aerodrome code; FAA AAC/ADG/TDG where applicable; Code E/F restrictions; wingspan/gear-span; runway/taxiway width; turn pad; bridge/shoulder; stand restriction; recovery capability; pavement.

Do not reproduce generic training tables in each airport.

## 17. Pavement decision flow

Current State AIP publishes ACR/PCR -> retain ACR/PCR.
Current State AIP publishes ACN/PCN -> retain ACN/PCN.
Unavailable -> NIL.

Do not unofficially convert.
Do not compare ACR directly with PCN.
Do not compare ACN directly with PCR.

Record runway/taxiway, system, exact rating, segment differences and effective source.

## 18. Units decision flow

FAA / TERPS: preserve ft, NM, ft/NM, statute miles, RVR ft.
ICAO / State: preserve ft altitude, NM, kt, dimensions m, visibility/RVR m or km, gradient % or State-published equivalent.

If conversion is useful:
SOURCE VALUE -> secondary conversion.

Never silently substitute units.

## 19. Threat object

Recommended fields:
threat_id; airport; phase; procedure; position; hazard; conditions; evidence/source IDs; source_status; operational_effect; confirm; crew_response; linked_occurrences; linked_chart; invalidation_trigger.

Threat IDs are internal Pilot Notes identifiers, not official incident numbers.

## 20. Occurrence object

Recommended fields:
occurrence_id; airport; date; phase; runway; procedure; position; authority; status; facts; linked_threats; publication_date; invalidation_trigger.

Preserve facts separately from Pilot Notes conclusions.
PRELIMINARY -> INTERIM -> FINAL triggers re-evaluation of linked threats.

## 21. Procedure object

Recommended fields:
procedure_id; airport; type; runway; design_basis; effective_cycle; waypoints; restrictions; missed_approach; holding; circling; linked_threats; linked_occurrences; chart_source; invalidation_trigger.

## 22. Airport object

Recommended fields:
airport_id; ICAO; IATA; name; State; authority; effective_cycle; procedure_basis; runways; surface; operations; procedures; occurrences; threats; sources; current_day_overlay; release_status.

## 23. AIRAC / change-management flow

On each AIRAC:
1. Compare current authoritative source with previous.
2. Identify changed objects.
3. Mark affected objects REVIEW REQUIRED.
4. Revalidate linked threats.
5. Replace affected chart.
6. Preserve unaffected occurrence history.
7. Update cycle.
8. SME review changed conclusions.
9. Release new airport version.

Do not regenerate the complete airport unnecessarily.

## 24. Invalidation triggers

noise -> AD 2.21 change.
ILS note -> IAP revision.
SID note -> SID revision.
hotspot -> airport/hotspot chart revision.
holding -> ENR/IAP revision.
pavement -> AD 2.8/2.12 revision.
pilot experience -> geometry/procedure change.
occurrence -> final report.
LVP -> AD 2 operating-procedure revision.

Every stored object carries an invalidation trigger.

## 25. QA release flow

SOURCE:
authority/current cycle/exact citation/source class.

PROCEDURE:
exact title/runway suffix/waypoint/missed approach/chart.

SAFETY:
event date/report status/current applicability/no unsupported rate.

AIRPORT OPS:
NIL/CURRENT-DAY/noise/holding/LVP/pavement/units.

PRESENTATION:
note beside chart/readable/no repeated threat/no generic filler/pilot terminology.

Critical failure -> REVIEW REQUIRED, not RELEASED.

## 26. Pilot-facing writing

Use:
HAZARD
POSITION
CONDITIONS
EVIDENCE
OPERATIONAL EFFECT
CONFIRM
CREW RESPONSE
SOURCE STATUS

Qualified-pilot language.
Succinct.
No lay explanation.
No IT terms in pilot-facing notes.
No “gate” terminology.
No repeated reminders.
No Procedure Review Checklist.
One threat once; cross-reference rather than repeat.

## 27. Current baseline airports

KJFK - John F Kennedy International
VHHH - Hong Kong International
WMKK - Kuala Lumpur International / Sepang
WSSS - Singapore Changi
VTBS - Suvarnabhumi International
LFPG - Paris Charles de Gaulle
LIRF - Roma/Fiumicino
YPPH - Perth Airport
RPLL - Ninoy Aquino International / Manila
RKSI - Incheon International
FAOR - O. R. Tambo International
KLAX - Los Angeles International

All future airports use v25 architecture.

## 28. Handover instructions for the next conversation

1. Read v25 first.
2. Airport Intelligence Library is the scalable source model; Pilot Notes is the pilot-facing view.
3. Preserve the 12-airport baseline unless explicitly changed.
4. Do not alter ODSS Level 1/2 or core PilotDriven/Helpyou.
5. Research official current sources before generating a new airport.
6. Occurrence evidence is mandatory.
7. Keep operational notes adjacent to pertinent official charts.
8. Use NIL rather than generic filler.
9. Keep dynamic data CURRENT-DAY.
10. Preserve authoritative versus pilot-experience demarcation.
11. Maintain PANS-OPS/TERPS compatibility review.
12. Keep aircraft/aerodrome/pavement data inside airport record.
13. Preserve source units.
14. Use object-level invalidation and AIRAC change detection.
15. Generate PDF/export only after structured airport record and QA.

## 29. v25 decision

Approved scalable architecture:

Helpyou
-> Airport Intelligence Library
-> structured airport/procedure/threat/evidence objects
-> Current-Day Overlay when applicable
-> Pilot Notes response/UI
-> optional PDF/export.

Compactness comes from targeted retrieval and removal of repetition, not from removing occurrence evidence or separating operational notes from the chart they explain.
