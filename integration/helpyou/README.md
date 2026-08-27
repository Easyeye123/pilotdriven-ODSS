# Helpyou Policy Reference

This directory contains deterministic reference policies for the first Helpyou integration boundary and the approved continuity/facilitation baseline.

It does **not** answer aviation questions and does **not** duplicate ODSS. It establishes:

- request segregation;
- specialist-engine ownership;
- cognitive-layer activation gates;
- authoritative evidence requirements;
- the ODSS/pilot-memory boundary;
- minimum-sufficient response sections;
- the PilotDriven citation format;
- mandatory separation of the pilot's raw wording and the AI interpretation;
- dual-authority continuity checkpoints;
- visible fail-closed resumption; and
- Development Mode as the default unless Assessment or Research is explicitly selected.

## Run

```bash
cd integration/helpyou
python3 -m unittest discover -s . -p "test_*.py" -v
```

The implementation is standard-library only.

## Core invariants

1. Lido CFP analysis is owned by ODSS.
2. Rasmussen, Endsley and CBTA do not run on ordinary CFP, lookup, compilation or calculation requests.
3. A CFP-grounded scenario cannot generate flight-specific options until the Lido CFP has been processed by ODSS.
4. Authoritative claims require current, applicable and claim-supporting citations.
5. Pilot experience and AI possibilities never become ODSS evidence.
6. Citation dates use `DD.MM.YY`; document dates use `eff`.
7. Helpyou returns the minimum sufficient detail for the routed task.
8. Every pilot turn passes through memory classification, while durable memory remains governed and user-controllable.
9. Private flight-case data, proprietary source content and pilot wording never enter this public repository.
10. A valid continuity checkpoint requires verified merged-GitHub and persistent human-record bindings.
11. Every approved material change creates one atomic successor checkpoint; drafts do not.
12. A valid load produces a visible status brief before substantive work.
13. Development Mode teaches the policy and viable options before one focused learning question.
14. Assessment or Research activates only through explicit recorded selection; the word `facilitator` alone does not select a mode.

## Integration boundary

`helpyou_continuity.py` is a reference enforcement module, not a hosted persistence service. Product startup must call `bootstrap_helpyou_session`, provide a private store adapter, retrieve and externally verify the complete checkpoint chain, and render the returned status brief before the first substantive Helpyou response. Documentation or a pull-request branch alone does not create platform-level automatic continuity.
