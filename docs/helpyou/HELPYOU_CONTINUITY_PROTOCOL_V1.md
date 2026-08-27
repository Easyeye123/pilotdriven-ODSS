# Helpyou Continuity and Facilitation Protocol v1

**Status:** Approved continuity baseline  
**Version:** 1.0  
**Approval date:** 27.08.26

## 1. Purpose

This protocol makes a Helpyou discussion recoverable across conversation, workspace or interface interruptions. Chat history is useful context but is not the canonical system of record. Continuity is established by controlled checkpoints, dual authority pointers and a visible resumption brief.

This protocol governs conversation state and learning facilitation. It does not make operational aviation decisions, calculate Flight Briefing findings or replace current approved sources.

## 2. Approved defaults

| ID | Approved default | Hardcoded result |
|---|---|---|
| D1 | Authority | The controlled GitHub protocol and a persistent human-readable record are both required. |
| D2 | Checkpoint trigger | Every approved material, source-revision or mode change creates a successor checkpoint. Draft discussion does not silently become approved state. |
| D3 | Resumption | A checkpoint is loaded automatically when accessible, followed by a visible status brief before substantive work. |
| D4 | Interaction mode | Development Mode is the default. Assessment or Research Mode activates only through explicit selection recorded in the checkpoint. |

## 3. Continuity contract

1. Do not treat a platform conversation as the sole record.
2. Do not respond to an interruption by asserting that the work must start again when a valid checkpoint exists.
3. Load the latest valid checkpoint and show its identifier, status, active mode, last approved change, open items and next prompt.
4. Do not silently reconstruct missing controlled state from model memory.
5. If a checkpoint is incomplete or inaccessible, identify the exact missing layer and fail closed on affected claims.
6. Preserve approved changes, superseded positions and unresolved questions separately.
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

Both authority pointers, their fingerprints and external verification are required for a checkpoint to be declared recoverable. GitHub authority means the merged `main`-branch commit, not an unmerged branch or pull request. A GitHub document alone proves the protocol but not the current private state. A human record alone preserves the state but does not prove which machine-enforced protocol governed it.

## 5. Checkpoint state

Each checkpoint records at least:

- protocol version and checkpoint identifier;
- explicit UTC update time;
- GitHub repository and protocol path;
- merged GitHub commit and normalized policy fingerprint;
- persistent human-record identifier;
- human-record fingerprint and verification state;
- current mode and whether a non-default mode was explicitly selected;
- private active-case reference, when applicable;
- source manifest by controlled reference, not copied proprietary content;
- controlled facts;
- approved material changes;
- superseded positions;
- open questions;
- the next prompt; and
- completion or gap status.

The same approved material change must not be represented by multiple conflicting successor checkpoints. A later correction supersedes the earlier position explicitly; it does not erase the history.

## 6. Visible resumption brief

Before substantive work after resumption, Helpyou shows:

```text
CONTINUITY STATUS
Checkpoint: <identifier>
Status: <active / incomplete / superseded>
Mode: <development / assessment / research>
Active case: <private reference or none>
Last approved change: <one statement>
Open items: <material unresolved questions>
Next step: <one deterministic prompt>
Authority: <GitHub verified / human record verified / gap stated>
```

The brief is a control display, not a request for the pilot to retell the entire case.

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

If both authority layers are accessible and verified, resume from the latest valid checkpoint. An unmerged pull request is not active normative authority. If only one layer is accessible, declare continuity incomplete, show what was recovered and stop any claim dependent on the missing layer. If neither layer is accessible, state that no controlled checkpoint can be verified; do not imply that model memory is a substitute.

The recoverability test is passed only when a fresh session can:

1. locate both authority pointers;
2. validate the checkpoint schema;
3. display the resumption brief;
4. identify the next prompt without asking for a full retelling; and
5. keep private state out of the public repository.

## 11. Regression baseline

The reference implementation must test at least:

- Development Mode is the default;
- Assessment and Research require explicit selection;
- every approved material event requires a checkpoint;
- the four approved defaults can be stored as one atomic, idempotent bundle;
- drafts cannot be recorded as approved changes;
- both authority pointers are required;
- missing required fields fail closed;
- a visible resumption brief is always produced after a valid load;
- Development Mode teaches policy and options before probing;
- Assessment Mode does not coach before commitment; and
- private pilot wording and AI interpretation are excluded from public projection.

## 12. Change control

| Version | Date | Change |
|---|---|---|
| 1.0 | 27.08.26 | Established the four approved continuity defaults, mode-specific facilitation order, dual-authority recovery and privacy boundary. |
