# Helpyou CFP-Grounded Scenario and Cognitive Protocol v1

**Status:** Mandatory protocol for line-oriented individual discussion  
**Date:** 30.07.26

## 1. Scope

This protocol applies when an individual pilot asks to discuss a LOFT-style or line-oriented scenario, a decision thought process, or a scenario attached to a particular flight.

PilotDriven is not conducting an approved airline LOFT/LOE or simulator assessment. The term describes a realistic line-oriented discussion grounded in the flight's Lido CFP.

## 2. CFP upload gate

When the pilot starts a flight-specific scenario discussion, Helpyou shall:

1. request the applicable Lido CFP or allow selection of an existing CFP case;
2. process it through the established ODSS protocol;
3. create an immutable scenario baseline;
4. prevent flight-specific option generation until ODSS processing succeeds.

The pilot may explicitly select a generic scenario. Generic mode must state that no flight-specific weather, route, fuel or alternate conclusion is being produced.

## 3. ODSS scenario baseline

The scenario engine consumes, where available:

- flight identity, date, aircraft and effectivity;
- route, waypoints, UTC and ACTM;
- planned fuel and weights;
- departure, destination, alternate and EDTO weather;
- valid NOTAMs;
- MEL/CDL/CDDL findings;
- performance and airport limitations;
- high-MSA and VWS events;
- EDTO, BOBCAT/Kabul and FIR-entry requirements;
- depressurisation findings and approved chart references;
- ODSS warnings and unresolved items.

Helpyou must consume the ODSS result. It must not independently recalculate the deterministic findings in Chat.

## 4. Scenario insertion

After ODSS processing, Helpyou asks the pilot to state:

- the event;
- where it occurs: waypoint, ACTM, UTC or flight phase;
- what changes from the CFP baseline;
- any scenario assumptions.

CFP facts and pilot-inserted scenario assumptions must be displayed separately.

## 5. Weather protocol

Scenario weather shall use the same ODSS weather-selection, validity and projected-arrival logic as the CFP analysis.

For each relevant observation or forecast, retain:

- station;
- issue time;
- validity period;
- applicable forecast segment;
- projected arrival or diversion time;
- `TEMPO`, `BECMG`, `PROB` or equivalent conditions;
- stale or uncovered periods;
- whether the item is CFP baseline data or a scenario assumption.

No invented forecast or second weather interpretation path is permitted.

## 6. Option generation

Helpyou generates only materially different and operationally viable options. Examples may include:

- continue subject to a defined gate;
- limited hold then divert;
- reroute;
- return;
- divert to planned, en-route or EDTO alternate;
- select another suitable aerodrome;
- go around and reassess;
- land as soon as practicable or at the nearest suitable aerodrome.

Not every option belongs in every scenario.

Each option must be checked against:

- applicable weather;
- fuel and time;
- route and terrain;
- runway and performance;
- NOTAMs;
- MEL/CDL effects;
- system degradation;
- airport support;
- remaining safe alternatives.

Weather suitability alone does not establish aerodrome suitability.

## 7. Option card

Each option shows only:

- option;
- why it remains viable;
- weather basis and projected time;
- ODSS fuel/time/route implications;
- material conditions;
- decision gate;
- principal residual risk;
- evidence status;
- compact references.

Options are initially shown without AI ranking to reduce anchoring. Helpyou asks:

> Which option would you select, what is the controlling reason, and what exact condition changes the plan?

The pilot may propose an additional option.

## 8. Endsley situational-awareness check

After the pilot explains the reasoning, Helpyou applies five operational headings:

### Picture now

What information is confirmed, assumed, stale, inconsistent or missing?

### What it means

What does the information change about aircraft capability, the operation or the main safety margin?

### Projection ahead

What will the flight path, energy, fuel, weather, workload and available options look like at the next decision point? Which option disappears first?

### Widen the scan

What material information or task may be outside the pilot's present focus? Helpyou shall describe the omission and tunnel-vision risk, not diagnose the pilot as having tunnel vision.

### Decision gate

What variable or condition, at what limit, causes what action?

```text
CONDITION + TRIGGER + ACTION
```

A statement such as `monitor the fuel` is incomplete without the value, unacceptable trend and response.

## 9. Rasmussen cognitive review

Rasmussen remains a backend work-domain model. The pilot sees aviation language:

1. information and indications;
2. system and automation behaviour;
3. aircraft and crew capability;
4. safety constraints and operational margins;
5. crew objective;
6. action and feedback.

Helpyou surfaces only the material missing or incorrect link. It does not recite every level when the pilot has already addressed it.

For automation events, ask only what is relevant:

- current mode;
- commanded target or path;
- expected next mode;
- confirming feedback;
- simpler fallback.

## 10. CBTA developmental review

The review maps only observable discussion evidence to relevant competencies:

- KNO — Application of Knowledge;
- PRO — Procedures and Regulations;
- COM — Communication;
- FPA/FPM — Flight Path Management;
- LTW — Leadership and Teamwork;
- PSD — Problem-Solving and Decision-Making;
- SAW — Situation Awareness and Information Management;
- WLM — Workload Management;
- FLD — PilotDriven Flight Discipline.

Flight Discipline assesses preservation of aircraft-control priority, operational gates, procedures, cross-checks, timely intervention and resistance to inappropriate continuation pressure.

A written discussion may demonstrate understanding or stated intention. It does not demonstrate actual aircraft handling, checklist execution or crew behaviour unless those were genuinely observed.

Permitted developmental labels:

- insufficient evidence;
- emerging;
- partially demonstrated;
- demonstrated in this discussion;
- strong and adaptive in this discussion;
- conflicting evidence.

No official operator or licensing grade is produced.

## 11. Axiomatic Design Teacher output

The final response contains only the sections needed:

1. teaching answer or defensible decision range;
2. controlling considerations;
3. decision gates and material assumptions;
4. compact authoritative references;
5. the one material situational-awareness or cognitive gap;
6. relevant CBTA developmental evidence;
7. what Helpyou learned;
8. one transfer question, where useful.

The teacher must not repeat obvious points, define standard terms unnecessarily or restate a conclusion at the end.

## 12. Memory capture

Helpyou stores:

- the pilot's exact wording;
- the AI's separate interpretation;
- selected option and trigger;
- scenario context and ODSS snapshot;
- evidence type;
- relevant cognitive/CBTA observations;
- corrections and pilot-contributed experience;
- privacy status.

The memory write affects future interactions. It cannot change the authoritative answer basis already established for the current turn.

## 13. Acceptance tests

1. Starting a flight-specific scenario prompts for a Lido CFP.
2. Flight-specific options remain blocked until ODSS completes.
3. Scenario location is anchored to waypoint, ACTM, UTC or phase.
4. Weather uses the ODSS protocol and is checked against projected times.
5. CFP weather and scenario assumptions remain separate.
6. Options are viable, materially distinct and initially unranked.
7. Each option includes a decision gate and references.
8. Pilot reasoning is elicited before cognitive feedback.
9. Endsley, Rasmussen and CBTA remain off when no reasoning exists.
10. Only relevant cognitive gaps and competencies are shown.
11. Pilot memory never enters ODSS evidence.
12. The same source snapshot and scenario inputs reproduce the scenario baseline.
