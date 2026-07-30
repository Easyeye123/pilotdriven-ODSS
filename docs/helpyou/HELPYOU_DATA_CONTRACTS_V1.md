# Helpyou Data Contracts v1

**Status:** Integration baseline  
**Date:** 30.07.26

## 1. Logical data stores

### Authoritative Knowledge Database

Contains controlled documents, source spans, current and superseded versions, applicability, conflicts and published knowledge objects.

### Pilot Memory Database

Contains private pilot wording, structured interpretations, experiences, corrections, preferences and discussion-specific reasoning evidence.

### CFP Case Database

Contains the uploaded CFP, ODSS source snapshot, parsed flight facts, deterministic findings, weather/NOTAM snapshot and report versions.

### Audit Database

Contains the request route, policy version, source snapshot, claims, citations, cognitive activation, memory decision and user corrections.

The CFP analyser must not query the Pilot Memory Database.

## 2. Request route record

```json
{
  "request_id": "REQ-...",
  "context": {
    "operator": "SIA",
    "aircraft": "A350",
    "scenario_date": "30.07.26",
    "cfp_case_id": "CFP-..."
  },
  "subrequests": [
    {
      "route": "odss_cfp",
      "specialist_engine": "ODSS",
      "axiomatic_design": true,
      "rasmussen": false,
      "endsley": false,
      "cbta": false
    }
  ]
}
```

## 3. Authoritative claim record

```json
{
  "claim_id": "CLM-...",
  "text": "The verified claim",
  "evidence_class": "authoritative",
  "applicable": true,
  "current": true,
  "source_support_verified": true,
  "citations": [
    {
      "owner": "SIA",
      "document": "OM-B",
      "revision": "Rev 18",
      "eff": "13.08.25",
      "section": "§4.6.2",
      "page": 214,
      "applicability": "A350 arrival"
    }
  ],
  "assumptions": []
}
```

## 4. Pilot memory record

```json
{
  "record_id": "PKR-...",
  "pilot_id": "pseudonymous-user-id",
  "raw_pilot_wording": "Original wording",
  "ai_interpretation": "Separate structured interpretation",
  "record_type": "pilot_experience",
  "evidence_class": "single_pilot_report",
  "context": {
    "operator": null,
    "aircraft": null,
    "phase_of_flight": null,
    "airport_or_route": null,
    "weather": null,
    "system_state": null
  },
  "source_references": [],
  "visibility": "private",
  "authoritative_conflict": "none",
  "version": 1,
  "supersedes": null,
  "status": "active"
}
```

The raw statement and AI interpretation must never share the same field. AI inference must not be attributed to the pilot.

## 5. CFP-grounded scenario record

```json
{
  "scenario_id": "SCN-...",
  "cfp_case_id": "CFP-...",
  "odss_snapshot_id": "ODSS-SNAPSHOT-...",
  "event": "Destination weather deterioration",
  "anchor": {
    "waypoint": "...",
    "actm": "05:33",
    "utc": "...",
    "phase": "cruise"
  },
  "cfp_baseline": {},
  "pilot_scenario_assumptions": [],
  "weather_inputs": [],
  "options": [],
  "pilot_selection": null,
  "decision_gate": null,
  "cognitive_review_id": null
}
```

## 6. Option record

```json
{
  "option_id": "OPT-A",
  "course_of_action": "Divert to nominated alternate",
  "viable": true,
  "weather_basis": [],
  "odss_implications": {
    "time": null,
    "fuel": null,
    "route": null
  },
  "conditions": [],
  "decision_gate": {
    "condition": "fuel",
    "trigger": "...",
    "action": "divert"
  },
  "principal_risk": "...",
  "evidence_status": "supported_synthesis",
  "citations": []
}
```

Options are initially stored and displayed without an AI preference rank.

## 7. Cognitive review record

```json
{
  "review_id": "COG-...",
  "pilot_evidence": {
    "exact_statement": "...",
    "evidence_type": "expressed_in_discussion"
  },
  "endsley": {
    "picture_now": null,
    "meaning": null,
    "projection_ahead": null,
    "widen_scan": null,
    "decision_gate": null
  },
  "rasmussen": {
    "information": null,
    "system_behaviour": null,
    "capability": null,
    "safety_margin": null,
    "crew_objective": null,
    "action_and_feedback": null
  },
  "cbta": [
    {
      "competency": "SAW",
      "observable_evidence": "...",
      "developmental_status": "partially_demonstrated"
    }
  ],
  "flight_discipline": null,
  "safety_effect": null,
  "evidence_limitations": []
}
```

## 8. Evidence boundary

ODSS may consume:

- authoritative source records;
- supported synthesis derived exclusively from authoritative records;
- validated structured operational data;
- deterministic calculations.

ODSS must reject:

- pilot experience;
- pilot memory;
- AI possibilities;
- disputed, superseded or unsupported claims.

## 9. Citation rendering

All display layers use:

```text
[Owner | Document | Revision | eff DD.MM.YY | Section | p.Page | Applicability]
```

The database may retain ISO dates internally. User-facing citations render as `DD.MM.YY`.
