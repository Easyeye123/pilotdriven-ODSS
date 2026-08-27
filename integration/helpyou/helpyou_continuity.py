"""Fail-closed continuity and facilitation reference policy for Helpyou."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum
import re
from typing import Any, Iterable, Mapping, Protocol


class ContinuityPolicyError(ValueError):
    pass


class InteractionMode(str, Enum):
    DEVELOPMENT = "development"
    ASSESSMENT = "assessment"
    RESEARCH = "research"


class CheckpointStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INCOMPLETE = "INCOMPLETE"
    SUPERSEDED = "SUPERSEDED"


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

_ID_RE = re.compile(r"^[A-Z0-9][A-Z0-9._-]{0,63}$")
_USER_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{7,127}$")
_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_FP_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


def _identifier(value: str, field: str) -> None:
    if not isinstance(value, str) or not _ID_RE.fullmatch(value):
        raise ContinuityPolicyError(f"{field} must be an opaque controlled identifier.")


def _utc(value: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ContinuityPolicyError("updated_at_utc must be explicit UTC ending Z.")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ContinuityPolicyError("updated_at_utc is not valid ISO-8601.") from exc
    if parsed.tzinfo != timezone.utc:
        raise ContinuityPolicyError("updated_at_utc must use UTC.")
    return parsed


def _bool(payload: Mapping[str, Any], key: str) -> bool:
    value = payload.get(key)
    if type(value) is not bool:
        raise ContinuityPolicyError(f"{key} must be a JSON boolean.")
    return value


def _strings(payload: Mapping[str, Any], key: str) -> tuple[str, ...]:
    value = payload.get(key, ())
    if not isinstance(value, (list, tuple)) or isinstance(value, (str, bytes)):
        raise ContinuityPolicyError(f"{key} must be an array of strings.")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise ContinuityPolicyError(f"{key} must contain non-empty strings.")
    return tuple(item.strip() for item in value)


@dataclass(frozen=True, kw_only=True)
class AuthorityPointers:
    github_repository: str
    github_path: str
    github_commit_sha: str
    policy_fingerprint: str
    human_record_id: str
    human_record_fingerprint: str
    github_main_verified: bool
    human_record_verified: bool

    def validate(self) -> None:
        if not isinstance(self.github_repository, str) or not _REPO_RE.fullmatch(
            self.github_repository
        ):
            raise ContinuityPolicyError("github_repository must use owner/name.")
        if (
            not isinstance(self.github_path, str)
            or not self.github_path.strip()
            or self.github_path.startswith("/")
            or ".." in self.github_path.split("/")
            or "\n" in self.github_path
        ):
            raise ContinuityPolicyError("github_path is not a safe repository path.")
        if not isinstance(self.github_commit_sha, str) or not _COMMIT_RE.fullmatch(
            self.github_commit_sha
        ):
            raise ContinuityPolicyError("github_commit_sha must be 40 lowercase hex.")
        for field, value in (
            ("policy_fingerprint", self.policy_fingerprint),
            ("human_record_fingerprint", self.human_record_fingerprint),
        ):
            if not isinstance(value, str) or not _FP_RE.fullmatch(value):
                raise ContinuityPolicyError(f"{field} must use sha256:<64 lowercase hex>.")
        _identifier(self.human_record_id, "human_record_id")
        if type(self.github_main_verified) is not bool:
            raise ContinuityPolicyError("github_main_verified must be a boolean.")
        if type(self.human_record_verified) is not bool:
            raise ContinuityPolicyError("human_record_verified must be a boolean.")
        if not self.github_main_verified:
            raise ContinuityPolicyError("Merged-main GitHub authority is unverified.")
        if not self.human_record_verified:
            raise ContinuityPolicyError("The human-readable record is unverified.")


@dataclass(frozen=True, kw_only=True)
class PilotMemoryPair:
    raw_pilot_wording: str
    ai_interpretation: str

    def validate(self) -> None:
        if not isinstance(self.raw_pilot_wording, str) or not self.raw_pilot_wording.strip():
            raise ContinuityPolicyError("raw_pilot_wording is required.")
        if not isinstance(self.ai_interpretation, str) or not self.ai_interpretation.strip():
            raise ContinuityPolicyError("ai_interpretation is required.")
        if self.raw_pilot_wording.strip() == self.ai_interpretation.strip():
            raise ContinuityPolicyError("Pilot wording and AI interpretation must differ.")


@dataclass(frozen=True, kw_only=True)
class ContinuityState:
    protocol_version: str
    checkpoint_id: str
    sequence: int
    previous_checkpoint_id: str | None
    user_scope_id: str
    updated_at_utc: str
    authority: AuthorityPointers
    mode: InteractionMode = InteractionMode.DEVELOPMENT
    mode_selected_explicitly: bool = False
    status: CheckpointStatus = CheckpointStatus.ACTIVE
    active_case_ref: str | None = None
    source_manifest: tuple[str, ...] = ()
    controlled_facts: tuple[str, ...] = ()
    approved_changes: tuple[str, ...] = ()
    superseded_positions: tuple[str, ...] = ()
    open_questions: tuple[str, ...] = ()
    next_prompt: str = "Confirm the next material question."
    private_pilot_memory: tuple[PilotMemoryPair, ...] = ()

    def validate(self) -> None:
        if not isinstance(self.protocol_version, str) or not re.fullmatch(
            r"[0-9]+\.[0-9]+", self.protocol_version
        ):
            raise ContinuityPolicyError("protocol_version must use major.minor.")
        _identifier(self.checkpoint_id, "checkpoint_id")
        if type(self.sequence) is not int or self.sequence < 1:
            raise ContinuityPolicyError("sequence must be a positive integer.")
        if self.sequence == 1 and self.previous_checkpoint_id is not None:
            raise ContinuityPolicyError("The first checkpoint cannot name a predecessor.")
        if self.sequence > 1:
            if self.previous_checkpoint_id is None:
                raise ContinuityPolicyError("A successor requires previous_checkpoint_id.")
            _identifier(self.previous_checkpoint_id, "previous_checkpoint_id")
            if self.previous_checkpoint_id == self.checkpoint_id:
                raise ContinuityPolicyError("A checkpoint cannot be its own predecessor.")
        if not isinstance(self.user_scope_id, str) or not _USER_RE.fullmatch(
            self.user_scope_id
        ):
            raise ContinuityPolicyError("user_scope_id must be pseudonymous.")
        _utc(self.updated_at_utc)
        self.authority.validate()
        if not isinstance(self.mode, InteractionMode):
            raise ContinuityPolicyError("mode must be an InteractionMode.")
        if type(self.mode_selected_explicitly) is not bool:
            raise ContinuityPolicyError("mode_selected_explicitly must be a boolean.")
        if self.mode is not InteractionMode.DEVELOPMENT and not self.mode_selected_explicitly:
            raise ContinuityPolicyError("Assessment or Research requires explicit selection.")
        if not isinstance(self.status, CheckpointStatus):
            raise ContinuityPolicyError("status must be a CheckpointStatus.")
        if self.active_case_ref is not None and (
            not isinstance(self.active_case_ref, str)
            or not self.active_case_ref.strip()
            or len(self.active_case_ref) > 128
            or "\n" in self.active_case_ref
        ):
            raise ContinuityPolicyError("active_case_ref must be a short private reference.")
        for name, value in (
            ("source_manifest", self.source_manifest),
            ("controlled_facts", self.controlled_facts),
            ("approved_changes", self.approved_changes),
            ("superseded_positions", self.superseded_positions),
            ("open_questions", self.open_questions),
        ):
            if not isinstance(value, tuple) or any(
                not isinstance(item, str) or not item.strip() for item in value
            ):
                raise ContinuityPolicyError(f"{name} must be a tuple of strings.")
        if len(set(self.approved_changes)) != len(self.approved_changes):
            raise ContinuityPolicyError("approved_changes contains duplicates.")
        if not isinstance(self.next_prompt, str) or not self.next_prompt.strip():
            raise ContinuityPolicyError("next_prompt is required.")
        if not isinstance(self.private_pilot_memory, tuple):
            raise ContinuityPolicyError("private_pilot_memory must be a tuple.")
        for item in self.private_pilot_memory:
            if not isinstance(item, PilotMemoryPair):
                raise ContinuityPolicyError("Invalid private_pilot_memory item.")
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


class ContinuityStore(Protocol):
    def list_checkpoints(self, user_scope_id: str) -> Iterable[Mapping[str, Any]]: ...

    def put_checkpoint(self, payload: Mapping[str, Any]) -> None: ...


def select_mode(requested: str | InteractionMode | None) -> tuple[InteractionMode, bool]:
    if requested is None:
        return InteractionMode.DEVELOPMENT, False
    try:
        return InteractionMode(requested), True
    except (TypeError, ValueError) as exc:
        raise ContinuityPolicyError(f"Unknown interaction mode: {requested!r}") from exc


def checkpoint_required(event: ContinuityEvent) -> bool:
    return event in CHECKPOINT_EVENTS


def _successor(
    previous: ContinuityState,
    *,
    event: ContinuityEvent,
    approved_changes: tuple[str, ...],
    checkpoint_id: str,
    updated_at_utc: str,
    next_prompt: str,
    authority: AuthorityPointers,
    mode: InteractionMode,
    explicit: bool,
) -> ContinuityState:
    previous.validate()
    if not checkpoint_required(event):
        raise ContinuityPolicyError("The event does not permit an approved checkpoint.")
    normalized = tuple(item.strip() for item in approved_changes if item.strip())
    if not normalized or len(set(normalized)) != len(normalized):
        raise ContinuityPolicyError("The approved bundle is empty or duplicated.")
    new_changes = tuple(item for item in normalized if item not in previous.approved_changes)
    if not new_changes:
        return previous
    _identifier(checkpoint_id, "checkpoint_id")
    if checkpoint_id == previous.checkpoint_id:
        raise ContinuityPolicyError("A successor requires a new checkpoint_id.")
    if _utc(updated_at_utc) <= _utc(previous.updated_at_utc):
        raise ContinuityPolicyError("A successor timestamp must be later.")
    authority.validate()
    if authority.human_record_fingerprint == previous.authority.human_record_fingerprint:
        raise ContinuityPolicyError("A successor requires a newly verified human record.")
    state = replace(
        previous,
        checkpoint_id=checkpoint_id,
        sequence=previous.sequence + 1,
        previous_checkpoint_id=previous.checkpoint_id,
        updated_at_utc=updated_at_utc,
        authority=authority,
        mode=mode,
        mode_selected_explicitly=explicit,
        approved_changes=previous.approved_changes + new_changes,
        next_prompt=next_prompt,
    )
    state.validate()
    return state


def record_approved_bundle(
    previous: ContinuityState,
    *,
    event: ContinuityEvent,
    approved_changes: tuple[str, ...],
    checkpoint_id: str,
    updated_at_utc: str,
    next_prompt: str,
    authority: AuthorityPointers,
) -> ContinuityState:
    if event is ContinuityEvent.APPROVED_MODE_CHANGE:
        raise ContinuityPolicyError("Use record_mode_change for mode changes.")
    return _successor(
        previous,
        event=event,
        approved_changes=approved_changes,
        checkpoint_id=checkpoint_id,
        updated_at_utc=updated_at_utc,
        next_prompt=next_prompt,
        authority=authority,
        mode=previous.mode,
        explicit=previous.mode_selected_explicitly,
    )


def record_approved_change(previous: ContinuityState, *, approved_change: str, **kwargs) -> ContinuityState:
    return record_approved_bundle(previous, approved_changes=(approved_change,), **kwargs)


def record_mode_change(
    previous: ContinuityState,
    *,
    new_mode: str | InteractionMode,
    approved_change: str,
    checkpoint_id: str,
    updated_at_utc: str,
    next_prompt: str,
    authority: AuthorityPointers,
) -> ContinuityState:
    mode, explicit = select_mode(new_mode)
    return _successor(
        previous,
        event=ContinuityEvent.APPROVED_MODE_CHANGE,
        approved_changes=(approved_change,),
        checkpoint_id=checkpoint_id,
        updated_at_utc=updated_at_utc,
        next_prompt=next_prompt,
        authority=authority,
        mode=mode,
        explicit=explicit,
    )


def visible_resume_brief(state: ContinuityState) -> ResumeBrief:
    state.validate()
    return ResumeBrief(
        checkpoint_id=state.checkpoint_id,
        status=state.status.value,
        mode=state.mode.value,
        active_case_ref=state.active_case_ref,
        last_approved_change=state.approved_changes[-1] if state.approved_changes else None,
        open_questions=state.open_questions,
        next_prompt=state.next_prompt,
        authority_status="Merged GitHub main + human-readable record verified",
    )


def load_checkpoint(payload: Mapping[str, Any]) -> ContinuityState:
    if not isinstance(payload, Mapping):
        raise ContinuityPolicyError("Checkpoint payload must be a mapping.")
    required = {
        "protocol_version", "checkpoint_id", "sequence", "previous_checkpoint_id",
        "user_scope_id", "updated_at_utc", "authority", "mode",
        "mode_selected_explicitly", "status", "next_prompt",
    }
    missing = sorted(required.difference(payload))
    if missing:
        raise ContinuityPolicyError("Checkpoint cannot be reconstructed; missing: " + ", ".join(missing))
    authority = payload["authority"]
    if not isinstance(authority, Mapping):
        raise ContinuityPolicyError("authority must be a mapping.")
    try:
        mode = InteractionMode(payload["mode"])
        status = CheckpointStatus(payload["status"])
    except (TypeError, ValueError) as exc:
        raise ContinuityPolicyError("Stored mode or status is invalid.") from exc
    if type(payload["sequence"]) is not int:
        raise ContinuityPolicyError("sequence must be a JSON integer.")
    memories = payload.get("private_pilot_memory", ())
    if not isinstance(memories, (list, tuple)) or isinstance(memories, (str, bytes)):
        raise ContinuityPolicyError("private_pilot_memory must be an array.")
    parsed_memory = []
    for item in memories:
        if not isinstance(item, Mapping):
            raise ContinuityPolicyError("Invalid private_pilot_memory item.")
        parsed_memory.append(PilotMemoryPair(
            raw_pilot_wording=str(item.get("raw_pilot_wording", "")),
            ai_interpretation=str(item.get("ai_interpretation", "")),
        ))
    state = ContinuityState(
        protocol_version=str(payload["protocol_version"]),
        checkpoint_id=str(payload["checkpoint_id"]),
        sequence=payload["sequence"],
        previous_checkpoint_id=payload["previous_checkpoint_id"],
        user_scope_id=str(payload["user_scope_id"]),
        updated_at_utc=str(payload["updated_at_utc"]),
        authority=AuthorityPointers(
            github_repository=str(authority.get("github_repository", "")),
            github_path=str(authority.get("github_path", "")),
            github_commit_sha=str(authority.get("github_commit_sha", "")),
            policy_fingerprint=str(authority.get("policy_fingerprint", "")),
            human_record_id=str(authority.get("human_record_id", "")),
            human_record_fingerprint=str(authority.get("human_record_fingerprint", "")),
            github_main_verified=_bool(authority, "github_main_verified"),
            human_record_verified=_bool(authority, "human_record_verified"),
        ),
        mode=mode,
        mode_selected_explicitly=_bool(payload, "mode_selected_explicitly"),
        status=status,
        active_case_ref=payload.get("active_case_ref"),
        source_manifest=_strings(payload, "source_manifest"),
        controlled_facts=_strings(payload, "controlled_facts"),
        approved_changes=_strings(payload, "approved_changes"),
        superseded_positions=_strings(payload, "superseded_positions"),
        open_questions=_strings(payload, "open_questions"),
        next_prompt=str(payload["next_prompt"]),
        private_pilot_memory=tuple(parsed_memory),
    )
    state.validate()
    return state


def state_to_payload(state: ContinuityState) -> dict[str, Any]:
    state.validate()
    return {
        "protocol_version": state.protocol_version,
        "checkpoint_id": state.checkpoint_id,
        "sequence": state.sequence,
        "previous_checkpoint_id": state.previous_checkpoint_id,
        "user_scope_id": state.user_scope_id,
        "updated_at_utc": state.updated_at_utc,
        "authority": {
            "github_repository": state.authority.github_repository,
            "github_path": state.authority.github_path,
            "github_commit_sha": state.authority.github_commit_sha,
            "policy_fingerprint": state.authority.policy_fingerprint,
            "human_record_id": state.authority.human_record_id,
            "human_record_fingerprint": state.authority.human_record_fingerprint,
            "github_main_verified": state.authority.github_main_verified,
            "human_record_verified": state.authority.human_record_verified,
        },
        "mode": state.mode.value,
        "mode_selected_explicitly": state.mode_selected_explicitly,
        "status": state.status.value,
        "active_case_ref": state.active_case_ref,
        "source_manifest": list(state.source_manifest),
        "controlled_facts": list(state.controlled_facts),
        "approved_changes": list(state.approved_changes),
        "superseded_positions": list(state.superseded_positions),
        "open_questions": list(state.open_questions),
        "next_prompt": state.next_prompt,
        "private_pilot_memory": [
            {"raw_pilot_wording": item.raw_pilot_wording, "ai_interpretation": item.ai_interpretation}
            for item in state.private_pilot_memory
        ],
    }


def _chain(user_scope_id: str, payloads: Iterable[Mapping[str, Any]]) -> tuple[ContinuityState, ...]:
    if not isinstance(user_scope_id, str) or not _USER_RE.fullmatch(user_scope_id):
        raise ContinuityPolicyError("user_scope_id must be pseudonymous.")
    states = tuple(load_checkpoint(item) for item in payloads)
    if not states:
        raise ContinuityPolicyError("No continuity checkpoint was found.")
    if any(item.user_scope_id != user_scope_id for item in states):
        raise ContinuityPolicyError("A checkpoint belongs to another user scope.")
    by_sequence: dict[int, ContinuityState] = {}
    for state in states:
        old = by_sequence.get(state.sequence)
        if old is not None and old != state:
            raise ContinuityPolicyError("Conflicting checkpoints share a sequence.")
        by_sequence[state.sequence] = state
    numbers = sorted(by_sequence)
    if numbers != list(range(1, numbers[-1] + 1)):
        raise ContinuityPolicyError("The checkpoint chain has a missing sequence.")
    chain = tuple(by_sequence[number] for number in numbers)
    for previous, current in zip(chain, chain[1:]):
        if current.previous_checkpoint_id != previous.checkpoint_id:
            raise ContinuityPolicyError("The predecessor chain is broken.")
        if _utc(current.updated_at_utc) <= _utc(previous.updated_at_utc):
            raise ContinuityPolicyError("Checkpoint timestamps are not increasing.")
    return chain


def bootstrap_helpyou_session(user_scope_id: str, store: ContinuityStore) -> tuple[ContinuityState, ResumeBrief]:
    state = _chain(user_scope_id, store.list_checkpoints(user_scope_id))[-1]
    return state, visible_resume_brief(state)


def persist_checkpoint(store: ContinuityStore, state: ContinuityState) -> None:
    state.validate()
    store.put_checkpoint(state_to_payload(state))
    if _chain(state.user_scope_id, store.list_checkpoints(state.user_scope_id))[-1] != state:
        raise ContinuityPolicyError("Checkpoint round-trip verification failed.")


def facilitation_sequence(mode: str | InteractionMode) -> tuple[str, ...]:
    try:
        normalized = InteractionMode(mode)
    except (TypeError, ValueError) as exc:
        raise ContinuityPolicyError(f"Unknown interaction mode: {mode!r}") from exc
    if normalized is InteractionMode.DEVELOPMENT:
        return (
            "State the known facts, limits and confidence.",
            "Explain the controlling policy or technical basis.",
            "Present the materially different viable options and decision gates.",
            "Ask one focused question that tests or extends understanding.",
            "Debrief the answer and checkpoint any approved material learning.",
        )
    if normalized is InteractionMode.ASSESSMENT:
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
    state.validate()
    return {
        "protocol_version": state.protocol_version,
        "mode": state.mode.value,
        "status": state.status.value,
        "approved_change_count": len(state.approved_changes),
        "authority_verified": True,
        "private_checkpoint_present": True,
    }
