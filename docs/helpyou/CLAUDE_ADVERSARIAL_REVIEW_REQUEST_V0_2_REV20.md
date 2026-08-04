# Claude Adversarial Review Request — Helpyou Core v0.2 OM32/Rev20 Refresh

**Repository:** `Easyeye123/pilotdriven-ODSS`  
**Pull request:** `#32`  
**Branch:** `feature/helpyou-core-v0.2`  
**Review target:** Use the current PR head shown by GitHub after the OM32 refresh. Do not use the superseded SHAs `8083106b...` or `9bf0abd1...`.

## Role

Act as an independent aviation-software, evidence-governance, cognitive-engineering and human-factors critic. Find failure paths. Do not rewrite PilotDriven into a formal training/checking system, and do not assume the architecture is safe merely because tests pass.

## Product boundaries

1. Helpyou is an individual pilot teaching and decision-support aid.
2. It is not an approved airline LOFT, EBT, checking or licensing system.
3. ODSS exclusively owns Lido CFP parsing and deterministic flight analysis.
4. Helpyou may consume an immutable ODSS baseline but may not recalculate ODSS findings in Chat.
5. Axiomatic Design governs request decomposition, independent decision requirements, option structure and the teaching reply.
6. Endsley examines present picture, operational meaning and projection ahead.
7. Rasmussen examines indication, system behaviour, capability, safety constraint, purpose, action and feedback across part-to-whole scope.
8. CBTA provides developmental observations only from evidence demonstrated in the discussion.
9. PilotDriven Flight Discipline is adapted, not an ICAO/QCAA core competency.
10. The reply must contain minimum sufficient detail without repetition or academic chatter.
11. Helpyou learns from the pilot while keeping raw wording separate from AI interpretation.
12. Pilot memory, pilot reports and AI possibilities cannot become ODSS or authoritative evidence.

## Review sources in the repository

The raw manuals remain in private storage. Review these metadata, policy and fixture records:

```text
docs/helpyou/HELPYOU_SOURCE_BUNDLE_SQ23_A350_REV20.md
docs/helpyou/HELPYOU_OM_FCTM_AUTHORITY_AND_SQ23_TEST_BASIS.md
integration/helpyou/fixtures/sq23_source_manifest_rev20.json
integration/helpyou/fixtures/sq23_oei_etp1_1d.json
integration/helpyou/helpyou_core/source_registry.py
integration/helpyou/helpyou_core/document_priority.py
```

## Golden case

- SQ23 KJFK-WSSS, 25.07.26;
- A350-941, 9V-SGE;
- stable OEI at ETP1-1D, ACTM 03:18;
- CYQX and EINN initially unranked;
- FCOM Rev20 supplies the landing-performance method;
- airport-specific landing performance is accepted only as an explicit golden-test assumption;
- CFP NOTAMs and CFP-declared current MEL items are accepted as valid only for the frozen test;
- CFP weather is used as scenario weather within the printed validity and projected arrival time;
- no fire, severe damage or additional degradation is introduced.

## SIA OM document-authority policy to attack

The implementation claims to preserve the OM 12.1.1.1 sequence:

1. INTAM;
2. FSI;
3. MEL;
4. OM Vol A / FCOM / Jeppesen Reference Text / SQNP / SQSP;
5. SEP;
6. FCTM / Technical Bulletin / Airport Briefing / Circular;
7. Crew Administration / Flight Security Procedures.

It also claims that:

- Certificate of Airworthiness, ANO/ANR and AFM remain mandatory constraints;
- lower-authority documents may impose more restrictive requirements;
- same-level sources are not given invented sub-priority;
- QRH/CDL/SQI are linked Volume B components without a separately invented rank;
- latest revision is used where copies differ;
- installed-EFB AFM/MEL/CDL copies are primary operational references.

Challenge whether the code actually enforces those claims or merely documents them.

## Adversarial review questions

### A. OM priority and source authority

- Can FCTM, a study guide or cognitive source override MEL, OM or FCOM?
- Can the resolver incorrectly treat the hierarchy as a total order and invent priority within group 4?
- Can QRH, CDL or SQI be assigned a rank not stated by the OM?
- Can a lower-authority but more restrictive requirement be discarded?
- Can an older but higher-ranked document silently override a newer applicable document without version reconciliation?
- Does the installed-EFB AFM/MEL/CDL primary-copy rule apply only to those documents?
- Can a same-level conflict be resolved without source-scope or SME review?

### B. Source authority and currency

- Can FCOM Rev18A leak into the Rev20/OM32 fixture?
- Is OM Rev32 the controlling operator-policy source?
- Can QRH Rev18 be used without currentness/effectivity reconciliation?
- Can source presence be mistaken for currency?
- Does every source have permitted and prohibited uses?

### C. Proprietary-data boundary

- Can raw manuals, CFP pages, copyrighted tables or substantial extracts enter GitHub, CI artifacts, logs, exceptions or snapshots?
- Does the handoff ZIP include private storage paths or source bytes?

### D. Landing-performance boundary

- Can Code 4E become proof of A350 landing suitability?
- Can the authoritative FCOM method be conflated with the assumed airport result?
- Can the system fabricate LDA, LD, FLD, RLD or runway-required values?
- Can the response describe an “approved EFB result” when no airport-specific result exists?
- Does the golden test remain conditional/assumption-labelled while still allowing the decision flow to proceed?

### E. NOTAM and MEL assumptions

- Can the frozen-test NOTAM assumption leak into another flight, date or live operation?
- Can “MEL items are valid” be interpreted as waiving their operational conditions?
- Can a new inflight defect be incorrectly processed as a dispatch-MEL eligibility question?
- Can the assumptions be promoted to `authoritative` or `support_verified`?

### F. OEI, EDTO and diversion

- Can a stable OEI case silently mutate into fire, severe damage, vibration, fuel leak or another condition without changing procedure and urgency?
- Can distance alone determine the diversion choice?
- Are terrain, weather, facilities, runway/approach, RFFS, fuel, workload, landing method and fallback independent requirements?
- Does the system preserve Commander discretion to select another more appropriate airport?
- Can planning weather be presented as live operational weather outside the frozen test?

### G. Cognitive and teaching models

- Does Axiomatic Design remain the hidden conversation/teaching architecture rather than academic output?
- Does the facilitator ask the first material missing question and stop when enough information exists?
- Can Endsley diagnose tunnel vision or quantify SA from text alone?
- Can Rasmussen reward higher abstraction regardless of task need?
- Can CBTA infer handling, callouts or crew performance not observed?
- Is Flight Discipline always labelled PilotDriven-adapted?
- Can fatigue material appear as irrelevant boilerplate?

### H. Learning, memory and human factors

- Can pilot memory contaminate authoritative or ODSS output?
- Can raw wording be overwritten by interpretation?
- Can the response expose all internal models, repeat obvious facts or over-interrogate?
- Are fact, assumption, inference, decision and developmental feedback structurally distinct?

### I. Test adequacy

For every material finding, propose a deterministic regression test. Specifically attack:

- exact OM priority groups;
- same-level conflict handling;
- lower-authority more-restrictive rules;
- unranked QRH/CDL/SQI treatment;
- OM/FCOM/FCTM scope leakage;
- FCOM method versus assumed result;
- NOTAM/MEL assumption leakage;
- private-byte leakage;
- stable-OEI mutation;
- fatigue overactivation;
- source-bundle/fixture mismatch;
- cognitive activation before pilot reasoning;
- repeated or excessive answer sections.

## Required output

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
