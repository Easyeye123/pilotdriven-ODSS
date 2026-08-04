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
- OM-grounded document priority and version rules;
- official live-weather source governance;
- the SQ23 A350 Rev20/OM32 golden scenario.

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
helpyou_core/                         deterministic orchestration modules
helpyou_core/source_registry.py      authority, currency and source-use guard
helpyou_core/document_priority.py    SIA OM document priority and scope policy
helpyou_core/live_weather_policy.py  NOAA/JMA/BoM/HKO authority and evidence guard
fixtures/sq23_oei_etp1_1d.json       SQ23 OEI golden scenario
fixtures/sq23_source_manifest_rev20.json
                                      private-source metadata only
fixtures/live_weather_source_registry.json
                                      official public weather-source metadata
tests/                                regression suite
```

See:

- [`README_CORE_V0_2.md`](README_CORE_V0_2.md)
- [`../../docs/helpyou/HELPYOU_CORE_V0_2_VERTICAL_SLICE.md`](../../docs/helpyou/HELPYOU_CORE_V0_2_VERTICAL_SLICE.md)
- [`../../docs/helpyou/HELPYOU_SOURCE_BUNDLE_SQ23_A350_REV20.md`](../../docs/helpyou/HELPYOU_SOURCE_BUNDLE_SQ23_A350_REV20.md)
- [`../../docs/helpyou/HELPYOU_OM_FCTM_AUTHORITY_AND_SQ23_TEST_BASIS.md`](../../docs/helpyou/HELPYOU_OM_FCTM_AUTHORITY_AND_SQ23_TEST_BASIS.md)
- [`../../docs/helpyou/HELPYOU_LIVE_WEATHER_SOURCE_PROTOCOL.md`](../../docs/helpyou/HELPYOU_LIVE_WEATHER_SOURCE_PROTOCOL.md)
- [`../../docs/helpyou/CLAUDE_ADVERSARIAL_REVIEW_REQUEST_V0_2_REV20.md`](../../docs/helpyou/CLAUDE_ADVERSARIAL_REVIEW_REQUEST_V0_2_REV20.md)
- [`../../docs/helpyou/CLAUDE_LIVE_WEATHER_ADVERSARIAL_ADDENDUM.md`](../../docs/helpyou/CLAUDE_LIVE_WEATHER_ADVERSARIAL_ADDENDUM.md)

The implementation is standard-library only. The raw FCOM, OM, QRH, FCTM, SQNP, SQSP, SQI, CFP and other proprietary sources are not committed and remain in private controlled storage.

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
13. FCOM Rev20 is the primary FCOM; OM Rev32 is the operator-policy and document-priority source; QRH Rev18 requires explicit currentness reconciliation.
14. The exact OM priority groups are preserved; same-level sources are not given invented sub-priority.
15. A valid lower-authority requirement that is more restrictive remains applicable.
16. The FCOM landing-performance method is authoritative, while the airport result in the golden case remains an explicit scenario assumption without fabricated numerical values.
17. SQ23 CFP NOTAM and MEL validity assumptions apply only to the frozen golden test and cannot leak to another case.
18. ODSS, not Helpyou Chat, acquires live METAR, TAF, SIGMET and satellite products.
19. The issuing aerodrome authority or MWO is primary; NOAA AWC is the global machine-readable copy/fallback.
20. Satellite imagery is supporting evidence only and cannot independently establish an operational weather conclusion.
21. Historical replay weather cannot be labelled live, and source conflicts cannot be silently merged.
