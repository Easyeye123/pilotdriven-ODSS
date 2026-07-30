# Helpyou Policy Reference

This directory contains a deterministic reference policy for the first Helpyou integration boundary.

It does **not** answer aviation questions and does **not** duplicate ODSS. It establishes:

- request segregation;
- specialist-engine ownership;
- cognitive-layer activation gates;
- authoritative evidence requirements;
- the ODSS/pilot-memory boundary;
- minimum-sufficient response sections;
- the PilotDriven citation format;
- mandatory separation of the pilot's raw wording and the AI interpretation.

## Run

```bash
cd integration/helpyou
python3 -m unittest -v test_helpyou_policy.py
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
