# Helpyou SQ23 A350 Rev20 Source Bundle

**Status:** Private source registration for controlled prototype testing  
**Bundle ID:** `HELPYOU-SQ23-A350-REV20-04AUG26`  
**Registered:** 04.08.26  
**GitHub content rule:** Metadata, schemas and synthetic/derived fixtures only. No proprietary manual or CFP bytes.

## 1. Purpose

This bundle refreshes the Helpyou Core v0.2 golden test case with the supplied A350 Rev20 and operator documents while preserving the ODSS, evidence and confidentiality boundaries.

Golden case:

- SQ23 KJFK-WSSS, 25.07.26;
- A350-941, 9V-SGE;
- Lido CFP OFP 108/0/1;
- stable one-engine-inoperative discussion at ETP1-1D, ACTM 03:18;
- candidate EDTO aerodromes CYQX and EINN.

The source registry is in:

```text
integration/helpyou/fixtures/sq23_source_manifest_rev20.json
```

## 2. Private source storage

The files are registered in the private PilotDriven/Helpyou source library under:

```text
/PilotDriven/Helpyou/Source Library/SQ23 A350 Rev20 Test Bundle
/PilotDriven/Helpyou/Source Library/Cognitive and Design Foundations
```

The GitHub repository records source identity, revision, authority, currency status, permitted use and prohibited use. It does not contain the source PDFs.

## 3. Operational source precedence

For the SQ23 scenario, Helpyou applies the following precedence within each source's stated scope:

1. Current approved operator and aircraft controlled material: FCOM, QRH, OM, MEL/CDL, SQNP, SQSP, SQI and applicable FCTM.
2. ODSS-validated flight-specific facts from the Lido CFP, current weather, NOTAM, AIP/chart and approved performance data.
3. Applicable regulations and approvals.
4. Controlled operator training and technique material, within its scope and without overriding the sources above.
5. Training syntheses, study guides and change summaries as navigation aids only.
6. Endsley, Rasmussen, CBTA and Axiomatic Design as teaching and cognitive-engineering models only. They do not generate aircraft procedures.
7. Pilot experience and adversarial AI material as separately labelled, non-authoritative inputs.

## 4. Registered operational documents

| Source | Revision/date | Registry role | Permitted use | Required safeguard |
|---|---|---|---|---|
| SQ23 Lido CFP | OFP 108/0/1, 25.07.26 | Controlled flight source | Route, ACTM, ETP, planned fuel, planning weather and EDTO pair through ODSS | Planning data is not current operational data |
| SIA A350 FCOM | Rev 20, 06.05.26 | Controlled operational | Systems, limitations, abnormal procedures and performance | Primary technical source; private and claim-cited |
| SIA A350 QRH | Rev 18, 03.04.25 | Controlled operational | Quick-reference procedure verification | Currency and aircraft effectivity must be reconciled because it predates the Rev20 bundle |
| A350 SIA FCTM Vol 2 | Rev 1.0, 30.04.26 | Controlled operator guidance | OEI landing, engine fire, EDTO, CRM, LOFT and EBT teaching context | Must not override FCOM, QRH, OM or MEL |
| SIA A350 SQNP | Rev 20, 06.05.26 | Controlled operator guidance | SOP, task sharing, briefing and phase preparation | Apply aircraft and operator effectivity |
| SIA A350 SQSP | Rev 20, 06.05.26 | Controlled operator guidance | Alternates, communications, navigation, performance, special operations and CDL context | Do not promote an airport list to current suitability |
| SIA A350 SQI | Rev 20, 06.05.26 | Controlled operator guidance | Cruise briefing aid and communication support | Cannot override procedure or performance sources |
| ANR 121 Fifth Schedule | Informal consolidation in force 01.01.23 | Regulatory context | Fatigue constraints when fatigue is material to the scenario | Verify current legal status; no automatic fatigue diagnosis |

## 5. Supporting material

The following sources may help navigation, teaching or change identification but do not independently support an operational conclusion:

- A350 FLS/F-APP Training Reference, Issue 1 Rev 6;
- A350 FCOM Rev20 Limitations Study Guide;
- A350 Main FCOM/FCTM Changes, Oct 2025;
- secondary situational-awareness review;
- human-information-processing lecture material;
- introductory Axiomatic Design summary;
- prior PilotDriven decision-process proposal used as adversarial input.

A supporting source may point Helpyou to a controlling section. The controlling section must then be retrieved and verified before the claim is promoted.

## 6. Cognitive and teaching foundations

The private source library also contains:

- Endsley, *Toward a Theory of Situation Awareness in Dynamic Systems*;
- Leveson, *Rasmussen's Legacy*;
- QCAA Competency Based Training and Assessment;
- fuller Axiomatic Design lecture material;
- human-information-processing material.

Their permitted functions are deliberately separate:

- Endsley: present picture, operational meaning and projection ahead;
- Rasmussen: indication-to-capability-to-safety-purpose structure and part-to-whole scope;
- CBTA: developmental evidence from what the pilot actually states;
- Axiomatic Design: request decomposition, independent decision requirements, option comparison, teaching structure and minimum sufficient detail.

## 7. Rev20 changes to the golden fixture

The previous fixture cited A350 FCOM Rev18A. It is replaced by:

```text
[SIA | A350 FCOM | Rev 20 | eff 06.05.26 | PER-LDG-20 / PER-LDG-50]
```

The landing-performance boundary remains unchanged:

- diversion or an in-flight failure requires an approved in-flight landing-performance computation;
- the test instruction to assume landing performance suitable is retained as a visible `scenario_assumption`;
- Code 4E is not treated as proof of A350 landing performance;
- the teaching result remains conditional until approved EFB output is supplied.

The FCTM EDTO material is added to the teaching basis so that option generation does not reduce suitability to distance alone. Estimated-time-of-use weather, diversion procedures and operational-control considerations remain visible.

## 8. Open source gaps

The bundle is not a production-complete operator library. The following remain required:

1. current SIA OM-A and OM-B diversion, commander-authority and fuel-policy sections;
2. current SIA A350 MEL/CDL and effectivity for 9V-SGE;
3. current FCTM Volume 1 where cited;
4. any separate controlled EDTO operational-control/diversion policy;
5. approved EFB landing-performance outputs for CYQX and EINN;
6. current charts/AIP, NOTAMs and operational weather at projected arrival;
7. current OEB, TAB and temporary documentary-unit applicability.

Helpyou must fail closed or state a conditional result where one of these gaps affects the decision.

## 9. Acceptance requirements added by this refresh

- Rev18A FCOM citations must not remain in the SQ23 Rev20 fixture.
- Training aids cannot be marked controlling.
- Cognitive models cannot support aircraft-technical claims.
- QRH Rev18 must carry a currency-review flag.
- Raw proprietary files must never appear in the GitHub tree or release bundle.
- Source precedence and authority scope must be machine-testable.
- Fatigue prompts activate only when fatigue is a material scenario input.
- The current source-bundle ID must be recorded in every reproducible SQ23 test result.
