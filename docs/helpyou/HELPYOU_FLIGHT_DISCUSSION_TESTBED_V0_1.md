# Helpyou Flight Discussion Test Bed v0.1

**Status:** Controlled prototype  
**Date:** 05.08.26  
**Purpose:** Give a pilot a separate browser page to discuss a flight, teach Helpyou and inspect exactly what Helpyou learned.

## 1. Customer need

> “Let me discuss a realistic flight decision in my own words. Ask only the question that materially improves the decision, teach me from controlled sources, and show what you learned from me without treating my experience as authority.”

## 2. Functional requirements

| FR | Requirement | Test-bed result |
|---|---|---|
| FR1 | Load a flight-specific operational baseline without duplicating analysis | Immutable Flight Briefing SQ23 snapshot |
| FR2 | Elicit the pilot’s own decision before teaching | Initially unranked options and pilot-first response |
| FR3 | Ask the first material missing question | Deterministic Endsley/Rasmussen facilitator |
| FR4 | Construct a concise teaching response | Axiomatic Design teaching plan |
| FR5 | Review only observable discussion evidence | Selective developmental CBTA/Flight Discipline output |
| FR6 | Learn visibly and reversibly from the pilot | Raw wording, separate interpretation, private memory and deletion |
| FR7 | Preserve evidence boundaries | Pilot memory cannot become Flight Briefing evidence |
| FR8 | Make the session independently reviewable | JSON export containing transcript, state, teaching and memory |

## 3. Pilot-facing flow

```text
Select Flight Briefing case
        ↓
Read the flight baseline and unranked options
        ↓
State an initial decision and controlling reason
        ↓
Answer one material question at a time
        ↓
Receive the minimum sufficient teaching response
        ↓
Inspect evidence, developmental observations and memory
        ↓
Correct/delete memory or export the complete session
```

The academic model names remain secondary. The pilot sees operational questions:

- What is confirmed and what is assumed?
- What does it change operationally?
- What changes at the next decision point?
- What would invalidate the present plan?
- What capability is degraded and retained?
- Which safety margin controls the decision?
- What is the crew objective?
- How will the crew implement, monitor and recover?

## 4. Initial controlled case

The first test uses the frozen SQ23 golden case:

```text
SQ23 KJFK–WSSS
25.07.26
A350-941 9V-SGE
Stable OEI at ETP1-1D
ACTM 03:18 / 0533Z
Candidates: CYQX and EINN
```

The scenario cannot be silently changed to fire, smoke, severe damage, depressurisation or another failure. Such a change requires a separate controlled Flight Briefing case.

## 5. Teaching and learning boundaries

- Flight Briefing owns CFP, timing, weather, NOTAM, fuel and deterministic analysis.
- Helpyou consumes the immutable snapshot and does not recalculate it.
- The pilot’s response is preserved before the teacher answer is shown.
- The teaching output remains conditional where the source fixture contains explicit assumptions.
- CBTA observations describe only what was stated in the discussion.
- Actual aircraft handling, callouts, checklist execution and crew performance are not inferred.
- Every stored pilot contribution remains `pilot_reported` unless independently verified against a current applicable source.

## 6. Interface

The page uses three persistent areas:

1. **Session rail** — start or resume a discussion.
2. **Conversation and teaching area** — one facilitator question at a time, followed by the teaching result.
3. **Contextual inspector** — Flight Briefing baseline, option cards, evidence assumptions and pilot memory.

The inspector remains visible on desktop and moves below the conversation on smaller screens. No academic dashboard or full competency matrix is displayed by default.

## 7. Persistence and export

The prototype stores locally in SQLite:

- session mode and scenario;
- structured pilot reasoning;
- transcript messages;
- raw pilot wording;
- separate Helpyou interpretation;
- evidence and privacy status.

The pilot may delete memory and export the entire session as JSON for Claude adversarial review or later replay.

## 8. Run

```bash
python -m pip install -r pilotdriven_odss_dashboard/requirements.txt
PYTHONPATH=integration/helpyou python -m testbed
```

Open:

```text
http://127.0.0.1:8010
```

## 9. Validation

```bash
PYTHONPATH=integration/helpyou pytest -q integration/helpyou/testbed/tests
```

The first suite verifies:

- Flight Briefing public naming;
- unranked SQ23 options;
- fixed scenario boundaries;
- one-question-at-a-time progression;
- complete teaching-plan generation;
- raw/interpretation memory separation;
- non-authoritative pilot contribution handling;
- export of transcript and memory.
