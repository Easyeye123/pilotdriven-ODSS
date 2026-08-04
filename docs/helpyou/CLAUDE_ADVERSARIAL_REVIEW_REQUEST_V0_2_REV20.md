# Claude Adversarial Review Request — Helpyou Core v0.2 Rev20 Refresh

**Repository:** `Easyeye123/pilotdriven-ODSS`  
**Pull request:** `#32`  
**Branch:** `feature/helpyou-core-v0.2`  
**Review target:** Use the current PR head shown by GitHub after the Rev20 refresh. Do not use the superseded pre-refresh SHA `8083106b...`.

## Role

Act as an independent aviation-software, evidence-governance, cognitive-engineering and human-factors critic. Find failure paths. Do not rewrite PilotDriven into a formal training or checking system, and do not assume the architecture is safe merely because the tests pass.

## Product boundaries

1. Helpyou is an individual pilot teaching and decision-support aid.
2. It is not an approved airline LOFT, EBT, checking or licensing system.
3. ODSS exclusively owns Lido CFP parsing and deterministic flight analysis.
4. Helpyou may consume an immutable ODSS baseline but may not recalculate ODSS findings in Chat.
5. Axiomatic Design governs request decomposition, independent decision requirements, option structure and the teaching reply.
6. Endsley examines the pilot's present picture, operational meaning and projection ahead.
7. Rasmussen examines the relationship between indications, system behaviour, capability, safety constraints, operational purpose, action and feedback across part-to-whole scope.
8. CBTA provides developmental observations only from evidence demonstrated in the discussion.
9. PilotDriven Flight Discipline is an adapted competency, not an ICAO or QCAA core competency.
10. The reply must contain the minimum sufficient detail and avoid repetition or academic chatter.
11. Helpyou must learn from the pilot while keeping raw pilot wording separate from AI interpretation.
12. Pilot memory, pilot reports and AI possibilities cannot become ODSS or authoritative operational evidence.

## Rev20 private source bundle

The raw manuals are stored privately and are not committed to GitHub. Review the metadata and fixture contracts in:

```text
docs/helpyou/HELPYOU_SOURCE_BUNDLE_SQ23_A350_REV20.md
integration/helpyou/fixtures/sq23_source_manifest_rev20.json
integration/helpyou/fixtures/sq23_oei_etp1_1d.json
integration/helpyou/helpyou_core/source_registry.py
```

The bundle includes, among other sources:

- SQ23 Lido CFP OFP 108/0/1;
- SIA A350 FCOM Rev20, 06.05.26;
- SIA A350 QRH Rev18, 03.04.25;
- A350 SIA FCTM Vol2 Rev1.0, 30.04.26;
- SIA A350 SQNP/SQSP/SQI Rev20, 06.05.26;
- ANR 121 Fifth Schedule fatigue material;
- training and study aids that are expressly non-controlling;
- Endsley, Rasmussen/Leveson, QCAA CBTA and Axiomatic Design sources.

## Golden case

- SQ23 KJFK-WSSS, 25.07.26;
- A350-941, 9V-SGE;
- stable OEI discussion at ETP1-1D, ACTM 03:18;
- CYQX and EINN initially presented as unranked conditional options;
- landing performance assumed suitable only for the prototype and explicitly labelled `scenario_assumption`;
- actual landing suitability remains conditional on approved EFB output, current weather, NOTAM, runway/approach status, aircraft condition and operator policy.

## Adversarial review questions

### A. Source authority and currency

- Can FCOM Rev18A still leak into a Rev20 answer or fixture?
- Is FCOM Rev20 clearly the primary technical source?
- Can QRH Rev18 be used without its explicit currency/effectivity reconciliation?
- Can SQNP, SQSP, SQI or FCTM override FCOM, QRH, OM or MEL outside their authority scope?
- Can a training guide, study guide, change summary or secondary SA review be promoted to operational authority?
- Can an old or incomplete source be treated as current because its file is present?
- Does every source have machine-readable permitted and prohibited uses?

### B. Proprietary-data boundary

- Can any raw manual, CFP page, copyrighted table or substantial extract enter GitHub, CI artifacts, logs, exception messages or test snapshots?
- Does the handoff ZIP accidentally package private source bytes or private storage identifiers?
- Are metadata records sufficient to reproduce a test without exposing source content?

### C. Landing-performance boundary

- Can Code 4E be interpreted as proof of A350 landing suitability?
- Can the prototype performance assumption be transformed into an authoritative claim by the response planner?
- Does the fixture require actual ECAM/MEL/CDL selection and approved EFB computation before production use?
- Can LD, FLD, RLD, LDA or ROW/ROP concepts be conflated?
- Is the teacher forced to remain conditional while approved performance evidence is absent?

### D. OEI scenario definition

- Can a stable OEI case silently expand into engine fire, severe damage, vibration, fuel leak or another condition without rerouting the procedure and options?
- Does the system distinguish engine-failure diagnosis from engine-damage assessment?
- Can distance alone determine the diversion choice?
- Are terrain, estimated-time-of-use weather, runway/approach, fuel, operational support and fallback retained as independent requirements?

### E. EDTO and weather

- Does Chat recalculate EDTO, ACTM, projected arrival, weather applicability or minima instead of consuming ODSS?
- Can CFP planning weather be presented as current operational weather?
- Are BECMG/TEMPO/PROB transitions and uncovered forecast periods preserved?
- Can a listed alternate be promoted to suitable without current operational verification?

### F. Cognitive and teaching models

- Does Axiomatic Design remain the conversation and teaching architecture rather than an academic section shown to the pilot?
- Does the facilitator ask the first material missing question and then stop when sufficient evidence exists?
- Can Endsley be misused to diagnose tunnel vision or quantify SA from text alone?
- Can Rasmussen reward higher abstraction regardless of task need?
- Can CBTA infer handling, callouts, checklist execution or crew behaviour not actually observed?
- Is Flight Discipline always labelled PilotDriven-adapted?
- Can fatigue material appear as irrelevant boilerplate, or can Helpyou diagnose fatigue without evidence?

### G. Learning and memory

- Can a pilot correction or repeated pilot report be promoted into the operational source registry?
- Can raw pilot wording be overwritten by AI interpretation?
- Can private memory contaminate another pilot's answer or an ODSS output?
- Can a superseded memory record remain active without a visible conflict?

### H. Human factors and minimum detail

- Does the response expose every internal model rather than only the material issue?
- Can the interface repeat obvious data, over-interrogate the pilot or overload working memory?
- Are source, fact, assumption, inference, decision and developmental feedback structurally distinguishable?
- Does the final answer state the decision focus, material conditions and change trigger before background explanation?

### I. Test adequacy

For every material finding, propose a deterministic regression test. Specifically look for missing tests covering:

- QRH currency mismatch;
- training-source promotion;
- private-byte leakage;
- FCOM revision conflict;
- scenario mutation from stable OEI to fire/severe damage;
- performance-assumption promotion;
- fatigue overactivation;
- source-bundle mismatch between fixture and manifest;
- cognitive-model activation before pilot reasoning;
- answer verbosity and repeated sections.

## Required output format

For each finding:

```text
Finding ID:
Severity: Critical / High / Medium / Low
Category:
Exact file and function:
Observed problem:
Concrete failure scenario:
Affected Customer Need / Functional Requirement / constraint:
Why existing tests do not catch it:
Proposed regression test:
Suggested correction:
Confidence:
Fact, inference or design judgement:
```

Then provide:

1. top five release blockers;
2. missing-test matrix;
3. product-owner decisions required;
4. internal requirement inconsistencies;
5. recommendation: reject, revise, or ready for controlled prototype testing.

Do not merge or rewrite the branch. Return findings against the exact current PR head SHA.
