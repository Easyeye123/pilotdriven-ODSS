"""Fail-closed continuity and facilitation reference policy for Helpyou."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from enum import Enum
import hashlib
import json
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
MAX_RECEIPT_VALIDITY = timedelta(minutes=15)


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


def _strings(payload: Mapping[str, Any], key: str) -> tuple[str, ...]:
    value = payload.get(key, ())
    if not isinstance(value, (list, tuple)) or isinstance(value, (str, bytes)):
        raise ContinuityPolicyError(f"{key} must be an array of strings.")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise ContinuityPolicyError(f"{key} must contain non-empty strings.")
    return tuple(item.strip() for item in value)


def _json_bool(payload: Mapping[str, Any], key: str) -> bool:
    value = payload.get(key)
    if type(value) is not bool:
        raise ContinuityPolicyError(f"{key} must be a JSON boolean.")
    return value


@dataclass(frozen=True, kw_only=True)
class AuthorityPointers:
    github_repository: str
    github_path: str
    github_commit_sha: str
    policy_fingerprint: str
    human_record_id: str
    human_record_fingerprint: str

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


@dataclass(frozen=True, kw_only=True)
class AuthorityVerificationReceipt:
    """Receipt returned only after external GitHub and private-record checks."""

    github_repository: str
    github_path: str
    github_commit_sha: str
    policy_fingerprint: str
    human_record_id: str
    human_record_fingerprint: str
    governed_state_fingerprint: str
    checkpoint_fingerprint: str
    verified_at_utc: str
    expires_at_utc: str

    def validate_against(
        self,
        state: "ContinuityState",
        *,
        now_utc: str,
    ) -> None:
        state.validate()
        authority = state.authority
        authority.validate()
        if not isinstance(self.governed_state_fingerprint, str) or not _FP_RE.fullmatch(
            self.governed_state_fingerprint
        ):
            raise ContinuityPolicyError(
                "governed_state_fingerprint must use sha256:<64 lowercase hex>."
            )
        if not isinstance(self.checkpoint_fingerprint, str) or not _FP_RE.fullmatch(
            self.checkpoint_fingerprint
        ):
            raise ContinuityPolicyError(
                "checkpoint_fingerprint must use sha256:<64 lowercase hex>."
            )
        verified_at = _utc(self.verified_at_utc)
        expires_at = _utc(self.expires_at_utc)
        checkpoint_time = _utc(state.updated_at_utc)
        now = _utc(now_utc)
        if (
            self.github_repository != authority.github_repository
            or self.github_path != authority.github_path
            or self.github_commit_sha != authority.github_commit_sha
            or self.policy_fingerprint != authority.policy_fingerprint
            or self.human_record_id != authority.human_record_id
            or self.human_record_fingerprint != authority.human_record_fingerprint
            or self.governed_state_fingerprint
            != governed_state_fingerprint(state)
            or self.checkpoint_fingerprint != checkpoint_fingerprint(state)
        ):
            raise ContinuityPolicyError("Authority verification receipt does not match binding.")
        if verified_at < checkpoint_time:
            raise ContinuityPolicyError("Authority receipt predates the checkpoint.")
        if expires_at <= verified_at:
            raise ContinuityPolicyError("Authority receipt expiry is invalid.")
        if expires_at - verified_at > MAX_RECEIPT_VALIDITY:
            raise ContinuityPolicyError("Authority receipt validity exceeds 15 minutes.")
        if not (verified_at <= now <= expires_at):
            raise ContinuityPolicyError("Authority verification receipt is not currently valid.")


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
    previous_checkpoint_fingerprint: str | None
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
        if self.sequence == 1 and (
            self.previous_checkpoint_id is not None
            or self.previous_checkpoint_fingerprint is not None
        ):
            raise ContinuityPolicyError("The first checkpoint cannot name a predecessor.")
        if self.sequence > 1:
            if self.previous_checkpoint_id is None:
                raise ContinuityPolicyError("A successor requires previous_checkpoint_id.")
            _identifier(self.previous_checkpoint_id, "previous_checkpoint_id")
            if self.previous_checkpoint_id == self.checkpoint_id:
                raise ContinuityPolicyError("A checkpoint cannot be its own predecessor.")
            if (
                not isinstance(self.previous_checkpoint_fingerprint, str)
                or not _FP_RE.fullmatch(self.previous_checkpoint_fingerprint)
            ):
                raise ContinuityPolicyError(
                    "A successor requires previous_checkpoint_fingerprint."
                )
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


class PrivateContinuityStore(Protocol):
    privacy_class: str

    def list_checkpoints(self, user_scope_id: str) -> Iterable[Mapping[str, Any]]: ...

    def compare_and_swap_checkpoint(
        self, expected_checkpoint_id: str | None, payload: Mapping[str, Any]
    ) -> bool: ...


class AuthorityVerifier(Protocol):
    """Trusted adapter that independently verifies both authority artifacts.

    A production adapter must establish merged-main reachability, recompute the
    policy and human-record hashes, and confirm that the human record embeds the
    supplied governed-state fingerprint before returning a short-lived receipt.
    """

    def verify(
        self,
        authority: AuthorityPointers,
        governed_state_fingerprint: str,
        checkpoint_fingerprint: str,
    ) -> AuthorityVerificationReceipt: ...


def _require_private_store(store: PrivateContinuityStore) -> None:
    if getattr(store, "privacy_class", None) != "PRIVATE":
        raise ContinuityPolicyError("Continuity persistence requires a PRIVATE store adapter.")


def _verified_receipt(
    verifier: AuthorityVerifier,
    state: ContinuityState,
    *,
    now_utc: str,
) -> AuthorityVerificationReceipt:
    state.validate()
    receipt = verifier.verify(
        state.authority,
        governed_state_fingerprint(state),
        checkpoint_fingerprint(state),
    )
    if not isinstance(receipt, AuthorityVerificationReceipt):
        raise ContinuityPolicyError("Authority verifier did not return a valid receipt.")
    receipt.validate_against(state, now_utc=now_utc)
    return receipt


def _event(value: str | ContinuityEvent) -> ContinuityEvent:
    try:
        return ContinuityEvent(value)
    except (TypeError, ValueError) as exc:
        raise ContinuityPolicyError(f"Unknown continuity event: {value!r}") from exc


def select_mode(requested: str | InteractionMode | None) -> tuple[InteractionMode, bool]:
    if requested is None:
        return InteractionMode.DEVELOPMENT, False
    try:
        return InteractionMode(requested), True
    except (TypeError, ValueError) as exc:
        raise ContinuityPolicyError(f"Unknown interaction mode: {requested!r}") from exc


def checkpoint_required(event: str | ContinuityEvent) -> bool:
    return _event(event) in CHECKPOINT_EVENTS


def _successor(
    previous: ContinuityState,
    *,
    event: str | ContinuityEvent,
    approved_changes: tuple[str, ...],
    checkpoint_id: str,
    updated_at_utc: str,
    next_prompt: str,
    authority: AuthorityPointers,
    mode: InteractionMode,
    explicit: bool,
) -> ContinuityState:
    previous.validate()
    normalized_event = _event(event)
    if normalized_event not in CHECKPOINT_EVENTS:
        raise ContinuityPolicyError("The event does not permit an approved checkpoint.")
    if not isinstance(approved_changes, (list, tuple)) or isinstance(
        approved_changes, (str, bytes)
    ):
        raise ContinuityPolicyError("approved_changes must be an array of strings.")
    if any(not isinstance(item, str) or not item.strip() for item in approved_changes):
        raise ContinuityPolicyError("approved_changes must contain non-empty strings.")
    normalized = tuple(item.strip() for item in approved_changes)
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
        previous_checkpoint_fingerprint=checkpoint_fingerprint(previous),
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
    event: str | ContinuityEvent,
    approved_changes: tuple[str, ...],
    checkpoint_id: str,
    updated_at_utc: str,
    next_prompt: str,
    authority: AuthorityPointers,
) -> ContinuityState:
    normalized_event = _event(event)
    if normalized_event is ContinuityEvent.APPROVED_MODE_CHANGE:
        raise ContinuityPolicyError("Use record_mode_change for mode changes.")
    return _successor(
        previous,
        event=normalized_event,
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


def visible_resume_brief(
    state: ContinuityState,
    receipt: AuthorityVerificationReceipt,
    *,
    now_utc: str,
) -> ResumeBrief:
    state.validate()
    receipt.validate_against(state, now_utc=now_utc)
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
        "previous_checkpoint_fingerprint",
        "user_scope_id", "updated_at_utc", "authority", "mode",
        "mode_selected_explicitly", "status", "next_prompt",
        "governed_state_fingerprint",
        "checkpoint_fingerprint",
    }
    missing = sorted(required.difference(payload))
    if missing:
        raise ContinuityPolicyError("Checkpoint cannot be reconstructed; missing: " + ", ".join(missing))
    authority = payload["authority"]
    if not isinstance(authority, Mapping):
        raise ContinuityPolicyError("authority must be a mapping.")
    for key in (
        "protocol_version", "checkpoint_id", "user_scope_id", "updated_at_utc",
        "mode", "status", "next_prompt",
    ):
        if not isinstance(payload[key], str):
            raise ContinuityPolicyError(f"{key} must be a JSON string.")
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
            raw_pilot_wording=item.get("raw_pilot_wording", ""),
            ai_interpretation=item.get("ai_interpretation", ""),
        ))
    state = ContinuityState(
        protocol_version=payload["protocol_version"],
        checkpoint_id=payload["checkpoint_id"],
        sequence=payload["sequence"],
        previous_checkpoint_id=payload["previous_checkpoint_id"],
        previous_checkpoint_fingerprint=payload["previous_checkpoint_fingerprint"],
        user_scope_id=payload["user_scope_id"],
        updated_at_utc=payload["updated_at_utc"],
        authority=AuthorityPointers(
            github_repository=authority.get("github_repository", ""),
            github_path=authority.get("github_path", ""),
            github_commit_sha=authority.get("github_commit_sha", ""),
            policy_fingerprint=authority.get("policy_fingerprint", ""),
            human_record_id=authority.get("human_record_id", ""),
            human_record_fingerprint=authority.get("human_record_fingerprint", ""),
        ),
        mode=mode,
        mode_selected_explicitly=_json_bool(payload, "mode_selected_explicitly"),
        status=status,
        active_case_ref=payload.get("active_case_ref"),
        source_manifest=_strings(payload, "source_manifest"),
        controlled_facts=_strings(payload, "controlled_facts"),
        approved_changes=_strings(payload, "approved_changes"),
        superseded_positions=_strings(payload, "superseded_positions"),
        open_questions=_strings(payload, "open_questions"),
        next_prompt=payload["next_prompt"],
        private_pilot_memory=tuple(parsed_memory),
    )
    state.validate()
    stored_fingerprint = payload["governed_state_fingerprint"]
    if not isinstance(stored_fingerprint, str) or not _FP_RE.fullmatch(stored_fingerprint):
        raise ContinuityPolicyError(
            "governed_state_fingerprint must use sha256:<64 lowercase hex>."
        )
    if stored_fingerprint != governed_state_fingerprint(state):
        raise ContinuityPolicyError("Stored governed-state fingerprint does not match checkpoint.")
    stored_checkpoint_fingerprint = payload["checkpoint_fingerprint"]
    if (
        not isinstance(stored_checkpoint_fingerprint, str)
        or not _FP_RE.fullmatch(stored_checkpoint_fingerprint)
    ):
        raise ContinuityPolicyError(
            "checkpoint_fingerprint must use sha256:<64 lowercase hex>."
        )
    if stored_checkpoint_fingerprint != checkpoint_fingerprint(state):
        raise ContinuityPolicyError("Stored checkpoint fingerprint does not match checkpoint.")
    return state


def _private_payload_body(state: ContinuityState) -> dict[str, Any]:
    state.validate()
    return {
        "protocol_version": state.protocol_version,
        "checkpoint_id": state.checkpoint_id,
        "sequence": state.sequence,
        "previous_checkpoint_id": state.previous_checkpoint_id,
        "previous_checkpoint_fingerprint": state.previous_checkpoint_fingerprint,
        "user_scope_id": state.user_scope_id,
        "updated_at_utc": state.updated_at_utc,
        "authority": {
            "github_repository": state.authority.github_repository,
            "github_path": state.authority.github_path,
            "github_commit_sha": state.authority.github_commit_sha,
            "policy_fingerprint": state.authority.policy_fingerprint,
            "human_record_id": state.authority.human_record_id,
            "human_record_fingerprint": state.authority.human_record_fingerprint,
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


def governed_state_fingerprint(state: ContinuityState) -> str:
    """Hash every governed field except the separately verified human-record hash.

    Excluding the human-record hash lets the human-readable record embed this digest
    without creating a circular hash dependency. The receipt independently binds and
    verifies the human-record hash as part of the complete authority tuple.
    """

    body = _private_payload_body(state)
    authority = dict(body["authority"])
    authority.pop("human_record_fingerprint")
    body["authority"] = authority
    encoded = json.dumps(
        body,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def checkpoint_fingerprint(state: ContinuityState) -> str:
    """Hash the complete checkpoint envelope, including the human-record hash."""

    body = _private_payload_body(state)
    body["governed_state_fingerprint"] = governed_state_fingerprint(state)
    encoded = json.dumps(
        body,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def state_to_private_payload(state: ContinuityState) -> dict[str, Any]:
    body = _private_payload_body(state)
    body["governed_state_fingerprint"] = governed_state_fingerprint(state)
    body["checkpoint_fingerprint"] = checkpoint_fingerprint(state)
    return body


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
    checkpoint_ids = [item.checkpoint_id for item in chain]
    if len(set(checkpoint_ids)) != len(checkpoint_ids):
        raise ContinuityPolicyError("A checkpoint_id is reused within the chain.")
    for previous, current in zip(chain, chain[1:]):
        if current.previous_checkpoint_id != previous.checkpoint_id:
            raise ContinuityPolicyError("The predecessor chain is broken.")
        if (
            current.previous_checkpoint_fingerprint
            != checkpoint_fingerprint(previous)
        ):
            raise ContinuityPolicyError("The governed-state hash chain is broken.")
        if _utc(current.updated_at_utc) <= _utc(previous.updated_at_utc):
            raise ContinuityPolicyError("Checkpoint timestamps are not increasing.")
    return chain


def bootstrap_helpyou_session(
    user_scope_id: str,
    store: PrivateContinuityStore,
    verifier: AuthorityVerifier,
    *,
    now_utc: str,
) -> tuple[ContinuityState, ResumeBrief]:
    _require_private_store(store)
    state = _chain(user_scope_id, store.list_checkpoints(user_scope_id))[-1]
    receipt = _verified_receipt(
        verifier,
        state,
        now_utc=now_utc,
    )
    return state, visible_resume_brief(state, receipt, now_utc=now_utc)


def persist_checkpoint(
    store: PrivateContinuityStore,
    state: ContinuityState,
    verifier: AuthorityVerifier,
    *,
    now_utc: str,
) -> None:
    _require_private_store(store)
    state.validate()
    _verified_receipt(
        verifier,
        state,
        now_utc=now_utc,
    )
    existing_payloads = tuple(store.list_checkpoints(state.user_scope_id))
    if existing_payloads:
        existing_chain = _chain(state.user_scope_id, existing_payloads)
        latest = existing_chain[-1]
        if state.sequence != latest.sequence + 1:
            raise ContinuityPolicyError("Candidate sequence is not the next sequence.")
        if state.previous_checkpoint_id != latest.checkpoint_id:
            raise ContinuityPolicyError("Candidate predecessor does not match latest checkpoint.")
        if (
            state.previous_checkpoint_fingerprint
            != checkpoint_fingerprint(latest)
        ):
            raise ContinuityPolicyError(
                "Candidate governed-state predecessor does not match latest checkpoint."
            )
        if state.checkpoint_id in {item.checkpoint_id for item in existing_chain}:
            raise ContinuityPolicyError("Candidate reuses a historical checkpoint_id.")
        if _utc(state.updated_at_utc) <= _utc(latest.updated_at_utc):
            raise ContinuityPolicyError("Candidate timestamp is not later than latest checkpoint.")
        if (
            state.authority.human_record_fingerprint
            == latest.authority.human_record_fingerprint
        ):
            raise ContinuityPolicyError("Candidate does not bind a new human record.")
    elif state.sequence != 1 or state.previous_checkpoint_id is not None:
        raise ContinuityPolicyError("The first persisted checkpoint must start sequence 1.")
    candidate_payload = state_to_private_payload(state)
    _chain(state.user_scope_id, existing_payloads + (candidate_payload,))
    committed = store.compare_and_swap_checkpoint(
        state.previous_checkpoint_id, candidate_payload
    )
    if type(committed) is not bool or not committed:
        raise ContinuityPolicyError("Checkpoint compare-and-swap was rejected.")
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
        "authority_binding_present": True,
        "private_checkpoint_present": True,
    }
