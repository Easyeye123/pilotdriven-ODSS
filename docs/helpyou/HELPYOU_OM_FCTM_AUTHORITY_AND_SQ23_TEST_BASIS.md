# Helpyou OM/FCTM Authority Review and SQ23 Golden-Test Basis

**Status:** Controlled prototype design record  
**Date:** 04.08.26  
**Applicable test:** SQ23 KJFK-WSSS, 25.07.26, A350-941 9V-SGE, stable OEI at ETP1-1D

## 1. Purpose

This record updates Helpyou Core v0.2 after review of:

- SIA Operations Manual Rev 32, eff 01.04.26;
- A350 SIA FCTM Volume 2 Rev 1.0, eff 30.04.26;
- SIA A350 FCOM Rev 20, eff 06.05.26;
- the SQ23 Lido CFP OFP 108/0/1.

It fixes the operator-document hierarchy, separates the FCOM landing-performance method from an airport-specific result, and records the product-owner assumptions for NOTAMs, MEL and landing performance in the frozen desktop test.

## 2. Operations Manual review

### 2.1 OM architecture

The OM identifies four volumes:

- Volume A — general policies, instructions and procedures;
- Volume B — aircraft operating information and type-specific component documents;
- Volume C — routes and aerodromes;
- Volume D — training.

The A350 Volume B framework links controlled component documents such as FCOM, QRH, AFM, CDL, MEL, SQNP, SQSP, SQI, FSI, SEP, weight-and-balance and fuelling material. The existence of a component in this list does not itself create a separate priority rank.

### 2.2 Mandatory airworthiness and regulatory compliance

OM 12.1.1.1 requires compliance with the Certificate of Airworthiness, Singapore ANO/ANR, AFM and SIA OM. A lower-authority document may impose a more restrictive requirement; where it does, the more restrictive requirement must be followed.

This means Helpyou must not use priority as permission to relax a valid lower-level safety restriction.

### 2.3 Descending operational-document priority

OM 12.1.1.1 para (5) states this descending order:

| Rank | Document group |
|---:|---|
| 1 | INTAMs |
| 2 | Flight Staff Instructions |
| 3 | Minimum Equipment List Manual |
| 4 | SIA OM Vol A / FCOM / Jeppesen Reference Texts / SQNP / SQSP |
| 5 | Safety Equipment and Procedures Manual |
| 6 | FCTM / Technical Bulletins / Airport Briefings / Circulars |
| 7 | Crew Administration Manual / Flight Security Procedures Manual |

Helpyou must preserve the same-level grouping. It must not invent a sub-priority between OM Vol A, FCOM, Jeppesen Reference Texts, SQNP and SQSP merely because they appear in a particular order on the page.

QRH, CDL, SQI, weight-and-balance and fuelling documents are linked Volume B components, but OM 12.1.1.1 does not assign each of them a distinct rank in the above list. Their use therefore requires subject-scope, document-relationship, revision and applicability resolution rather than an invented ranking.

### 2.4 Version discrepancy rule

Where iPad and installed-EFB document versions differ, the latest revision is used. On aircraft with an installed EFB, the AFM, MEL and CDL copies installed there are the primary operational references.

### 2.5 Non-normal and emergency rule

For a non-normal or emergency, the relevant OM or AFM section applies. Where neither covers the case, the Commander uses judgement and discretion to secure the safety of the aircraft and records the event as required.

### 2.6 A350 EDTO and engine-failure decision basis

For the A350, OM Rev 32 establishes:

- standard EDTO approval to 180 minutes at the approved OEI diversion speed;
- 207/240-minute flight-by-flight exception provisions in approved regions;
- inflight route protection within the applicable maximum diversion time;
- adequate and suitable EDTO airport criteria;
- weather, facilities, runway, instrument-approach, RFFS, fuel and performance considerations;
- flight following and inflight reassessment;
- Commander discretion to select another airport considered more appropriate under the actual circumstances.

Following engine failure, the OM requires ATC notification, drift-down and terrain protection. It permits obstacle, fixed-speed and standard strategies, or another strategy considered appropriate under the prevailing constraints.

The decision is not “nearest airport” by distance alone. For A350 LAND ANSA/LAND ASAP situations, the OM requires the nearest suitable airport where a safe approach and landing can be made. A more distant airport may be safer because of weather, facilities or runway margin. Persistent smoke or fire not positively confirmed extinguished may instead demand the earliest possible landing.

## 3. FCTM review

### 3.1 Authority role

FCTM Volume 2 is part of OM Volume D. It is controlled operator training/technique material, but OM places FCTM in priority group 6, below MEL and the group containing OM Vol A, FCOM, Jeppesen, SQNP and SQSP.

Helpyou may use FCTM to teach technique, task sharing and scenario management. It may not override a higher-priority operational instruction.

### 3.2 Engine-failure and OEI content

The reviewed FCTM:

- refers the engine-fire procedure back to the FCOM and adds sequencing guidance to avoid distraction before critical ECAM fire-agent actions are completed;
- refers One Engine Inoperative Landing to the applicable FCTM Volume 1 material;
- specifies, for manual OEI landing, rudder-trim reset no later than 1,000 ft AAL.

Because Volume 1 is referenced but not in the current bundle, Helpyou may state the Volume 2 point but must not fabricate the missing Volume 1 technique.

### 3.3 EDTO teaching content

The FCTM distinguishes:

- an adequate airport — performance can be met, facilities and services are available, and the airport is expected to be operational;
- a suitable EDTO airport — an adequate airport whose forecast weather meets the applicable estimated-time-of-use criteria.

It also teaches operational control, communications, MEL status, fuel, performance information and the Commander’s ability to select another more appropriate airport.

### 3.4 LOFT and facilitation content

The FCTM LOFT section uses realistic flight documentation and a line-operational environment. It identifies time management, coordination, communication, task delegation, task priority, automation/workload management, TEM, situational awareness, decision making, safety and abnormal/emergency management as discussion areas.

Helpyou adopts these as teaching prompts, not as a claim that a desktop chat is an approved simulator LOFT or formal assessment.

## 4. Landing-performance implementation

### 4.1 Authoritative method

The FCOM Performance section is the authoritative source for the A350 landing-performance method:

- an inflight computation is required when diversion, runway, weather or a performance-affecting failure changes the landing conditions;
- the approved EFB landing-performance application is used;
- FLD is normally used for the inflight assessment;
- applicable ECAM, MEL and CDL effects are selected;
- in an emergency, if the factor is disregarded, LD must still be shorter than LDA.

### 4.2 No airport-specific result in the source bundle

The FCOM describes the approved method and aircraft-performance logic. It does not contain a precomputed CYQX or EINN runway result for this SQ23 scenario.

The golden test therefore uses two separate evidence objects:

1. **Authoritative method:** FCOM Rev 20 landing-performance framework.
2. **Scenario result assumption:** landing performance is suitable for both test candidates.

The fixture must not create or imply numerical LDA, LD, FLD, RLD or runway-required values that were not supplied.

Code 4E remains an aerodrome-design compatibility classification and is not used as proof of landing-distance suitability.

## 5. Product-owner assumptions for the frozen SQ23 test

The following are accepted only for the frozen golden test:

1. The NOTAMs in the SQ23 Lido CFP are current and valid.
2. The current MEL items declared in the SQ23 CFP and their operational conditions are valid.
3. Landing performance is suitable for the A350 test candidates under the FCOM method.
4. The scenario remains a stable OEI case without continuing fire, severe damage or additional degradation.
5. CFP weather is the desktop-scenario weather within its stated validity and projected arrival times.

These assumptions remove repetitive data-verification prompts from the desktop test. They do not become authoritative operational claims and do not transfer to another flight, date or live operation.

MEL validity does not remove MEL restrictions. The conditions remain inputs to the scenario and performance method. A new defect arising in flight is handled under the inflight procedure and OM policy rather than by re-running dispatch eligibility.

## 6. Helpyou decision structure for SQ23

For each candidate, Helpyou evaluates independent requirements:

- controllability and OEI flight path;
- terrain and weather avoidance;
- adequate/suitable airport criteria;
- fuel and time margins;
- FCOM landing-performance method and test assumption;
- workload and Flight Discipline;
- communication and coordination;
- retained fallback.

CYQX and EINN remain initially unranked. The pilot explains the choice before Helpyou provides the teaching comparison. Distance may influence the decision but cannot independently establish suitability.

## 7. Machine implementation

The policy is represented in:

```text
integration/helpyou/helpyou_core/document_priority.py
integration/helpyou/helpyou_core/source_registry.py
integration/helpyou/fixtures/sq23_source_manifest_rev20.json
integration/helpyou/fixtures/sq23_oei_etp1_1d.json
```

Regression tests require:

- exact OM priority groups;
- no invented priority for QRH/CDL/SQI;
- FCTM below FCOM and MEL;
- latest-copy and installed-EFB AFM/MEL/CDL rules;
- OM and FCTM authority boundaries;
- explicit NOTAM, MEL and landing-performance test assumptions;
- separation of FCOM method from assumed airport result;
- no fabricated airport-specific landing-distance values.

## 8. Remaining production gaps

The golden test can proceed, but production use still requires:

- current A350 MEL/CDL source text and 9V-SGE effectivity;
- FCTM Volume 1 where directly referenced;
- actual airport-specific EFB inputs/output for an operational case;
- live weather, charts and AIP for the actual time of use;
- current OEB/TAB/temporary-document applicability;
- confirmation that QRH Rev 18 remains current for the intended operational date.
