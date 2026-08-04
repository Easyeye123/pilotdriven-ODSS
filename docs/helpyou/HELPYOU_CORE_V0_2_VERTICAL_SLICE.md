# Helpyou Core v0.2 — Guided Decision Orchestrator

**Status:** Controlled prototype vertical slice  
**Golden case:** SQ23 KJFK–WSSS, 25.07.26, A350-941 9V-SGE  
**Scenario anchor:** ETP1-1D, ACTM 03:18, 0533Z  
**Source baseline:** SIA OM Rev32 / A350 FCOM Rev20 / FCTM Vol2 Rev1  
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

The controlled fixture is derived from SQ23 Lido CFP OFP 108/0/1:

- KJFK to WSSS;
- A350-941, 9V-SGE;
- scheduled 0215Z to 2130Z;
- first EDTO segment with CYQX and EINN;
- ETP1-1D at ACTM 03:18, near N56 26.2 W036 35.7;
- planned 1D diversion time of 02:23 to each EDTO airport in the source table;
- candidate weather periods and forecast trends preserved as ODSS inputs.

Reference format:

`[SIA | SQ23 Lido CFP | OFP 108/0/1 | Navlog and EDTO Information | pp.7,18 | ETP1-1D]`

## OM-grounded document priority

SIA OM Rev32, 12.1.1.1 supplies the descending operational priority:

1. INTAM;
2. Flight Staff Instructions;
3. MEL;
4. OM Vol A / FCOM / Jeppesen Reference Text / SQNP / SQSP;
5. SEP;
6. FCTM / Technical Bulletin / Airport Briefing / Circular;
7. Crew Administration / Flight Security Procedures.

Helpyou preserves the same-level groups rather than inventing sub-priority. Certificate of Airworthiness, ANO/ANR and AFM provisions remain mandatory. A lower-authority document may impose a more restrictive requirement. Where iPad and installed-EFB revisions differ, the latest version is used; installed-EFB AFM/MEL/CDL copies are the primary operational references.

QRH, CDL, SQI, weight-and-balance and fuelling material are linked A350 Volume B components, but they are not assigned a separate rank absent an explicit OM rule.

Machine policy:

```text
helpyou_core/document_priority.py
helpyou_core/source_registry.py
```

## OM engine-failure and EDTO basis

The OM establishes the operator decision framework for the golden case:

- protect terrain during drift-down;
- select obstacle, fixed-speed, standard or another appropriate strategy;
- choose an adequate EDTO alternate or another airport considered suitable by the Commander;
- compare proximity, weather, facilities, runway, approach, fuel, performance and fallback;
- do not assume the nearest airport is automatically the nearest suitable airport;
- preserve the urgency distinction for persistent smoke or fire not confirmed extinguished.

The source-backed teaching question is therefore not simply “Which airport is closest?” It is “Which available option best satisfies all independent safety and operational requirements under the actual condition?”

## FCTM role

FCTM Volume 2 is part of OM Volume D and is priority group 6. It supports technique, task sharing, EDTO teaching and LOFT-style facilitation, but it cannot override MEL, OM, FCOM, SQNP or SQSP.

Reviewed points include:

- engine-fire sequencing refers to the FCOM and avoids distracting the crew before critical ECAM actions are complete;
- One Engine Inoperative Landing refers to FCTM Volume 1 and states that, for manual landing, rudder trim is reset no later than 1,000 ft AAL;
- EDTO suitability includes performance, facilities, expected availability and estimated-time-of-use weather;
- LOFT discussion areas include time management, coordination, communication, task priority, workload/automation management, TEM, situational awareness, decision making and safety.

## Landing-performance treatment

The current method reference is:

`[SIA | A350 FCOM | Rev 20 | eff 06.05.26 | PER-LDG-20 / PER-LDG-50 | A350 fleet]`

The FCOM framework used by the fixture is:

1. Required Landing Distance is the dispatch reference.
2. In flight, changed runway, weather, diversion or a performance-affecting failure requires an approved EFB landing-performance computation.
3. Factored In-Flight Landing Distance is normally used.
4. Applicable ECAM, MEL and CDL effects are selected.
5. If the factor is disregarded in an emergency, In-Flight Landing Distance must remain shorter than LDA.

The FCOM contains the approved method, not a precomputed CYQX or EINN runway result for this scenario.

For the prototype, the product owner directs that landing performance and landing distance are suitable for both A350 test candidates. The fixture stores a visible `scenario_assumption` and does not fabricate any airport-specific LDA, LD, FLD, RLD or runway-required value.

Code 4E is never promoted to proof of landing-distance suitability.

## Frozen-test assumptions

For this case only:

- SQ23 CFP NOTAMs are accepted as current and valid;
- CFP-declared current MEL items and their operational conditions are accepted as valid;
- landing performance passes under the FCOM method;
- CFP weather is the scenario weather within its stated validity and projected arrival time;
- the failure remains stable OEI without continuing fire, severe damage or additional degradation.

These assumptions allow the desktop decision flow to proceed. They remain non-authoritative and cannot transfer to another case or live operation. MEL validity does not waive MEL restrictions.

## Conversation sequence

```text
Lido CFP / ODSS case
        ↓
Validate immutable ODSS baseline and source bundle
        ↓
Present viable candidates without AI ranking
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
- **FR3:** Use an aerodrome compatible with the aircraft condition, runway, approach and landing-performance requirement.
- **FR4:** Preserve applicable fuel and time margins.
- **FR5:** Maintain manageable workload and disciplined flight-path control.
- **FR6:** Retain a viable fallback.
- **FR7:** Complete aircraft, ATC, cabin and operational coordination.

### Independence rule

A single favourable attribute, such as distance, cannot satisfy every requirement. A nearer aerodrome can reduce time-to-land while worsening weather, runway, approach or fallback margin.

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

- **Picture now** — confirmed flight facts versus assumptions;
- **What it means** — operational significance;
- **Projection ahead** — future aircraft, weather, fuel and option state;
- **Widen the scan** — missing disconfirming evidence or neglected area, never a diagnosis of “tunnel vision”;
- **Decision gate** — condition, limit and resulting action.

## Rasmussen implementation

Academic labels remain backend-only. The pilot sees:

- information and indications;
- system and automation behaviour where diagnosis is material;
- aircraft and crew capability;
- safety constraints and margins;
- crew objective;
- action and feedback.

A higher-level statement is not automatically better. An objective without implementable action and feedback remains incomplete.

## CBTA implementation

The core maps explicit discussion evidence to relevant KNO, PRO, PSD, SAW, WLM, COM/LTW and PilotDriven Flight Discipline. It does not infer actual flight-path control, checklist execution or crew behaviour from written intention.

The output is developmental and case-specific, not a formal operator or licensing grade.

## Package layout

```text
integration/helpyou/
├── helpyou_core/
│   ├── contracts.py
│   ├── request_router.py
│   ├── evidence_guard.py
│   ├── odss_adapter.py
│   ├── source_registry.py
│   ├── document_priority.py
│   ├── endsley.py
│   ├── rasmussen.py
│   ├── axiomatic_decision.py
│   ├── facilitator.py
│   ├── cbta_mapper.py
│   ├── response_planner.py
│   ├── memory_classifier.py
│   └── orchestrator.py
├── fixtures/
│   ├── sq23_oei_etp1_1d.json
│   └── sq23_source_manifest_rev20.json
└── tests/
```

## Validation

Run:

```bash
cd integration/helpyou
PYTHONPATH=. python -m unittest discover -s tests -v
```

The existing `test_helpyou_policy.py` suite remains separate and must also pass. The final test count is recorded by CI rather than hardcoded in this document.

## Known limitations before adversarial review

- No production database writer is included.
- No LLM prose renderer is included; the core returns deterministic teaching plans.
- No proprietary manual or CFP content is committed.
- No airport-specific EFB output or numerical runway-performance result is included; the golden test uses an explicit pass assumption.
- NOTAM and MEL validity are frozen-case assumptions rather than live verification services.
- Live weather/AIP/chart refresh remains outside this prototype.
- The option set is limited to ODSS candidates supplied in the fixture.
- Fire, severe damage and combined failures require separate fixtures.
- FCTM Volume 1 and confirmation of QRH Rev18 currentness remain open source items.

## Adversarial-review boundary

Claude should review a frozen commit of this branch. It should attack OM priority handling, source scope, assumption leakage, evidence bypass, hidden coupling, over/under-questioning, invalid cognitive inference, memory contamination and untested failure paths. It should not replace ODSS or recast Helpyou as an approved training/checking system.
