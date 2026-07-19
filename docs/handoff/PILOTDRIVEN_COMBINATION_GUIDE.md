# Combining ODSS v0.6 with pilotdriven.com

## Purpose

This guide explains how to merge the ODSS operational-analysis service into the separate PilotDriven product without duplicating the aviation logic or rebuilding the map/report contracts.

## Recommended deployment boundary

```text
PilotDriven web/mobile application
       ↓ authenticated API
ODSS analysis service
       ├── Lido parser
       ├── deterministic engines
       ├── timing
       ├── map contract
       ├── report generation
       └── audit/evidence
```

## ODSS responsibilities

- CFP ingestion and section detection;
- Page 1 extraction;
- MEL/CDL/CDDL findings;
- NOTAM and weather applicability;
- performance/fuel;
- BOBCAT;
- EDTO;
- ACTM and ATOT/ATA-derived UTC;
- FIR/communication actions;
- MSA/VWS grouping;
- depressurisation profiles;
- canonical route and marker GeoJSON;
- Level 1 and Level 2 reports;
- evidence, warnings and reference versions.

## PilotDriven responsibilities

- login and account management;
- tenant isolation;
- flight library and search;
- upload/user experience;
- application navigation;
- MapLibre component;
- dashboards and responsive UI;
- notifications;
- subscription/billing;
- S3/object-storage lifecycle;
- operational review/approval workflow.

## API contract

Minimum target endpoints:

```text
POST /v1/analyses
GET  /v1/analyses/{id}
GET  /v1/analyses/{id}/briefing
GET  /v1/analyses/{id}/route.geojson
GET  /v1/analyses/{id}/markers.geojson
GET  /v1/analyses/{id}/map-config
GET  /v1/analyses/{id}/reports/level-1
GET  /v1/analyses/{id}/reports/level-2
POST /v1/analyses/{id}/timing
```

## Integration sequence

### Step 1 — import contracts, not the dashboard

Bring these into PilotDriven first:

- ODSS analysis schema;
- `view.briefing`;
- map contract v1;
- route/marker GeoJSON;
- timing request/response;
- report URLs;
- warning/evidence model.

Do not copy Jinja templates as the long-term product UI.

### Step 2 — create a PilotDriven service client

Create a typed backend client responsible for:

- submitting an S3/object reference;
- polling job status;
- retrieving canonical results;
- saving timing anchors;
- retrieving reports and map contracts;
- mapping ODSS errors to user-facing states.

### Step 3 — build the React map component

The included Next.js reference component demonstrates:

- MapLibre initialization;
- style URL use;
- route/marker layers;
- route-bound fit;
- attribution;
- cleanup.

Package MapLibre locally with npm for production. Do not rely on a public CDN in the final PilotDriven deployment.

### Step 4 — reuse PilotDriven identity and storage

ODSS should receive:

- tenant ID;
- user ID;
- flight/workspace ID;
- authorized object location;
- operator/fleet profile;
- requested analysis version.

ODSS should return immutable analysis IDs and artifact references.

### Step 5 — preserve server authority

The PilotDriven browser may format and filter findings, but must not independently determine:

- NOTAM applicability;
- early-call timing;
- BOBCAT timing;
- EDTO events;
- MSA/VWS events;
- depressurisation profiles;
- MEL/CDL effects.

### Step 6 — implement review and audit

PilotDriven should record:

- analysis version;
- reference-library versions;
- user who uploaded;
- user who entered ATOT/ATA;
- report version;
- review status;
- user annotations;
- overridden or acknowledged warnings.

### Step 7 — golden regression

Run both directions:

- SQ303 EBBR–WSSS;
- SQ304 WSSS–EBBR.

Compare:

- flight identity;
- route hash;
- point count;
- critical labels;
- Page 1 masses;
- map start/end;
- timing outputs;
- report links;
- fallback labels;
- no cross-flight data carryover.

## Production prerequisites

- private repositories;
- authentication and authorization;
- per-tenant encryption;
- object-retention policy;
- background workers;
- Secrets Manager;
- rate limiting;
- CloudWatch tracing/alarms;
- backup and disaster recovery;
- operator-approved reference library;
- pilot/dispatcher SME validation;
- legal and security review.
