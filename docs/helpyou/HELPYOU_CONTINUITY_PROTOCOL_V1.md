# Helpyou Continuity and Facilitation Protocol v1

**Status:** Approved continuity baseline  
**Version:** 1.0  
**Approval date:** 27.08.26  
**Deployment:** Reference control; hosted startup and private-store integration required

This is the approved normative/reference baseline. It is not a hosted persistence service and is not automatically invoked by ChatGPT or PilotDriven today.

## 1. Purpose

This protocol defines how a Helpyou discussion becomes recoverable across conversation, workspace or interface interruptions when the hosted product provides the required startup hook, private store and authority verifier. Chat history is useful context but is not the canonical system of record. Continuity is established by controlled checkpoints, dual authority pointers and a visible resumption brief.

This protocol governs conversation state and learning facilitation. It does not make operational aviation decisions, calculate Flight Briefing findings or replace current approved sources.

## 2. Approved defaults

| ID | Approved default | Hardcoded result |
|---|---|---|
| D1 | Authority | The controlled GitHub protocol and a persistent human-readable record are both required. |
| D2 | Checkpoint trigger | Every approved material, source-revision, mode, status or pilot-memory change creates a successor checkpoint. Draft discussion does not silently become approved state. |
| D3 | Resumption | Once integrated, product startup shall automatically load an accessible valid checkpoint and show a visible status brief before substantive work. |
| D4 | Interaction mode | Development Mode is the default. Assessment or Research Mode activates only through explicit selection recorded in the checkpoint. |

## 3. Continuity contract

1. Do not treat a platform conversation as the sole record.
2. Do not respond to an interruption by asserting that the work must start again when a valid checkpoint exists.
3. Load the latest valid checkpoint and show its identifier, status, active mode, last approved change, open items and next prompt.
4. Do not silently reconstruct missing controlled state from model memory.
5. If a checkpoint is incomplete or inaccessible, identify the exact missing layer and fail closed on affected claims.
6. Preserve source references, controlled facts, approved changes and superseded positions as append-only histories; preserve unresolved questions separately.
7. Preserve the pilot's raw wording separately from AI interpretation.
8. Keep pilot memory and private flight-case content out of the public repository.
9. Never allow pilot memory, AI interpretation or a continuity record to override approved operational authority.
10. After every approved material change, write the next checkpoint before continuing to another material topic.

## 4. Dual authority and privacy boundary

The generic protocol, schema and regression logic belong in GitHub. The human-readable record contains the approved checkpoint and may refer to a private active case. Public projections contain only non-sensitive protocol metadata and must exclude:

- uploaded flight-document contents;
- proprietary manuals;
- personal pilot wording;
- AI interpretation of personal wording;
- private source identifiers or case facts; and
- unapproved hypotheses.

Both authority pointers, their fingerprints and a trusted-adapter verification receipt are required for a checkpoint to be declared recoverable. The verifier independently confirms that the commit is reachable from merged `main`, recomputes the policy and human-record hashes, and confirms that the human record embeds the supplied governed-state fingerprint. The human record is not required to embed the checkpoint-envelope fingerprint because that envelope contains the human-record hash. Instead, the receipt independently binds the complete repository/path/commit/fingerprint tuple, the governed-state fingerprint and the checkpoint-envelope fingerprint. The governed-state digest excludes only the human-record file hash so the human record can embed it without a circular dependency; the envelope digest closes that gap for successor chaining. A separate short-lived receipt from an independently authenticated monotonic head registry binds the user scope to the actual latest sequence, checkpoint identifier and envelope fingerprint. The head lookup must be linearizable and must not echo caller-supplied candidates. This freshness check detects a valid but stale chain prefix, which hash chaining alone cannot detect. Receipts are refreshed on every bootstrap and remain valid for no more than 15 minutes. Receipt expiry does not expire or delete the checkpoint; it requires fresh verification for the next load. Stored `verified=true` assertions are insufficient. GitHub authority means the merged `main`-branch commit, not an unmerged branch or pull request. A GitHub document alone proves the protocol but not the current private state. A human record alone preserves the state but does not prove which machine-enforced protocol governed it.

## 5. Checkpoint state

Each checkpoint records at least:

- protocol version and checkpoint identifier;
- monotonically increasing sequence and predecessor identifier;
- predecessor checkpoint-envelope fingerprint, creating a transitive chain that also authenticates historical human-record hashes;
- pseudonymous user-scope identifier;
- explicit UTC update time;
- GitHub repository and protocol path;
- merged GitHub commit and normalized policy fingerprint;
- persistent human-record identifier;
- human-record fingerprint and verification state;
- canonical governed-state fingerprint embedded in the human-readable record;
- stable transition identifier, event type and current transition delta;
- private upstream approval-evidence reference, append-only applied-transition identifiers and human-record identifiers unique within the complete user checkpoint chain;
- current mode and whether a non-default mode was explicitly selected;
- status, stable gap-reason code, unavailable layers and a safe-to-resume gate;
- private active-case reference, when applicable;
- source manifest by controlled reference, not copied proprietary content;
- controlled facts;
- approved material changes;
- superseded positions;
- open questions;
- the next prompt; and
- completion or gap status.

The same approved event must not be represented by multiple conflicting successor checkpoints. Idempotency is keyed by a stable transition identifier, not prose; repeated wording under a new source-revision or material-change event still creates a checkpoint. A successor requires checkpoint and human-record identifiers unique within the complete user chain, a later UTC time, the prior checkpoint-envelope fingerprint and a distinct verified human record. The existing chain plus candidate must pass full sequence, predecessor, identifier, timestamp, transition-semantic, transitive-digest, current-head and authority validation before any write. The repository and path remain immutable; changes to the merged commit or policy fingerprint require an `APPROVED_SOURCE_REVISION` transition. Status or gap metadata changes require an `APPROVED_STATUS_CHANGE`. `ACTIVE` requires no gap reason, no unavailable layers and `safe_to_resume=true`; `INCOMPLETE` requires a reason, at least one unavailable layer and `safe_to_resume=false`. `SUPERSEDED` is not a persistable v1 tail state because successor history itself records supersession. Source references, controlled facts, approved changes and superseded positions are append-only. A later correction adds a supersession record and corrected fact; it does not erase history. An `APPROVED_MEMORY_CHANGE` transition may deactivate or supersede pilot memory in the latest active view, but immutable predecessor checkpoints retain the historical value for audit. Genuine erasure requires a separately governed deletion or cryptographic key-destruction process outside this append-only checkpoint chain. The private store is append-only and immutable. Its compare-and-swap checks both the expected predecessor identifier and complete envelope fingerprint and atomically advances the independent monotonic head. A write is not reported successful until the advanced head and latest authority artifacts are independently reverified.

The reference module rejects draft-labelled events and preserves caller-supplied approved changes; it does not authenticate that a human approved them. The product integration is responsible for authenticating the user action and retaining an immutable private approval-evidence reference before calling the approved-change API.

## 6. Visible resumption brief

Before substantive work after resumption, Helpyou shows:

```text
CONTINUITY STATUS
Checkpoint: <identifier>
Status: <active / incomplete / superseded>
Mode: <development / assessment / research>
Active case: <private reference or none>
Last approved change: <one statement>
Last transition: <stable identifier / event type>
Open items: <material unresolved questions>
Next step: <one deterministic prompt>
Authority: <GitHub verified / human record verified / gap stated>
```

“Last approved change” comes from the current transition delta, not the tail of cumulative prose history. The brief is a control display, not a request for the pilot to retell the entire case.

## 7. Facilitation modes

### Development Mode — default

Development Mode teaches and probes in this order:

1. state known facts, limits and confidence;
2. explain the controlling policy or technical basis;
3. present materially different viable options and their decision gates;
4. ask one focused question that tests or extends understanding;
5. debrief the answer; and
6. checkpoint any approved material learning.

If the pilot says the options or policy are not understood, Helpyou explains them before asking the pilot to choose. A facilitator question must not manufacture doubt about whether Helpyou has read the applicable policy.

### Assessment Mode — explicit only

Assessment Mode may withhold coaching until the participant commits. It presents authorised scenario information, elicits reasoning, freezes the trace and then conducts a source-based debrief. Prompted and unprompted evidence remain distinguishable.

### Research Mode — explicit only

Research Mode uses neutral probes to extract mental models, assumptions, source use and adaptation. It records prompt timing and separates observation from later cognitive interpretation.

## 8. Prompt contract

Every Development Mode prompt must have a declared learning purpose. The default is one focused question after the answer, options and policy basis. The question should target one of:

- the controlling reason;
- the condition that changes the plan;
- a material assumption;
- the first option that will disappear;
- the evidence needed to reduce uncertainty; or
- expected feedback after action.

The pilot may change prompt depth, timing or style. Any approved change to that facilitation contract becomes a checkpointed material change.

## 9. Source and authority boundary

The existing PilotDriven doctrine remains controlling:

> Flight Briefing computes and never guesses. Helpyou retrieves and never invents. PilotDriven presents — and the pilot always decides.

Continuity checkpoints preserve what was known and approved; they do not promote it to operational authority. Current approved manuals, operational data, aeronautical and meteorological products, ATC instructions and commander judgement remain controlling.

## 10. Failure and recovery

If both authority layers are accessible, retrieve the complete private chain, verify every predecessor envelope digest and semantic transition transitively, match its tail to the independently attested monotonic head, and obtain a fresh trusted-adapter receipt matching the repository, path, merged commit, authority fingerprints, governed-state fingerprint embedded in the human record and complete checkpoint-envelope fingerprint. The trusted clock is read only after each verifier returns and preserves sub-second precision. Reject expired receipts, a stale valid prefix, unknown or noncanonical schema fields, competing sequence numbers, reused identifiers or broken predecessor links. Resume only when the verified tail is `ACTIVE` and `safe_to_resume=true`; a verified `INCOMPLETE` tail produces a structured gated brief rather than a normal resume. An unmerged pull request is not active normative authority. If only one authority layer is accessible, a trusted adapter raises a sanitized typed layer failure so bootstrap can identify which layer was recovered and which is unavailable. Layer values come from a closed, non-overlapping, duplicate-free enumeration; arbitrary adapter text cannot enter the UI-safe brief. Head and clock failures receive distinct opaque reason codes. Public exception text and tracebacks must not reproduce raw store, verifier or clock diagnostics; controlled adapters own any private diagnostic logging. The host must render the safe brief and block substantive use of the recovered case state. If neither layer is accessible, the same structured brief states that no controlled checkpoint can be verified; model memory is not a substitute.

The recoverability test is passed only when a fresh session can:

1. locate both authority pointers;
2. validate the checkpoint schema;
3. display the resumption brief;
4. match the retrieved tail to an independently attested monotonic head;
5. identify the next prompt without asking for a full retelling; and
6. keep private state out of the public repository.

## 11. Regression baseline

The reference implementation must test at least:

- Development Mode is the default;
- Assessment and Research require explicit selection;
- every approved material event requires a checkpoint;
- the four approved defaults can be stored as one atomic, idempotent bundle;
- successor IDs, sequence, predecessor and UTC ordering are enforced;
- malformed booleans, hashes, fingerprints, timestamps and arrays fail closed;
- malformed JSON scalar types fail closed without string coercion;
- unknown fields and noncanonical array whitespace fail closed;
- mode-change events actually update the selected mode;
- direct-state mode changes and ordinary-event authority migrations fail semantic validation;
- genesis checkpoints cannot smuggle prior approvals or a non-default mode;
- stable transition identifiers make retries idempotent without suppressing distinct repeated-prose events;
- competing successors and broken checkpoint chains fail closed;
- a write is round-trip verified through the private store adapter;
- a compare-and-swap rejection cannot be reported as a successful checkpoint;
- CAS binds the predecessor envelope and identical retry races are recognized as success;
- a fast-following valid checkpoint does not make an already committed write appear to fail;
- valid-prefix rollback is rejected by an independently attested monotonic head;
- persistence atomically advances that head and proves the new state is immediately recoverable;
- public or capability-unknown stores cannot receive private pilot memory;
- external authority-receipt mismatch fails closed;
- repository/path mismatch, expired or overlong receipts, and governed-state tampering fail closed;
- a changed predecessor, governed state or historical human-record hash breaks the transitive envelope chain;
- human-record identifiers are unique across the complete user checkpoint chain;
- source, controlled-fact and supersession histories cannot be erased;
- pilot memory cannot be deactivated or superseded in the active view without an approved memory-change transition, and immutable history is not misrepresented as erased;
- an invalid candidate is rejected before compare-and-swap can mutate the store;
- drafts cannot be recorded as approved changes;
- both authority pointers are required;
- missing required fields fail closed;
- a visible resumption brief is always produced after a valid load, and a structured `INCOMPLETE` brief is produced when recovery fails;
- raw store, verifier and clock exception text is not exposed through the recovery error or traceback;
- one-layer authority failures and trusted-clock failures identify the exact unavailable layer with sanitized reason codes;
- typed recovery failures reject arbitrary, duplicate or overlapping layer labels;
- an `INCOMPLETE` persisted tail is gated by reason, unavailable-layer and safe-to-resume metadata, while `SUPERSEDED` is rejected as a v1 tail state;
- Development Mode teaches policy and options before probing;
- Assessment Mode does not coach before commitment; and
- private pilot wording and AI interpretation are excluded from public projection.

The regression suite proves that draft-labelled calls are rejected. Authentication of the underlying human approval remains an upstream product responsibility.

## 12. Change control

| Version | Date | Change |
|---|---|---|
| 1.0 | 27.08.26 | Established the four approved continuity defaults, mode-specific facilitation order, dual-authority recovery and privacy boundary. |
