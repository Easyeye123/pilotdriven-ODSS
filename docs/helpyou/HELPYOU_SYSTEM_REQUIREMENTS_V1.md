# Helpyou System Requirements v1

**Status:** Proposed product baseline  
**Date:** 30.07.26

## 1. Product purpose

Helpyou is an individual pilot decision-support and teaching aid. It is not an airline training programme, approved LOFT/LOE platform, simulator instructor, operator authority or replacement for approved manuals and operational control.

Helpyou must:

- understand and interrogate the pilot's actual need;
- route each request to the correct specialist process;
- give a source-backed answer at the correct level of detail;
- expose material assumptions, dependencies and decision gates;
- review stated pilot reasoning when requested or relevant;
- learn persistently from the pilot under explicit evidence and privacy controls;
- compile authoritative source material into reusable knowledge for ODSS and Chat.

## 2. Customer Needs

Customer Needs are stated in the pilot's voice and remain solution-neutral.

| ID | Customer Need |
|---|---|
| CN1 | Understand what I am really asking without making me select a technical source mode. |
| CN2 | Ask only the questions needed to resolve intent, applicability, assumptions or reasoning. |
| CN3 | Give me the answer that applies to my operator, aircraft, configuration, date and situation. |
| CN4 | Show where every material authoritative statement came from. |
| CN5 | Separate authoritative information, synthesis, pilot experience, AI possibility, dispute and unknowns. |
| CN6 | Explain why the answer follows and which condition changes it. |
| CN7 | When I explain my reasoning, identify the material safety, Flight Discipline, knowledge and situational-awareness gap without academic language. |
| CN8 | Remember what I teach Helpyou and use it appropriately later. |
| CN9 | Show me what was stored and let me correct, supersede, share or delete it. |
| CN10 | Compile several manuals without losing conditions, exceptions, conflicts, precedence or revision status. |
| CN11 | Supply controlled, reproducible knowledge to the ODSS CFP analyser. |
| CN12 | Give me the minimum sufficient detail without obvious repetition or unnecessary chatter. |

## 3. Hard constraints

| ID | Constraint |
|---|---|
| C1 | Every authoritative substantive claim has a current, applicable and claim-supporting reference or validated data source. |
| C2 | Citation dates use `DD.MM.YY`; document dates use `eff`. |
| C3 | Absence of qualified evidence fails closed. No general-AI substitute may appear as authority. |
| C4 | Evidence classes remain visibly separate. |
| C5 | ODSS is the sole owner of deterministic Lido CFP analysis. |
| C6 | Pilot memory and pilot experience are prohibited as ODSS evidence inputs. |
| C7 | Rasmussen, Endsley and CBTA activate only when pilot reasoning is available. |
| C8 | CBTA output is developmental and discussion-specific, not an official operator or licensing grade. |
| C9 | Flight Discipline is a PilotDriven adapted competency, not a claim that it is a tenth ICAO/QCAA core competency. |
| C10 | Every pilot turn passes through memory classification; durable storage remains governed, visible and user-controllable. |
| C11 | The pilot's original wording is stored separately from the AI interpretation. |
| C12 | The same inputs, source snapshot and policy version reproduce the same routed analysis record. |

## 4. Top-level Functional Requirements

Functional Requirements describe what Helpyou must achieve, not a specific interface or technology.

| FR | Functional Requirement | Required result |
|---|---|---|
| FR1 | Understand and segregate the pilot's need | One or more independent routed subrequests |
| FR2 | Establish a supported answer basis | Applicable evidence and specialist-analysis package |
| FR3 | Conduct a clear teaching dialogue | Minimum-sufficient answer, questions, conditions and references |
| FR4 | Develop the pilot's reasoning when demonstrated | Operational cognitive review and developmental evidence |
| FR5 | Learn from and remember the pilot | Versioned, contextual and controllable memory |
| FR6 | Transform controlled sources into maintained knowledge | Published knowledge objects with applicability and conflicts |
| FR7 | Supply verified knowledge to specialist engines | Immutable snapshots and ODSS-facing data service |

## 5. Functional decomposition

### FR1 — Understand and segregate the pilot's need

- identify request type;
- detect Lido CFP and other attachments;
- resolve operator, aircraft, date and scenario context;
- identify the pilot's underlying objective;
- distinguish a question from a contribution or correction;
- split mixed requests;
- determine whether cognitive layers are applicable.

### FR2 — Establish a supported answer basis

- identify the source class needed for each requirement;
- retrieve and validate applicable evidence;
- resolve currency, effectivity and precedence;
- invoke ODSS, Compiler, authoritative retrieval or deterministic calculation;
- detect conflicts and missing conditions;
- verify that each cited passage supports the claim.

### FR3 — Conduct a clear teaching dialogue

- answer first;
- use Axiomatic Design to separate independent matters and order dependent matters;
- expose coupled variables rather than hide them;
- state material conditions and the decision gate;
- use only the detail needed for understanding, verification and correct application;
- place deeper explanation behind expandable sections.

### FR4 — Develop the pilot's reasoning

Active only when the pilot provides reasoning.

- preserve the exact pilot statement;
- apply the operational Endsley check: Picture now, What it means, Projection ahead, Widen the scan, Decision gate;
- apply Rasmussen through pilot language: information, system behaviour, capability, safety margin, objective, action and feedback;
- map only supported evidence to relevant CBTA competencies;
- include the PilotDriven Flight Discipline competency;
- state what was not observed;
- provide no more than one or two material development targets.

### FR5 — Learn from and remember the pilot

- capture experience, correction, technique, hypothesis, reasoning evidence and preferences;
- preserve raw wording and AI interpretation separately;
- assign context, provenance and evidence class;
- default to private memory;
- allow correction, supersession, sharing and deletion;
- retrieve only when contextually relevant;
- display what Helpyou learned.

### FR6 — Transform controlled sources into maintained knowledge

- register document owner, class, revision, `eff`, applicability and hash;
- preserve text, tables, notes, figures and cross-references;
- compile atomic claims across documents;
- retain conditions, exceptions and rationale;
- detect conflict and precedence;
- review, publish, supersede and invalidate affected downstream objects.

### FR7 — Supply verified knowledge to specialist engines

- publish immutable source snapshots;
- provide structured knowledge objects through an internal API;
- include applicability and unresolved-item status;
- prohibit pilot-memory retrieval;
- record the snapshot used for every CFP analysis.

## 6. Design Parameters

| DP | Design Parameter | Owns |
|---|---|---|
| DP1 | Request and Elicitation Orchestrator | FR1 |
| DP2 | Evidence and Specialist Analysis Orchestrator | FR2 |
| DP3 | Axiomatic Response Composer | FR3 |
| DP4 | Cognitive Development Engine | FR4 |
| DP5 | Pilot Memory and Knowledge Commons | FR5 |
| DP6 | Authoritative Compiler and Knowledge Graph | FR6 |
| DP7 | Publication Snapshot and Knowledge API | FR7 |

The required high-level sequence is:

```text
Understand → establish evidence → teach → review reasoning when applicable → store governed memory → reuse later
```

The current answer basis must not be retroactively altered by a new pilot-memory write.

## 7. Request routing

| Request | Specialist owner | Rasmussen | Endsley | CBTA |
|---|---|---:|---:|---:|
| Lido CFP upload | ODSS | Off | Off | Off |
| Multi-manual compilation | Compiler | Off | Off | Off |
| Direct procedure or limitation lookup | Authoritative Retrieval | Off | Off | Off |
| Calculation | Deterministic Calculator | Off | Off | Off |
| Decision factors only | Decision Teaching | Off until reasoning is given | Off until reasoning is given | Off by default |
| Pilot reasoning review | Decision Teaching | On | On | Developmental |
| Pilot experience or correction | Memory/Knowledge Commons | Normally off | Off | Off |
| Mixed request | Split between specialist owners | Relevant branch only | Relevant branch only | Relevant branch only |

## 8. Evidence classes

- `AUTHORITATIVE`
- `SUPPORTED_SYNTHESIS`
- `CORROBORATED_PILOT_EXPERIENCE`
- `SINGLE_PILOT_REPORT`
- `AI_POSSIBILITY`
- `DISPUTED`
- `SUPERSEDED`
- `UNSUPPORTED`

Multiple pilot reports can increase corroboration but cannot convert experience into an approved procedure.

## 9. Citation contract

Normal form:

```text
[SIA | OM-B | Rev 18 | eff 13.08.25 | §4.6.2 | p.214]
```

The passage need not be reproduced unless exact wording is material. Internally, every claim retains source-to-claim traceability and applicability.

## 10. Minimum-sufficient-detail policy

Helpyou shall stop adding content once the pilot can understand the answer, verify its authority and apply it correctly.

Hardcoded response rules:

- answer first;
- do not restate the question unless clarification is needed;
- state each material fact once;
- do not explain standard aviation terminology unless requested or misunderstood;
- show only CBTA competencies supported by evidence;
- surface only the Rasmussen or Endsley gap that affects the result;
- avoid a closing summary that repeats the opening answer;
- use progressive disclosure for technical detail and source extracts.

## 11. Interface

### Chat & Learn

- persistent context bar: operator, aircraft, date, CFP case and source snapshot;
- automatic route label, correctable by the pilot;
- conversation area;
- answer-status badge;
- compact sources and applicability panel;
- optional `Review my reasoning` flow;
- `What Helpyou learned` panel with memory controls.

No global Manual/Official/Experience/General-AI mode switch is permitted.

### Compile & Data Hub

- document registry;
- revision and supersession status;
- functional compilation workspace;
- source comparison and conflict viewer;
- claim-to-source review;
- publish/unpublish workflow;
- ODSS data-coverage and unresolved-gap dashboard.

## 12. Process Variables

- labelled pilot-request routing set;
- controlled document-ingestion pipeline;
- structured extraction preserving tables and footnotes;
- applicability and precedence rules;
- claim-verification service;
- Axiomatic Design response planner;
- SME-reviewed Endsley/Rasmussen/CBTA mapping library;
- memory-governance service;
- publication workflow;
- regression and calibration suite.

## 13. Acceptance baseline

1. Lido CFP uploads route to ODSS.
2. Ordinary CFP analysis does not activate cognitive review.
3. Mixed requests are split.
4. Authoritative claims without verified citations fail closed.
5. Superseded sources cannot support current claims.
6. Pilot experience cannot enter ODSS findings.
7. Flight-specific scenario options require an ODSS-processed CFP.
8. Scenario weather uses the same ODSS validity logic.
9. Cognitive review uses only evidence in the discussion.
10. The pilot can inspect and control stored memory.
11. The default answer contains no unnecessary repetition.
12. The source snapshot used by ODSS is reproducible.

## 14. Reference baseline

- `[QCAA | Competency Based Training and Assessment | 1st Ed | eff 22.04.21 | pp.15–18]`
- `[Endsley | Toward a Theory of Situation Awareness in Dynamic Systems | Human Factors 37(1) | 1995 | pp.32–64]`
- `[Leveson | Rasmussen's Legacy: A Paradigm Change in Engineering for Safety | 2016]`
- `[Suh | Axiomatic Design | Independence and Information Axioms]`
