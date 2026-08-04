# Helpyou Core v0.2 — Guided Decision Orchestrator

**Status:** Controlled prototype vertical slice  
**Golden case:** SQ23 KJFK–WSSS, 25.07.26, A350-941 9V-SGE  
**Scenario anchor:** ETP1-1D, ACTM 03:18, 0533Z  
**Purpose:** Prove deterministic request segregation, CFP-grounded facilitation, cognitive-model gating, Axiomatic Design option structure, developmental CBTA mapping and governed pilot-memory capture.

## Authority boundary

Helpyou Core does not parse or recalculate the Lido CFP. ODSS remains the sole owner of:

- CFP parsing and route timing;
- weather and NOTAM applicability;
- EDTO entry, exit, ETP and diversion data;
- fuel, MSA/VWS, BOBCAT, FIR, MEL/CDL and depressurisation findings;
- the immutable source/evidence snapshot.

The core consumes an ODSS scenario baseline. Pilot experience and AI possibilities cannot be used as ODSS evidence.

## SQ23 source baseline

The controlled test fixture is derived from the SQ23 Lido CFP, OFP 108/0/1:

- KJFK to WSSS;
- A350-941, 9V-SGE;
- scheduled 0215Z to 2130Z;
- first EDTO segment with CYQX and EINN;
- ETP1-1D at ACTM 03:18, near N56 26.2 W036 35.7;
- planned 1D diversion time of 02:23 to each EDTO airport in the source table;
- candidate weather periods and forecast trends are preserved as ODSS inputs, not reinterpreted by Chat.

Reference format:

`[SIA | SQ23 Lido CFP | OFP 108/0/1 | Navlog and EDTO Information | pp.7,18 | ETP1-1D]`

## Landing-performance treatment

The A350 FCOM does not make an ICAO Code 4E classification a substitute for aircraft landing-performance assessment.

The FCOM framework used by the fixture is:

1. Required Landing Distance is the regulatory dispatch reference.
2. At dispatch, LDA must be at least the RLD for the planned landing weight.
3. In flight, changed conditions, diversion or a failure require the approved EFB landing-performance computation using Factored In-Flight Landing Distance.
4. If the factor is disregarded in an emergency, In-Flight Landing Distance must remain shorter than LDA.
5. A failure affecting performance must be selected in the EFB, including applicable MEL/CDL items.

Reference:

`[SIA | A350 FCOM | Rev 18A | eff 13.08.25 | PER-LDG-20 / PER-LDG-40 / PER-LDG-50 | A350 fleet]`

For this prototype only, the product owner directed that landing performance and landing distance be assumed suitable for the A350 test candidates. The fixture therefore stores:

```text
landing_performance_assumed_suitable = true
status = scenario_assumption
```

The assumption is visible and forces the overall teaching result to remain **Conditional**. Production use must replace it with approved EFB/performance data. Code 4E alone is never promoted to an authoritative performance conclusion.

## Conversation sequence

```text
Lido CFP / ODSS case
        ↓
Validate immutable ODSS baseline
        ↓
Present viable candidate options without AI ranking
        ↓
Pilot selects an option and explains the controlling reason
        ↓
Endsley: picture now → meaning → projection → scan-width → decision gate
        ↓
Rasmussen: capability → safety constraint → objective → action/feedback
        ↓
Axiomatic Design: CN → independent FRs → constraints → options → coupling
        ↓
CBTA: map only demonstrated discussion evidence
        ↓
Teacher response: answer, condition, gate, one key gap, citations
        ↓
Store raw pilot wording separately from AI interpretation
```

The facilitator asks one material missing question at a time. It does not display every model when the pilot has already covered the relevant element.

## Axiomatic Design decision model

### Customer Need

Safely manage the aircraft condition and reach an operationally suitable landing aerodrome.

### Functional Requirements

- **FR1:** Maintain controllability and an acceptable one-engine flight path.
- **FR2:** Remain clear of terrain and hazardous weather.
- **FR3:** Use an aerodrome compatible with the aircraft condition, runway, approach and approved landing-performance requirement.
- **FR4:** Preserve the applicable fuel and time margins.
- **FR5:** Maintain manageable workload and disciplined flight-path control.
- **FR6:** Retain a viable fallback.
- **FR7:** Complete aircraft, ATC, cabin and operational coordination.

### Independence rule

The pilot or system may not treat one favourable attribute, such as distance, as satisfying every requirement. A nearer aerodrome can reduce time-to-land while worsening weather, runway, approach or fallback margin.

### Information rule

Helpyou surfaces the smallest complete answer:

- selected option status;
- material conditions;
- decision gate;
- first significant situational-awareness or cognitive gap;
- relevant developmental competencies;
- compact citations.

Full matrices and model traces remain expandable.

## Endsley implementation

User-facing headings are:

- **Picture now** — confirmed flight facts versus assumptions.
- **What it means** — operational significance.
- **Projection ahead** — future aircraft, weather, fuel and option state.
- **Widen the scan** — missing disconfirming evidence or neglected area; never a diagnosis of “tunnel vision”.
- **Decision gate** — condition, limit and resulting action.

## Rasmussen implementation

Academic hierarchy labels remain backend-only. The pilot sees:

- Information and indications;
- System and automation behaviour, only where diagnosis is material;
- Aircraft and crew capability;
- Safety constraints and margins;
- Crew objective;
- Action and feedback.

A higher-level statement is not automatically better. An objective without an implementable action and feedback loop remains incomplete.

## CBTA implementation

The core can map explicit discussion evidence to KNO, PRO, PSD, SAW, WLM, COM/LTW and PilotDriven Flight Discipline. It does not infer actual flight-path control, checklist execution or crew behaviour from a written intention.

The output is developmental and case-specific. It is not a formal airline, licensing or operator competency grade.

## Package layout

```text
integration/helpyou/
├── helpyou_core/
│   ├── contracts.py
│   ├── request_router.py
│   ├── evidence_guard.py
│   ├── odss_adapter.py
│   ├── endsley.py
│   ├── rasmussen.py
│   ├── axiomatic_decision.py
│   ├── facilitator.py
│   ├── cbta_mapper.py
│   ├── response_planner.py
│   ├── memory_classifier.py
│   └── orchestrator.py
├── fixtures/
│   └── sq23_oei_etp1_1d.json
└── tests/
```

## Validation

Run:

```bash
cd integration/helpyou
PYTHONPATH=. python -m unittest discover -s tests -v
```

Current local result:

```text
Ran 26 tests
OK
```

The existing `test_helpyou_policy.py` suite remains separate and must also pass.

## Known limitations before Claude adversarial review

- No production database writer is included.
- No LLM prose renderer is included; the core returns deterministic teaching plans.
- No proprietary manual or CFP content is committed; the fixture stores metadata, derived test values and references only.
- No approved EFB landing-performance result is included.
- Current weather and NOTAM refresh are ODSS service responsibilities and are not implemented here.
- The option set is limited to the ODSS candidates supplied in the fixture.
- The first case covers a stable OEI EDTO diversion at ETP1-1D; fire, severe damage and combined failures require separate fixtures.

## Adversarial-review boundary

Claude should review a frozen commit of this branch. It should attack requirement traceability, hidden coupling, evidence bypass, over/under-questioning, invalid cognitive inference, memory contamination and untested failure paths. It should not replace ODSS or recast Helpyou as an approved training/checking system.
