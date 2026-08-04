# Helpyou SQ23 A350 Rev20 / OM32 Source Bundle

**Status:** Private source registration for controlled prototype testing  
**Bundle ID:** `HELPYOU-SQ23-A350-REV20-OM32-04AUG26`  
**Registered:** 04.08.26  
**GitHub content rule:** Metadata, schemas and derived/synthetic fixtures only. No proprietary manual or CFP bytes.

## 1. Golden case

- SQ23 KJFK-WSSS, 25.07.26;
- A350-941, 9V-SGE;
- Lido CFP OFP 108/0/1;
- stable OEI discussion at ETP1-1D, ACTM 03:18;
- candidate EDTO aerodromes CYQX and EINN.

The complete OM/FCTM review and test basis is recorded in:

```text
docs/helpyou/HELPYOU_OM_FCTM_AUTHORITY_AND_SQ23_TEST_BASIS.md
```

Machine-readable registration:

```text
integration/helpyou/fixtures/sq23_source_manifest_rev20.json
integration/helpyou/helpyou_core/source_registry.py
integration/helpyou/helpyou_core/document_priority.py
```

## 2. Private source storage

```text
/PilotDriven/Helpyou/Source Library/SQ23 A350 Rev20 Test Bundle
/PilotDriven/Helpyou/Source Library/Cognitive and Design Foundations
```

The repository records source identity, revision, authority scope, currency, permitted use and prohibited use. It does not contain the PDFs.

## 3. OM-grounded document authority

The source resolver now implements the exact descending operational sequence in SIA OM Rev 32, 12.1.1.1:

1. INTAMs;
2. Flight Staff Instructions;
3. MEL;
4. OM Vol A / FCOM / Jeppesen Reference Texts / SQNP / SQSP;
5. SEP;
6. FCTM / Technical Bulletins / Airport Briefings / Circulars;
7. Crew Administration / Flight Security Procedures.

Additional rules:

- Certificate of Airworthiness, ANO/ANR, AFM and OM provisions remain mandatory;
- a valid lower-authority document may impose a more restrictive requirement;
- same-level documents are not given an invented sub-priority;
- QRH, CDL, SQI, weight-and-balance and fuelling material are linked Volume B components whose scope must be reconciled explicitly;
- use the latest revision where iPad and installed-EFB copies differ;
- installed-EFB AFM, MEL and CDL copies are the primary operational references.

## 4. Registered controlled sources

| Source | Revision/date | Role in the golden case |
|---|---|---|
| SIA OM | Rev 32, eff 01.04.26 | Operational policy, document priority, EDTO, OEI diversion, nearest-suitable criteria, fuel and Commander authority |
| SIA A350 FCOM | Rev 20, eff 06.05.26 | Aircraft systems, procedures, limitations and approved landing-performance method |
| SIA A350 QRH | Rev 18, 03.04.25 | Quick-reference procedures, subject to currentness/effectivity reconciliation |
| A350 SIA FCTM Vol 2 | Rev 1.0, eff 30.04.26 | Technique, EDTO teaching, LOFT context, task sharing and Flight Discipline prompts; priority group 6 |
| SIA A350 SQNP | Rev 20, eff 06.05.26 | Normal SOP and task sharing |
| SIA A350 SQSP | Rev 20, eff 06.05.26 | Supplementary operations and alternate context |
| SIA A350 SQI | Rev 20, eff 06.05.26 | Crew-support and communication information |
| SQ23 Lido CFP | OFP 108/0/1, 25.07.26 | ODSS flight baseline, route, timing, fuel, scenario weather, NOTAM/MEL snapshot and EDTO pair |

Training references, study guides, change summaries and cognitive sources remain non-operational or supporting within their registered scopes.

## 5. Landing-performance boundary

The FCOM Performance section supplies the authoritative method:

- RLD/LD/FLD definitions;
- approved EFB inflight computation;
- ECAM/MEL/CDL selection;
- LD-versus-LDA safeguard where the factor is disregarded in an emergency.

The FCOM does not supply a precomputed CYQX or EINN runway result for this case. The golden fixture therefore keeps the result as an explicit test assumption and contains no fabricated LDA, LD, FLD, RLD or runway-required value.

Code 4E is not used as proof of landing-distance suitability.

## 6. Frozen-test assumptions

For this SQ23 desktop case only:

- CFP NOTAMs are accepted as current and valid;
- CFP-declared current MEL items and their operational conditions are accepted as valid;
- landing performance is accepted as suitable under the FCOM method;
- CFP weather is used as scenario weather within its validity and projected arrival time;
- the event remains stable OEI without fire, severe damage or additional degradation.

These are labelled `scenario_assumption`. They remove repetitive test prompts but cannot be promoted to an operational claim or reused for another case.

## 7. Remaining production gaps

- actual A350 MEL/CDL source text and 9V-SGE effectivity;
- FCTM Volume 1 where referenced;
- airport-specific approved EFB inputs/output for a live operation;
- live weather, charts and AIP;
- current OEB/TAB/temporary-document applicability;
- confirmation that QRH Rev 18 remains current for the intended operational date.

## 8. Acceptance rules

- OM priority groups are machine-testable.
- FCTM cannot override OM, FCOM or MEL.
- FCOM method and assumed airport result remain separate.
- NOTAM and MEL validity remain test assumptions.
- No proprietary bytes enter GitHub or CI artifacts.
- CYQX and EINN are initially unranked; the pilot must explain the selection before Helpyou teaches the comparison.
