"""Fail-closed continuity and facilitation policy for Helpyou.

This module governs how a Helpyou conversation can be resumed without treating
chat history as the system of record.  It intentionally stores pointers and
controlled state; it does not make operational aviation decisions.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from typing import Any, Mapping


class ContinuityPolicyError(ValueError):
    """Raised when a continuity checkpoint is incomplete or contradictory."""


class InteractionMode(str, Enum):
    DEVELOPMENT = "development"
    ASSESSMENT = "assessment"
    RESEARCH = "research"


class ContinuityEvent(str, Enum):
    APPROVED_MATERIAL_CHANGE = "approved_material_change"
    APPROVED_SOURCE_REVISION = "approved_source_revision"
    APPROVED_MODE_CHANGE = "approved_mode_change"
    DRAFT_CHANGE = "draft_change"
    INFORMATION_ONLY = "information_only"


CHECKPOINT_EVENTS = frozenset(
    {
        ContinuityEvent.APPROVED_MATERIAL_CHANGE,
        ContinuityEvent.APPROVED_SOURCE_REVISION,
        ContinuityEvent.APPROVED_MODE_CHANGE,
    }
)

APPROVED_DEFAULTS_V1 = (
    "D1: GitHub protocol plus persistent human-readable authority",
    "D2: checkpoint after every approved material change",
    "D3: automatic load with a visible status brief",
    "D4: Development Mode unless Assessment or Research is explicitly selected",
)


@dataclass(frozen=True, kw_only=True)
class AuthorityPointers:
    """The two independent anchors required for recoverable continuity."""

    github_repository: str
    github_path: str
    github_commit_sha: str
    policy_fingerprint: str
    human_record_id: str
    human_record_fingerprint: str
    github_main_verified: bool
    human_record_verified: bool

    def validate(self) -> None:
        missing = [
            name
            for name, value in (
                ("github_repository", self.github_repository),
                ("github_path", self.github_path),
                ("github_commit_sha", self.github_commit_sha),
                ("policy_fingerprint", self.policy_fingerprint),
                ("human_record_id", self.human_record_id),
                ("human_record_fingerprint", self.human_record_fingerprint),
            )
            if not value.strip()
        ]
        if missing:
            raise ContinuityPolicyError(
                "Continuity authority is incomplete: " + ", ".join(missing)
            )
        if not self.github_main_verified:
            raise ContinuityPolicyError(
                "GitHub authority must be verified against the merged main-branch commit."
            )
        if not self.human_record_verified:
            raise ContinuityPolicyError("The persistent human-readable record is unverified.")


@dataclass(frozen=True, kw_only=True)
class PilotMemoryPair:
    """Private pilot wording and AI interpretation remain distinct."""

    raw_pilot_wording: str
    ai_interpretation: str

    def validate(self) -> None:
        if not self.raw_pilot_wording.strip() or not self.ai_interpretation.strip():
            raise ContinuityPolicyError("Both pilot wording and AI interpretation are required.")
        if self.raw_pilot_wording.strip() == self.ai_interpretation.strip():
            raise ContinuityPolicyError(
                "Pilot wording and AI interpretation must be stored separately."
            )


@dataclass(frozen=True, kw_only=True)
class ContinuityState:
    protocol_version: str
    checkpoint_id: str
    updated_at_utc: str
    authority: AuthorityPointers
    mode: InteractionMode = InteractionMode.DEVELOPMENT
    mode_selected_explicitly: bool = False
    status: str = "ACTIVE"
    active_case_ref: str | None = None
    source_manifest: tuple[str, ...] = ()
    controlled_facts: tuple[str, ...] = ()
    approved_changes: tuple[str, ...] = ()
    superseded_positions: tuple[str, ...] = ()
    open_questions: tuple[str, ...] = ()
    next_prompt: str = "Confirm the next material question."
    private_pilot_memory: tuple[PilotMemoryPair, ...] = ()

    def validate(self) -> None:
        if not self.protocol_version.strip():
            raise ContinuityPolicyError("protocol_version is required.")
        if not self.checkpoint_id.strip():
            raise ContinuityPolicyError("checkpoint_id is required.")
        if not self.updated_at_utc.endswith("Z"):
            raise ContinuityPolicyError("updated_at_utc must be an explicit UTC value ending Z.")
        if not self.next_prompt.strip():
            raise ContinuityPolicyError("next_prompt is required for deterministic resumption.")
        self.authority.validate()
        if self.mode is not InteractionMode.DEVELOPMENT and not self.mode_selected_explicitly:
            raise ContinuityPolicyError(
                "Assessment or Research mode requires an explicit recorded selection."
            )
        for item in self.private_pilot_memory:
            item.validate()


@dataclass(frozen=True, kw_only=True)
class ResumeBrief:
    checkpoint_id: str
    status: str
    mode: str
    active_case_ref: str | None
    last_approved_change: str | None
    open_questions: tuple[str, ...]
    next_prompt: str
    authority_status: str


def select_mode(requested: str | InteractionMode | None) -> tuple[InteractionMode, bool]:
    """Return Development by default; other modes require explicit selection."""

    if requested is None:
        return InteractionMode.DEVELOPMENT, False
    try:
        return InteractionMode(requested), True
    except ValueError as exc:
        raise ContinuityPolicyError(f"Unknown interaction mode: {requested!r}") from exc


def checkpoint_required(event: ContinuityEvent) -> bool:
    """Every approved material, source or mode change creates a checkpoint."""

    return event in CHECKPOINT_EVENTS


def record_approved_change(
    previous: ContinuityState,
    *,
    event: ContinuityEvent,
    approved_change: str,
    checkpoint_id: str,
    updated_at_utc: str,
    next_prompt: str,
    authority: AuthorityPointers | None = None,
) -> ContinuityState:
    """Create the mandatory successor checkpoint for an approved change."""

    return record_approved_bundle(
        previous,
        event=event,
        approved_changes=(approved_change,),
        checkpoint_id=checkpoint_id,
        updated_at_utc=updated_at_utc,
        next_prompt=next_prompt,
        authority=authority,
    )


def record_approved_bundle(
    previous: ContinuityState,
    *,
    event: ContinuityEvent,
    approved_changes: tuple[str, ...],
    checkpoint_id: str,
    updated_at_utc: str,
    next_prompt: str,
    authority: AuthorityPointers | None = None,
) -> ContinuityState:
    """Write one atomic successor checkpoint for an approved change bundle.

    Replaying an already-recorded bundle is idempotent and returns ``previous``.
    """

    if not checkpoint_required(event):
        raise ContinuityPolicyError(
            "record_approved_bundle accepts only events that mandate a checkpoint."
        )
    normalized = tuple(item.strip() for item in approved_changes if item.strip())
    if not normalized:
        raise ContinuityPolicyError("At least one approved change is required.")
    if len(set(normalized)) != len(normalized):
        raise ContinuityPolicyError("An approved bundle cannot contain duplicate changes.")
    new_changes = tuple(
        item for item in normalized if item not in previous.approved_changes
    )
    if not new_changes:
        return previous
    successor = replace(
        previous,
        checkpoint_id=checkpoint_id,
        updated_at_utc=updated_at_utc,
        authority=authority or previous.authority,
        approved_changes=previous.approved_changes + new_changes,
        next_prompt=next_prompt,
    )
    successor.validate()
    return successor


def visible_resume_brief(state: ContinuityState) -> ResumeBrief:
    """Expose the loaded state before substantive work resumes."""

    state.validate()
    return ResumeBrief(
        checkpoint_id=state.checkpoint_id,
        status=state.status,
        mode=state.mode.value,
        active_case_ref=state.active_case_ref,
        last_approved_change=(state.approved_changes[-1] if state.approved_changes else None),
        open_questions=state.open_questions,
        next_prompt=state.next_prompt,
        authority_status="Merged GitHub main + human-readable record verified",
    )


def load_checkpoint(payload: Mapping[str, Any]) -> ContinuityState:
    """Load a checkpoint without silently reconstructing missing required fields."""

    required = {
        "protocol_version",
        "checkpoint_id",
        "updated_at_utc",
        "authority",
        "next_prompt",
    }
    missing = sorted(required.difference(payload))
    if missing:
        raise ContinuityPolicyError(
            "Checkpoint cannot be reconstructed; missing: " + ", ".join(missing)
        )

    authority_payload = payload["authority"]
    if not isinstance(authority_payload, Mapping):
        raise ContinuityPolicyError("authority must be a mapping.")

    mode_value = payload.get("mode", InteractionMode.DEVELOPMENT.value)
    try:
        mode = InteractionMode(mode_value)
    except ValueError as exc:
        raise ContinuityPolicyError(f"Unknown stored interaction mode: {mode_value!r}") from exc

    state = ContinuityState(
        protocol_version=str(payload["protocol_version"]),
        checkpoint_id=str(payload["checkpoint_id"]),
        updated_at_utc=str(payload["updated_at_utc"]),
        authority=AuthorityPointers(
            github_repository=str(authority_payload.get("github_repository", "")),
            github_path=str(authority_payload.get("github_path", "")),
            github_commit_sha=str(authority_payload.get("github_commit_sha", "")),
            policy_fingerprint=str(authority_payload.get("policy_fingerprint", "")),
            human_record_id=str(authority_payload.get("human_record_id", "")),
            human_record_fingerprint=str(
                authority_payload.get("human_record_fingerprint", "")
            ),
            github_main_verified=bool(authority_payload.get("github_main_verified", False)),
            human_record_verified=bool(authority_payload.get("human_record_verified", False)),
        ),
        mode=mode,
        mode_selected_explicitly=bool(payload.get("mode_selected_explicitly", False)),
        status=str(payload.get("status", "ACTIVE")),
        active_case_ref=payload.get("active_case_ref"),
        source_manifest=tuple(payload.get("source_manifest", ())),
        controlled_facts=tuple(payload.get("controlled_facts", ())),
        approved_changes=tuple(payload.get("approved_changes", ())),
        superseded_positions=tuple(payload.get("superseded_positions", ())),
        open_questions=tuple(payload.get("open_questions", ())),
        next_prompt=str(payload["next_prompt"]),
    )
    state.validate()
    return state


def bootstrap_session(payload: Mapping[str, Any] | None = None) -> tuple[ContinuityState, ResumeBrief]:
    """Load an existing checkpoint and always return a visible status brief.

    Creating a brand-new state is deliberately outside this function: a new state
    needs explicit authority pointers and a first checkpoint identifier.
    """

    if payload is None:
        raise ContinuityPolicyError(
            "No continuity checkpoint was supplied; do not claim that prior state was loaded."
        )
    state = load_checkpoint(payload)
    return state, visible_resume_brief(state)


def facilitation_sequence(mode: InteractionMode) -> tuple[str, ...]:
    """Return the mode-specific interaction order."""

    if mode is InteractionMode.DEVELOPMENT:
        return (
            "State the known facts, limits and confidence.",
            "Explain the controlling policy or technical basis.",
            "Present the materially different viable options and decision gates.",
            "Ask one focused question that tests or extends understanding.",
            "Debrief the answer and checkpoint any approved material learning.",
        )
    if mode is InteractionMode.ASSESSMENT:
        return (
            "Present only the authorised scenario state and timed injects.",
            "Elicit the participant's interpretation, options and decision.",
            "Do not coach or reveal the expected answer before commitment.",
            "Freeze the trace before the source-based debrief.",
        )
    return (
        "Present the controlled scenario state without ranking options.",
        "Use neutral probes to capture the participant's mental model.",
        "Record prompts, timing, sources and adaptations.",
        "Separate observation from later cognitive interpretation.",
    )


def public_checkpoint_projection(state: ContinuityState) -> dict[str, Any]:
    """Return only non-sensitive checkpoint metadata suitable for a public repo."""

    state.validate()
    return {
        "protocol_version": state.protocol_version,
        "checkpoint_id": state.checkpoint_id,
        "updated_at_utc": state.updated_at_utc,
        "mode": state.mode.value,
        "status": state.status,
        "approved_change_count": len(state.approved_changes),
        "github_repository": state.authority.github_repository,
        "github_path": state.authority.github_path,
        "github_commit_sha": state.authority.github_commit_sha,
        "policy_fingerprint": state.authority.policy_fingerprint,
        "human_record_present": bool(state.authority.human_record_id),
    }
