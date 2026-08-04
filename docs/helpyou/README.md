# PilotDriven Helpyou

**Status:** Product and integration baseline  
**Version:** 1.0  
**Date:** 04.08.26

Helpyou is a two-way, source-governed aviation decision-support and individual learning system.

It has two product sections:

1. **Chat & Learn** — interrogates the pilot, answers questions, supports decision discussions, reviews stated reasoning and learns persistently from the pilot.
2. **Compile & Data Hub** — compiles controlled manuals and operational sources into versioned knowledge objects for Helpyou and the ODSS CFP analyser.

ODSS remains the sole owner of deterministic Lido CFP analysis. Helpyou consumes ODSS results; it does not duplicate or reinterpret the ODSS engines.

## Documents

- [`HELPYOU_SYSTEM_REQUIREMENTS_V1.md`](HELPYOU_SYSTEM_REQUIREMENTS_V1.md) — Customer Needs, constraints, functional requirements, design parameters, process variables and interface.
- [`HELPYOU_SCENARIO_AND_COGNITIVE_PROTOCOL_V1.md`](HELPYOU_SCENARIO_AND_COGNITIVE_PROTOCOL_V1.md) — CFP-grounded LOFT-style discussion, option generation, Endsley, Rasmussen, CBTA and Flight Discipline.
- [`HELPYOU_DATA_CONTRACTS_V1.md`](HELPYOU_DATA_CONTRACTS_V1.md) — source, claim, routing, memory and scenario data contracts.
- [`HELPYOU_CORE_V0_2_VERTICAL_SLICE.md`](HELPYOU_CORE_V0_2_VERTICAL_SLICE.md) — deterministic guided-decision orchestrator and SQ23 golden test case.
- [`HELPYOU_SOURCE_BUNDLE_SQ23_A350_REV20.md`](HELPYOU_SOURCE_BUNDLE_SQ23_A350_REV20.md) — private Rev20 source registration, authority precedence and open gaps.
- [`CLAUDE_ADVERSARIAL_REVIEW_REQUEST_V0_2_REV20.md`](CLAUDE_ADVERSARIAL_REVIEW_REQUEST_V0_2_REV20.md) — refreshed independent review request for the Rev20 source-bound prototype.
- [`../../integration/helpyou/README.md`](../../integration/helpyou/README.md) — deterministic reference policy and tests.
- [`../../integration/helpyou/README_CORE_V0_2.md`](../../integration/helpyou/README_CORE_V0_2.md) — Core v0.2 package and test instructions.

## Governing doctrine

> Route the request first. Use the correct specialist engine. Verify every authoritative claim. Let Axiomatic Design teach the result. Use Rasmussen, Endsley and CBTA only when actual pilot reasoning is available. Learn from the pilot without confusing experience with authority.

## Non-negotiable boundaries

- All authoritative replies are based on current, applicable and claim-supporting citations or validated data.
- Citation dates use `DD.MM.YY`; document dates use `eff`.
- Pilot experience and AI possibilities are visibly segregated from authoritative information.
- Pilot memory never becomes ODSS operational evidence.
- A Lido CFP upload routes to ODSS and does not trigger a cognitive review by itself.
- A CFP-grounded scenario must use the same ODSS weather-selection and validity protocol as the CFP analysis.
- The default reply is the smallest complete answer at the correct operational level.
- Proprietary manuals and CFP bytes remain in private storage; GitHub contains metadata and synthetic or derived fixtures only.
