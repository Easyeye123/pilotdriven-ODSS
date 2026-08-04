# Helpyou Core and Policy Reference

This directory contains deterministic policy and the first guided-decision orchestration slice for Helpyou.

It does **not** independently answer aviation questions and does **not** duplicate ODSS. It establishes:

- request segregation;
- specialist-engine ownership;
- cognitive-layer activation gates;
- authoritative evidence requirements;
- the ODSS/pilot-memory boundary;
- minimum-sufficient response sections;
- the PilotDriven citation format;
- mandatory separation of the pilot's raw wording and the AI interpretation;
- metadata-only registration of private controlled sources;
- the SQ23 A350 Rev20 golden scenario.

## Baseline policy tests

```bash
cd integration/helpyou
python3 -m unittest -v test_helpyou_policy.py
```

## Helpyou Core v0.2 tests

```bash
cd integration/helpyou
PYTHONPATH=. python3 -m unittest discover -s tests -v
```

Core v0.2 adds a deterministic CFP-grounded decision orchestrator, Endsley and Rasmussen facilitation, Axiomatic Design option structure, developmental CBTA mapping, governed memory candidates and the SQ23 OEI golden fixture.

## Core v0.2 files

```text
helpyou_core/                       deterministic orchestration modules
helpyou_core/source_registry.py    authority, currency and source-use guard
fixtures/sq23_oei_etp1_1d.json     SQ23 OEI golden scenario
fixtures/sq23_source_manifest_rev20.json
                                   private-source metadata only
tests/                              regression suite
```

See:

- [`README_CORE_V0_2.md`](README_CORE_V0_2.md)
- [`../../docs/helpyou/HELPYOU_CORE_V0_2_VERTICAL_SLICE.md`](../../docs/helpyou/HELPYOU_CORE_V0_2_VERTICAL_SLICE.md)
- [`../../docs/helpyou/HELPYOU_SOURCE_BUNDLE_SQ23_A350_REV20.md`](../../docs/helpyou/HELPYOU_SOURCE_BUNDLE_SQ23_A350_REV20.md)
- [`../../docs/helpyou/CLAUDE_ADVERSARIAL_REVIEW_REQUEST_V0_2_REV20.md`](../../docs/helpyou/CLAUDE_ADVERSARIAL_REVIEW_REQUEST_V0_2_REV20.md)

The implementation is standard-library only. The raw FCOM, QRH, FCTM, SQNP, SQSP, SQI, CFP and other proprietary sources are not committed and remain in private controlled storage.

## Core invariants

1. Lido CFP analysis is owned by ODSS.
2. Rasmussen, Endsley and CBTA do not run on ordinary CFP, lookup, compilation or calculation requests.
3. A CFP-grounded scenario cannot generate flight-specific options until the Lido CFP has been processed by ODSS.
4. Authoritative claims require current, applicable and claim-supporting citations.
5. Pilot experience and AI possibilities never become ODSS evidence.
6. Citation dates use `DD.MM.YY`; document dates use `eff`.
7. Helpyou returns the minimum sufficient detail for the routed task.
8. Every pilot turn passes through memory classification, while durable memory remains governed and user-controllable.
9. Code 4E classification is not a substitute for approved aircraft landing-performance verification.
10. Flight-specific scenario options are initially presented without AI ranking.
11. Training aids, cognitive models and adversarial inputs cannot become aircraft-operational authority.
12. Private source bytes must not appear in GitHub, CI artifacts or handoff archives.
13. FCOM Rev20 is the primary FCOM for the refreshed SQ23 bundle; QRH Rev18 requires explicit currency reconciliation.
