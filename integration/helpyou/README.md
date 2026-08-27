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
10. A valid continuity checkpoint requires verified merged-GitHub and persistent human-record bindings plus a fresh receipt for the complete governed checkpoint state.
11. Every approved material change creates one atomic successor checkpoint; drafts do not.
12. A valid load produces a visible status brief before substantive work.
13. Development Mode teaches the policy and viable options before one focused learning question.
14. Assessment or Research activates only through explicit recorded selection; the word `facilitator` alone does not select a mode.
15. Every successor binds the prior checkpoint-envelope fingerprint, including its human-record hash, so history is transitively authenticated.
16. Every transition has a stable identifier, typed event, current delta and private upstream approval-evidence reference.
17. Persistence uses an immutable append-only store and envelope-bound compare-and-swap; identical retries and fast followers are handled deterministically.
18. Source references, controlled facts, approved changes and supersession records are append-only; pilot memory can be deactivated or superseded in the active view only by an approved memory-change transition, while immutable history remains.
19. Failed dual-authority bootstrap returns a structured `INCOMPLETE` recovery brief and never exposes an unverified state as safe to resume.
20. An independently authenticated monotonic head rejects valid-prefix rollback; checkpoint CAS and head advance are one transaction and are reverified before success.
21. `INCOMPLETE` state carries a controlled reason code semantically matched to unavailable layers and `safe_to_resume=false`; verified gaps are shown as recovered, while full resolution changes the visible gate to approved checkpoint-status clearance.
22. The v1 module accepts only protocol version `1.0`; unsupported versions and malformed accessible chains fail closed with truthful recovery layers.
23. Every successful persistence path verifies a bounded, mutually consistent chain/head snapshot and the latest authority artifacts; concurrent head movement triggers reread.
24. Store capability, stored-row, read, compare-and-swap and post-write exceptions are sanitized; arbitrary or wrong-stage unavailable/recovered reason-layer combinations cannot reach the visible recovery brief.
25. Genesis event types are orthogonal, invalid user scopes are rejected before adapter I/O, and unknown compare-and-swap outcomes are reconciled by verified candidate presence.
26. Clock failures always produce a clock-specific recovery action, whether detected during head or authority verification.
27. Recovery briefs enumerate all verified prerequisite stages and never mark one layer both recovered and unavailable.
28. Authority pointers use canonical owner/repository and POSIX-relative paths; traversal, backslashes, controls and dot/empty segments are rejected.
29. Invalid verifier receipt types fail at the adapter stage before a new clock read; post-clock head mismatches preserve truthful clock recovery.

## Integration boundary

`helpyou_continuity.py` is a reference enforcement module, not a hosted persistence service. Product startup must call `bootstrap_helpyou_session`, provide a `PRIVATE`, immutable, append-only store whose compare-and-swap binds both predecessor ID and envelope fingerprint, and provide a trusted authority verifier, independently authenticated monotonic head registry and clock. Startup validates the pseudonymous user scope before adapter I/O, retrieves and transitively verifies the complete checkpoint-envelope and semantic-transition chain, rejects valid-prefix rollback by matching its tail to the linearizable monotonic head, then renders the returned status brief before the first substantive Helpyou response. Checkpoint CAS and monotonic-head advance must be atomic. Every persistence success path—including idempotent retry, race recovery and unknown transport outcome—uses a bounded consistent-snapshot reread and verifies the current head, candidate presence and latest authority artifacts; capability, stored-row and adapter exceptions are sanitized. If private retrieval or any verification fails, bootstrap raises `ContinuityRecoveryError` with a UI-safe `INCOMPLETE` brief; typed failures distinguish missing checkpoints, invalid chains, GitHub, human-record, head, clock and status-clearance layers through closed, stage-specific reason and layer enumerations with semantic cross-validation, so arbitrary adapter diagnostics cannot enter the brief. The host must render the brief and block substantive use of unverified or persisted-`INCOMPLETE` state. The verifier independently establishes merged-main reachability, recomputes both artifact hashes and confirms that the human record embeds the governed-state fingerprint. The human record does not embed the checkpoint-envelope fingerprint because that envelope contains the record hash; the short-lived receipt independently binds the verified record hash and complete envelope. The trusted clock is read after each verifier returns and preserves sub-second precision. Bootstrap requests fresh receipts; expiry never deletes or expires the stored checkpoint. Unknown schema fields, unsupported protocol versions, direct-state semantic bypasses and unauthorised authority migrations fail closed. Genesis events cannot smuggle orthogonal mode or status state. Status changes use their own approved event; `ACTIVE` requires no gaps and `safe_to_resume=true`, while `INCOMPLETE` requires a controlled reason and unavailable layers. A gap verified during a later bootstrap is shown as recovered; once all gaps resolve, the brief changes to `STATUS_CLEARANCE_PENDING`, and an approved status-change checkpoint remains required before activation. Stable transition IDs provide idempotent retry without suppressing distinct repeated-prose events. Human-record IDs are unique within the complete user checkpoint chain; source, fact, approval and supersession histories are append-only. An approved memory-change event may deactivate or supersede memory in the latest active view, while immutable predecessor checkpoints retain history; genuine erasure requires a separate governed deletion or key-destruction process. The product must authenticate the user's approval and retain private approval evidence before calling an approved-change function; the module validates and stores the reference but cannot authenticate the external evidence itself. Documentation or a pull-request branch alone does not create platform-level automatic continuity.
