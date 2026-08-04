# Helpyou Core v0.2

Deterministic guided-decision orchestration for CFP-grounded scenario discussions.

## Run tests

```bash
PYTHONPATH=. python -m unittest discover -s tests -v
```

The first golden fixture is `fixtures/sq23_oei_etp1_1d.json`. It contains no proprietary manual pages or full CFP. It records controlled metadata, selected CFP-derived values, compact source references and explicit product-owner assumptions for landing performance, CFP NOTAM validity and CFP-declared MEL validity.

The OM-grounded source policy is implemented by:

```text
helpyou_core/document_priority.py
helpyou_core/source_registry.py
```

The FCOM landing-performance method remains separate from the assumed airport result; no airport-specific LDA, LD, FLD, RLD or runway-required values are fabricated.

See:

- [`../../docs/helpyou/HELPYOU_CORE_V0_2_VERTICAL_SLICE.md`](../../docs/helpyou/HELPYOU_CORE_V0_2_VERTICAL_SLICE.md)
- [`../../docs/helpyou/HELPYOU_OM_FCTM_AUTHORITY_AND_SQ23_TEST_BASIS.md`](../../docs/helpyou/HELPYOU_OM_FCTM_AUTHORITY_AND_SQ23_TEST_BASIS.md)
