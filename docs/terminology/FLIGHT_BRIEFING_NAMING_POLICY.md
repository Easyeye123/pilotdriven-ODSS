# PilotDriven Flight Briefing Naming Policy

**Status:** Canonical and permanent  
**Adopted:** 04.08.26

## Canonical product name

The PilotDriven component previously presented as ODSS is now called **Flight Briefing**.

Use these public terms:

- Flight Briefing;
- Flight Briefing analysis;
- Flight Briefing engine or service;
- Flight Briefing report;
- Flight Briefing protocol;
- Flight Briefing findings;
- Flight Briefing source snapshot;
- Flight Briefing evidence boundary.

Do not abbreviate Flight Briefing to `FB`.

## Legacy technical identifiers

The legacy name may remain only where changing it would break compatibility, traceability or historical references, including:

- the repository name `Easyeye123/pilotdriven-ODSS`;
- existing package, module, API, database, environment-variable and schema identifiers such as `odss_adapter.py`, `TaskRoute.ODSS_CFP`, `odss_snapshot_id` and `/api/odss/...`;
- archived filenames, branches, pull requests, commits and immutable historical artifacts;
- exact quotations from historical source material.

These identifiers are implementation details. They must not be exposed as the current product name in pilot-facing interfaces, reports, protocols or teaching responses.

Where migration context is genuinely required, use **“Flight Briefing (formerly ODSS)”** once, then use **Flight Briefing** throughout.

## Product relationship

- **PilotDriven** is the overall product.
- **Flight Briefing** performs deterministic Lido CFP analysis, weather and NOTAM applicability, operational calculations and briefing generation.
- **Helpyou** interrogates, teaches, compiles and learns from the pilot while consuming controlled Flight Briefing results.

## Enforcement

Current public documentation, interface labels, error messages and teaching text must not use standalone `ODSS` as the product name. Regression tests permit the legacy token only when it is embedded in a technical or immutable identifier.
