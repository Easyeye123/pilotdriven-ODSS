# Claude Adversarial Review Addendum — Live Weather Sources

Review this addendum together with PR #32 and the main Rev20 adversarial-review request.

## Governing boundary

- ODSS owns live-weather acquisition and validation.
- Helpyou consumes an immutable source-labelled snapshot.
- Approved public official sources are NOAA AWC, JMA, BoM and HKO.
- The issuing aerodrome authority or MWO is primary for its product.
- NOAA may provide a global machine-readable copy/fallback.
- Satellite imagery is supporting evidence only.

## Attack questions

1. Can Helpyou Chat bypass ODSS and fetch or reinterpret weather independently?
2. Can NOAA aggregation silently override JMA, BoM or HKO as the issuing authority?
3. Can two conflicting reports be silently merged or one discarded without a visible conflict?
4. Can a TAF be used when its validity does not cover projected arrival?
5. Can a SIGMET be displayed as relevant without route/time/vertical intersection?
6. Can satellite imagery be promoted into an airport-minima, SIGMET, runway or landing-performance conclusion?
7. Can a stale image or report be presented without issue/capture and retrieval times?
8. Can the historical SQ23 regression fixture be described as live weather?
9. Can BoM public-web data be presented as replacing the operator's approved Airservices/briefing channel?
10. Can a provider URL outside the registered official domains enter the snapshot?
11. Can decoded text replace or mutate the preserved raw OPMET message?
12. Can JMA/HKO regional monitoring guidance be mistaken for a formal SIGMET issued by the responsible MWO?

For every material finding, specify the exact file/function, concrete failure path and a deterministic regression test.
