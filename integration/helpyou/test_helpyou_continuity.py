from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import traceback
import unittest

from helpyou_continuity import (
    APPROVED_DEFAULTS_V1,
    AuthorityPointers,
    AuthorityVerificationReceipt,
    CheckpointStatus,
    CommittedHeadVerificationReceipt,
    ContinuityEvent,
    ContinuityPolicyError,
    ContinuityRecoveryError,
    ContinuityState,
    InteractionMode,
    PilotMemoryPair,
    VerificationLayerFailure,
    bootstrap_helpyou_session,
    checkpoint_fingerprint,
    checkpoint_required,
    facilitation_sequence,
    governed_state_fingerprint,
    load_checkpoint,
    persist_checkpoint,
    public_checkpoint_projection,
    record_approved_bundle,
    record_mode_change,
    record_status_change,
    select_mode,
    state_to_private_payload,
)

NOW_UTC = "2026-08-27T03:00:00Z"


class FixedClock:
    def now_utc(self):
        return NOW_UTC


FIXED_CLOCK = FixedClock()


class FractionalClock:
    def now_utc(self):
        return "2026-08-27T03:00:00.600000Z"


EXPECTED_DEFAULTS = (
    "D1: GitHub protocol plus persistent human-readable authority",
    "D2: checkpoint after every approved material change",
    "D3: automatic load with a visible status brief",
    "D4: Development Mode unless Assessment or Research is explicitly selected",
)


class MemoryStore:
    privacy_class = "PRIVATE"

    def __init__(self, payloads=(), *, drop_writes=False):
        self.payloads = [deepcopy(item) for item in payloads]
        self.drop_writes = drop_writes
        self.cas_calls = 0

    def list_checkpoints(self, user_scope_id):
        return deepcopy(self.payloads)

    def compare_and_swap_checkpoint(
        self, expected_checkpoint_id, expected_checkpoint_fingerprint, payload
    ):
        self.cas_calls += 1
        if self.drop_writes:
            return False
        latest = max(self.payloads, key=lambda item: item["sequence"], default=None)
        current_id = latest["checkpoint_id"] if latest else None
        current_fingerprint = latest["checkpoint_fingerprint"] if latest else None
        if (
            current_id != expected_checkpoint_id
            or current_fingerprint != expected_checkpoint_fingerprint
        ):
            return False
        self.payloads.append(deepcopy(payload))
        return True


class HeadRegistry:
    def __init__(self, payload=None):
        self.head = (0, None, None)
        if payload is not None:
            self.advance(payload)

    def advance(self, payload):
        self.head = (
            payload["sequence"],
            payload["checkpoint_id"],
            payload["checkpoint_fingerprint"],
        )


class RegistryStore(MemoryStore):
    def __init__(self, registry, payloads=(), *, advance_head=True):
        super().__init__(payloads)
        self.registry = registry
        self.advance_head = advance_head

    def compare_and_swap_checkpoint(
        self, expected_checkpoint_id, expected_checkpoint_fingerprint, payload
    ):
        committed = super().compare_and_swap_checkpoint(
            expected_checkpoint_id, expected_checkpoint_fingerprint, payload
        )
        if committed and self.advance_head:
            self.registry.advance(payload)
        return committed


class PublicStore(MemoryStore):
    privacy_class = "PUBLIC"


class RaceStore(MemoryStore):
    def __init__(self, payloads, competing_payload):
        super().__init__(payloads)
        self.competing_payload = deepcopy(competing_payload)

    def compare_and_swap_checkpoint(
        self, expected_checkpoint_id, expected_checkpoint_fingerprint, payload
    ):
        self.payloads.append(deepcopy(self.competing_payload))
        return super().compare_and_swap_checkpoint(
            expected_checkpoint_id, expected_checkpoint_fingerprint, payload
        )


class FastFollowStore(MemoryStore):
    def __init__(self, payloads, follower_payload):
        super().__init__(payloads)
        self.follower_payload = deepcopy(follower_payload)

    def compare_and_swap_checkpoint(
        self, expected_checkpoint_id, expected_checkpoint_fingerprint, payload
    ):
        committed = super().compare_and_swap_checkpoint(
            expected_checkpoint_id, expected_checkpoint_fingerprint, payload
        )
        if committed:
            self.payloads.append(deepcopy(self.follower_payload))
        return committed


class SameCandidateRaceStore(MemoryStore):
    def compare_and_swap_checkpoint(
        self, expected_checkpoint_id, expected_checkpoint_fingerprint, payload
    ):
        self.payloads.append(deepcopy(payload))
        return super().compare_and_swap_checkpoint(
            expected_checkpoint_id, expected_checkpoint_fingerprint, payload
        )


class FollowBetweenListAndHeadStore(RegistryStore):
    def __init__(self, registry, payloads, follower_payload):
        super().__init__(registry, payloads)
        self.follower_payload = deepcopy(follower_payload)
        self.list_calls = 0

    def list_checkpoints(self, user_scope_id):
        self.list_calls += 1
        snapshot = super().list_checkpoints(user_scope_id)
        if self.list_calls == 2:
            self.payloads.append(deepcopy(self.follower_payload))
            self.registry.advance(self.follower_payload)
        return snapshot


class TestVerifier:
    def __init__(
        self,
        *,
        mismatch=False,
        repository=None,
        path=None,
        expected_governed_fingerprint=None,
        expected_checkpoint_fingerprint=None,
        head_override=None,
        authority_layer_failure=None,
        head_layer_failure=None,
        verified_at_utc="2026-08-27T02:55:00Z",
        expires_at_utc="2026-08-27T03:10:00Z",
    ):
        self.mismatch = mismatch
        self.repository = repository
        self.path = path
        self.expected_governed_fingerprint = expected_governed_fingerprint
        self.expected_checkpoint_fingerprint = expected_checkpoint_fingerprint
        self.head_override = head_override
        self.authority_layer_failure = authority_layer_failure
        self.head_layer_failure = head_layer_failure
        self.verified_at_utc = verified_at_utc
        self.expires_at_utc = expires_at_utc

    def verify(self, authority, governed_fingerprint, checkpoint_envelope_fingerprint):
        if self.authority_layer_failure is not None:
            raise VerificationLayerFailure(**self.authority_layer_failure)
        return AuthorityVerificationReceipt(
            github_repository=self.repository or authority.github_repository,
            github_path=self.path or authority.github_path,
            github_commit_sha=("f" * 40 if self.mismatch else authority.github_commit_sha),
            policy_fingerprint=authority.policy_fingerprint,
            human_record_id=authority.human_record_id,
            human_record_fingerprint=authority.human_record_fingerprint,
            governed_state_fingerprint=(
                self.expected_governed_fingerprint or governed_fingerprint
            ),
            checkpoint_fingerprint=(
                self.expected_checkpoint_fingerprint
                or checkpoint_envelope_fingerprint
            ),
            verified_at_utc=self.verified_at_utc,
            expires_at_utc=self.expires_at_utc,
        )

    def verify_current_head(
        self,
        user_scope_id,
        requested_sequence,
        requested_checkpoint_id,
        requested_checkpoint_fingerprint,
    ):
        if self.head_layer_failure is not None:
            raise VerificationLayerFailure(**self.head_layer_failure)
        sequence, checkpoint_id, fingerprint = self.head_override or (
            requested_sequence,
            requested_checkpoint_id,
            requested_checkpoint_fingerprint,
        )
        return CommittedHeadVerificationReceipt(
            user_scope_id=user_scope_id,
            sequence=sequence,
            checkpoint_id=checkpoint_id,
            checkpoint_fingerprint=fingerprint,
            verified_at_utc=self.verified_at_utc,
            expires_at_utc=self.expires_at_utc,
        )


class RegistryVerifier(TestVerifier):
    def __init__(self, registry, **kwargs):
        super().__init__(**kwargs)
        self.registry = registry

    def verify_current_head(
        self,
        user_scope_id,
        requested_sequence,
        requested_checkpoint_id,
        requested_checkpoint_fingerprint,
    ):
        sequence, checkpoint_id, fingerprint = self.registry.head
        return CommittedHeadVerificationReceipt(
            user_scope_id=user_scope_id,
            sequence=sequence,
            checkpoint_id=checkpoint_id,
            checkpoint_fingerprint=fingerprint,
            verified_at_utc=self.verified_at_utc,
            expires_at_utc=self.expires_at_utc,
        )


class BadLatestAuthorityVerifier(TestVerifier):
    def __init__(self, bad_human_record_id):
        super().__init__()
        self.bad_human_record_id = bad_human_record_id

    def verify(self, authority, governed_fingerprint, checkpoint_envelope_fingerprint):
        receipt = super().verify(
            authority, governed_fingerprint, checkpoint_envelope_fingerprint
        )
        if authority.human_record_id == self.bad_human_record_id:
            return replace(receipt, github_commit_sha="f" * 40)
        return receipt


class OrderingClock:
    def __init__(self, calls):
        self.calls = calls

    def now_utc(self):
        self.calls.append("clock")
        return "2026-08-27T03:00:02Z"


class OrderingVerifier(TestVerifier):
    def __init__(self, calls):
        super().__init__(
            verified_at_utc="2026-08-27T03:00:01Z",
            expires_at_utc="2026-08-27T03:10:01Z",
        )
        self.calls = calls

    def verify(self, authority, governed_fingerprint, checkpoint_envelope_fingerprint):
        self.calls.append("verifier")
        return super().verify(
            authority, governed_fingerprint, checkpoint_envelope_fingerprint
        )

    def verify_current_head(
        self,
        user_scope_id,
        requested_sequence,
        requested_checkpoint_id,
        requested_checkpoint_fingerprint,
    ):
        self.calls.append("head_verifier")
        return super().verify_current_head(
            user_scope_id,
            requested_sequence,
            requested_checkpoint_id,
            requested_checkpoint_fingerprint,
        )


class HelpyouContinuityV2Tests(unittest.TestCase):
    def authority(self, marker="a") -> AuthorityPointers:
        return AuthorityPointers(
            github_repository="Easyeye123/pilotdriven-ODSS",
            github_path="docs/helpyou/HELPYOU_CONTINUITY_PROTOCOL_V1.md",
            github_commit_sha="a" * 40,
            policy_fingerprint="sha256:" + "b" * 64,
            human_record_id=f"HCP-{marker.upper()}001",
            human_record_fingerprint="sha256:" + marker * 64,
        )

    def state(self) -> ContinuityState:
        return ContinuityState(
            protocol_version="1.0",
            checkpoint_id="HCP-001",
            sequence=1,
            previous_checkpoint_id=None,
            previous_checkpoint_fingerprint=None,
            user_scope_id="user_12345678",
            updated_at_utc="2026-08-27T00:00:00Z",
            authority=self.authority("c"),
            transition_id="EVT-INIT-001",
            transition_event=ContinuityEvent.INITIALIZATION,
            transition_approved_changes=(),
            approval_evidence_ref="fixture:initialization",
            applied_transition_ids=("EVT-INIT-001",),
            applied_human_record_ids=("HCP-C001",),
            active_case_ref="private-case-reference",
            next_prompt="Continue the controlled case review.",
        )

    def incomplete_state(
        self,
        unavailable_layers=("hosted startup integration",),
        reason_code="RUNTIME_INTEGRATION_PENDING",
    ) -> ContinuityState:
        change = "Continuity gap recorded."
        return replace(
            self.state(),
            transition_event=ContinuityEvent.APPROVED_STATUS_CHANGE,
            transition_approved_changes=(change,),
            approved_changes=(change,),
            status=CheckpointStatus.INCOMPLETE,
            status_reason_code=reason_code,
            unavailable_layers=unavailable_layers,
            safe_to_resume=False,
        )

    def successor(self) -> ContinuityState:
        return record_approved_bundle(
            self.state(),
            event=ContinuityEvent.APPROVED_MATERIAL_CHANGE,
            approved_changes=APPROVED_DEFAULTS_V1,
            transition_id="EVT-DEFAULTS-001",
            approval_evidence_ref="fixture:defaults-approval",
            checkpoint_id="HCP-002",
            updated_at_utc="2026-08-27T01:00:00Z",
            next_prompt="Calibrate Development Mode prompting.",
            authority=self.authority("d"),
        )

    def third(self) -> ContinuityState:
        return record_approved_bundle(
            self.successor(),
            event=ContinuityEvent.APPROVED_MATERIAL_CHANGE,
            approved_changes=("Third approved change",),
            transition_id="EVT-THIRD-001",
            approval_evidence_ref="fixture:third-approval",
            checkpoint_id="HCP-003",
            updated_at_utc="2026-08-27T02:00:00Z",
            next_prompt="Continue after the third change.",
            authority=self.authority("e"),
        )

    def test_four_defaults_are_exactly_hardcoded(self):
        self.assertEqual(APPROVED_DEFAULTS_V1, EXPECTED_DEFAULTS)

    def test_development_is_default(self):
        self.assertEqual(select_mode(None), (InteractionMode.DEVELOPMENT, False))

    def test_non_default_mode_requires_explicit_selection(self):
        self.assertEqual(select_mode("assessment"), (InteractionMode.ASSESSMENT, True))

    def test_facilitator_word_does_not_infer_mode(self):
        with self.assertRaises(ContinuityPolicyError):
            select_mode("facilitator")

    def test_all_approved_events_require_checkpoint(self):
        self.assertTrue(checkpoint_required(ContinuityEvent.APPROVED_MATERIAL_CHANGE))
        self.assertTrue(checkpoint_required(ContinuityEvent.APPROVED_SOURCE_REVISION))
        self.assertTrue(checkpoint_required(ContinuityEvent.APPROVED_MODE_CHANGE))
        self.assertTrue(checkpoint_required(ContinuityEvent.APPROVED_MEMORY_CHANGE))
        self.assertTrue(checkpoint_required(ContinuityEvent.APPROVED_STATUS_CHANGE))
        self.assertFalse(checkpoint_required(ContinuityEvent.DRAFT_CHANGE))

    def test_four_item_bundle_creates_one_successor(self):
        result = self.successor()
        self.assertEqual(result.sequence, 2)
        self.assertEqual(result.previous_checkpoint_id, "HCP-001")
        self.assertEqual(
            result.previous_checkpoint_fingerprint,
            checkpoint_fingerprint(self.state()),
        )
        self.assertEqual(result.approved_changes, EXPECTED_DEFAULTS)

    def test_bundle_replay_is_idempotent(self):
        result = self.successor()
        replay = record_approved_bundle(
            result,
            event=ContinuityEvent.APPROVED_MATERIAL_CHANGE,
            approved_changes=APPROVED_DEFAULTS_V1,
            transition_id="EVT-DEFAULTS-001",
            approval_evidence_ref="fixture:defaults-approval",
            checkpoint_id="HCP-003",
            updated_at_utc="2026-08-27T02:00:00Z",
            next_prompt="Different prompt",
            authority=self.authority("e"),
        )
        self.assertIs(replay, result)

    def test_repeated_change_text_with_new_transition_id_creates_checkpoint(self):
        second = self.successor()
        third = record_approved_bundle(
            second,
            event=ContinuityEvent.APPROVED_SOURCE_REVISION,
            approved_changes=APPROVED_DEFAULTS_V1,
            transition_id="EVT-DEFAULTS-002",
            approval_evidence_ref="fixture:new-source-approval",
            checkpoint_id="HCP-003",
            updated_at_utc="2026-08-27T02:00:00Z",
            next_prompt="Continue with the revised source.",
            authority=self.authority("e"),
        )
        self.assertEqual(third.sequence, 3)
        self.assertEqual(third.approved_changes, second.approved_changes)
        self.assertEqual(third.transition_id, "EVT-DEFAULTS-002")

    def test_transition_id_collision_with_different_content_fails(self):
        with self.assertRaisesRegex(ContinuityPolicyError, "transition_id collides"):
            record_approved_bundle(
                self.successor(),
                event=ContinuityEvent.APPROVED_MATERIAL_CHANGE,
                approved_changes=("Different content",),
                transition_id="EVT-DEFAULTS-001",
                approval_evidence_ref="fixture:defaults-approval",
                checkpoint_id="HCP-003",
                updated_at_utc="2026-08-27T02:00:00Z",
                next_prompt="Continue.",
                authority=self.authority("e"),
            )

    def test_human_record_id_cannot_be_reused_across_chain(self):
        with self.assertRaisesRegex(ContinuityPolicyError, "historical authority"):
            record_approved_bundle(
                self.successor(),
                event=ContinuityEvent.APPROVED_MATERIAL_CHANGE,
                approved_changes=("Third approved change",),
                transition_id="EVT-THIRD-REUSE",
                approval_evidence_ref="fixture:third-approval",
                checkpoint_id="HCP-003",
                updated_at_utc="2026-08-27T02:00:00Z",
                next_prompt="Continue.",
                authority=self.authority("c"),
            )

    def test_successor_rejects_reused_id(self):
        with self.assertRaisesRegex(ContinuityPolicyError, "new checkpoint_id"):
            record_approved_bundle(
                self.state(), event=ContinuityEvent.APPROVED_MATERIAL_CHANGE,
                approved_changes=("Approved change",), checkpoint_id="HCP-001",
                transition_id="EVT-CHANGE-001",
                approval_evidence_ref="fixture:change-approval",
                updated_at_utc="2026-08-27T01:00:00Z", next_prompt="Continue.",
                authority=self.authority("d"),
            )

    def test_successor_rejects_stale_time(self):
        with self.assertRaisesRegex(ContinuityPolicyError, "timestamp"):
            record_approved_bundle(
                self.state(), event=ContinuityEvent.APPROVED_MATERIAL_CHANGE,
                approved_changes=("Approved change",), checkpoint_id="HCP-002",
                transition_id="EVT-CHANGE-002",
                approval_evidence_ref="fixture:change-approval",
                updated_at_utc="2026-08-26T23:00:00Z", next_prompt="Continue.",
                authority=self.authority("d"),
            )

    def test_successor_requires_new_human_record(self):
        with self.assertRaisesRegex(ContinuityPolicyError, "historical authority"):
            record_approved_bundle(
                self.state(), event=ContinuityEvent.APPROVED_MATERIAL_CHANGE,
                approved_changes=("Approved change",), checkpoint_id="HCP-002",
                transition_id="EVT-CHANGE-003",
                approval_evidence_ref="fixture:change-approval",
                updated_at_utc="2026-08-27T01:00:00Z", next_prompt="Continue.",
                authority=self.authority("c"),
            )

    def test_mode_change_changes_the_mode(self):
        result = record_mode_change(
            self.state(), new_mode="assessment", approved_change="Assessment selected.",
            transition_id="EVT-MODE-001",
            approval_evidence_ref="fixture:mode-approval",
            checkpoint_id="HCP-002", updated_at_utc="2026-08-27T01:00:00Z",
            next_prompt="Begin assessment.", authority=self.authority("d"),
        )
        self.assertIs(result.mode, InteractionMode.ASSESSMENT)
        self.assertTrue(result.mode_selected_explicitly)

    def test_generic_bundle_rejects_mode_change_event(self):
        with self.assertRaisesRegex(ContinuityPolicyError, "record_mode_change"):
            record_approved_bundle(
                self.state(), event=ContinuityEvent.APPROVED_MODE_CHANGE,
                approved_changes=("Assessment selected.",), checkpoint_id="HCP-002",
                transition_id="EVT-MODE-002",
                approval_evidence_ref="fixture:mode-approval",
                updated_at_utc="2026-08-27T01:00:00Z", next_prompt="Begin.",
                authority=self.authority("d"),
            )

    def test_generic_bundle_rejects_status_change_event(self):
        with self.assertRaisesRegex(ContinuityPolicyError, "record_status_change"):
            record_approved_bundle(
                self.state(), event=ContinuityEvent.APPROVED_STATUS_CHANGE,
                approved_changes=("Runtime integration became unavailable.",),
                checkpoint_id="HCP-002", transition_id="EVT-STATUS-001",
                approval_evidence_ref="fixture:status-approval",
                updated_at_utc="2026-08-27T01:00:00Z", next_prompt="Recover runtime.",
                authority=self.authority("d"),
            )

    def test_status_change_records_complete_gap_metadata(self):
        result = record_status_change(
            self.state(),
            new_status=CheckpointStatus.INCOMPLETE,
            reason_code="RUNTIME_INTEGRATION_PENDING",
            unavailable_layers=("hosted startup integration",),
            approved_change="Runtime integration gap recorded.",
            transition_id="EVT-STATUS-002",
            approval_evidence_ref="fixture:status-approval",
            checkpoint_id="HCP-002",
            updated_at_utc="2026-08-27T01:00:00Z",
            next_prompt="Complete hosted startup integration.",
            authority=self.authority("d"),
        )
        self.assertIs(result.status, CheckpointStatus.INCOMPLETE)
        self.assertEqual(result.status_reason_code, "RUNTIME_INTEGRATION_PENDING")
        self.assertFalse(result.safe_to_resume)

    def test_activation_cannot_silently_discard_supplied_unresolved_gap(self):
        incomplete = record_status_change(
            self.state(),
            new_status=CheckpointStatus.INCOMPLETE,
            reason_code="RUNTIME_INTEGRATION_PENDING",
            unavailable_layers=("hosted startup integration",),
            approved_change="Runtime integration gap recorded.",
            transition_id="EVT-STATUS-003",
            approval_evidence_ref="fixture:status-gap-approval",
            checkpoint_id="HCP-002",
            updated_at_utc="2026-08-27T01:00:00Z",
            next_prompt="Complete hosted startup integration.",
            authority=self.authority("d"),
        )
        with self.assertRaisesRegex(ContinuityPolicyError, "cannot discard"):
            record_status_change(
                incomplete,
                new_status=CheckpointStatus.ACTIVE,
                reason_code="RUNTIME_INTEGRATION_PENDING",
                unavailable_layers=("hosted startup integration",),
                approved_change="Activate continuity.",
                transition_id="EVT-STATUS-004",
                approval_evidence_ref="fixture:status-activation-approval",
                checkpoint_id="HCP-003",
                updated_at_utc="2026-08-27T02:00:00Z",
                next_prompt="Resume.",
                authority=self.authority("e"),
            )

    def test_incomplete_status_requires_gap_metadata(self):
        with self.assertRaisesRegex(ContinuityPolicyError, "status_reason_code"):
            replace(self.state(), status=CheckpointStatus.INCOMPLETE).validate()

    def test_incomplete_status_requires_controlled_reason_code(self):
        with self.assertRaisesRegex(ContinuityPolicyError, "controlled recovery"):
            replace(
                self.state(),
                status=CheckpointStatus.INCOMPLETE,
                status_reason_code="SECRET_TOKEN_AKIA1234567890",
                unavailable_layers=("hosted startup integration",),
                safe_to_resume=False,
            ).validate()

    def test_genesis_status_change_cannot_be_default_active_noop(self):
        with self.assertRaisesRegex(ContinuityPolicyError, "non-default INCOMPLETE"):
            replace(
                self.state(),
                transition_event=ContinuityEvent.APPROVED_STATUS_CHANGE,
                transition_approved_changes=("Activate continuity.",),
                approved_changes=("Activate continuity.",),
            ).validate()

    def test_genesis_events_cannot_smuggle_orthogonal_mode_or_status(self):
        gap = self.incomplete_state()
        with self.assertRaisesRegex(ContinuityPolicyError, "Development Mode"):
            replace(
                gap,
                mode=InteractionMode.ASSESSMENT,
                mode_selected_explicitly=True,
            ).validate()
        with self.assertRaisesRegex(ContinuityPolicyError, "default ACTIVE"):
            replace(
                gap,
                transition_event=ContinuityEvent.APPROVED_MATERIAL_CHANGE,
            ).validate()
        with self.assertRaisesRegex(ContinuityPolicyError, "default ACTIVE"):
            replace(
                gap,
                transition_event=ContinuityEvent.APPROVED_MODE_CHANGE,
                mode=InteractionMode.ASSESSMENT,
                mode_selected_explicitly=True,
            ).validate()
        with self.assertRaisesRegex(ContinuityPolicyError, "non-default mode"):
            replace(
                self.state(),
                transition_event=ContinuityEvent.APPROVED_MODE_CHANGE,
                transition_approved_changes=("Development selected.",),
                approved_changes=("Development selected.",),
                mode_selected_explicitly=True,
            ).validate()

    def test_superseded_status_is_not_persistable(self):
        with self.assertRaisesRegex(ContinuityPolicyError, "not a persistable"):
            replace(self.state(), status=CheckpointStatus.SUPERSEDED).validate()

    def test_unsupported_protocol_version_fails_closed(self):
        payload = state_to_private_payload(self.state())
        payload["protocol_version"] = "999.999"
        with self.assertRaisesRegex(ContinuityPolicyError, "supported version 1.0"):
            load_checkpoint(payload)

    def test_serialized_mode_event_cannot_bypass_mode_gate(self):
        with self.assertRaisesRegex(ContinuityPolicyError, "record_mode_change"):
            record_approved_bundle(
                self.state(), event="approved_mode_change",
                approved_changes=("Assessment selected.",), checkpoint_id="HCP-002",
                transition_id="EVT-MODE-003",
                approval_evidence_ref="fixture:mode-approval",
                updated_at_utc="2026-08-27T01:00:00Z", next_prompt="Begin.",
                authority=self.authority("d"),
            )

    def test_mutation_rejects_string_change_collection(self):
        with self.assertRaisesRegex(ContinuityPolicyError, "array of strings"):
            record_approved_bundle(
                self.state(), event=ContinuityEvent.APPROVED_MATERIAL_CHANGE,
                approved_changes="ABC", checkpoint_id="HCP-002",
                transition_id="EVT-CHANGE-004",
                approval_evidence_ref="fixture:change-approval",
                updated_at_utc="2026-08-27T01:00:00Z", next_prompt="Continue.",
                authority=self.authority("d"),
            )

    def test_string_false_is_not_a_verified_boolean(self):
        payload = state_to_private_payload(self.state())
        payload["mode_selected_explicitly"] = "false"
        with self.assertRaisesRegex(ContinuityPolicyError, "JSON boolean"):
            load_checkpoint(payload)

    def test_invalid_sha_and_fingerprint_fail(self):
        payload = state_to_private_payload(self.state())
        payload["authority"]["github_commit_sha"] = "not-a-sha"
        with self.assertRaisesRegex(ContinuityPolicyError, "40 lowercase hex"):
            load_checkpoint(payload)
        payload = state_to_private_payload(self.state())
        payload["authority"]["policy_fingerprint"] = "sha256:bad"
        with self.assertRaisesRegex(ContinuityPolicyError, "64 lowercase hex"):
            load_checkpoint(payload)

    def test_authority_paths_are_canonical_and_traversal_safe(self):
        state = self.state()
        for repository in ("../repo", "owner/.."):
            with self.subTest(repository=repository):
                with self.assertRaisesRegex(ContinuityPolicyError, "noncanonical"):
                    replace(
                        state,
                        authority=replace(
                            state.authority,
                            github_repository=repository,
                        ),
                    ).validate()
        for path in (
            "docs\\..\\secret",
            "docs/../secret",
            "docs/./protocol.md",
            "docs//protocol.md",
            "docs/\rsecret",
            "docs/protocol.md ",
        ):
            with self.subTest(path=repr(path)):
                with self.assertRaisesRegex(ContinuityPolicyError, "safe repository path"):
                    replace(
                        state,
                        authority=replace(state.authority, github_path=path),
                    ).validate()

    def test_invalid_timestamp_fails(self):
        payload = state_to_private_payload(self.state())
        payload["updated_at_utc"] = "not-a-dateZ"
        with self.assertRaisesRegex(ContinuityPolicyError, "ISO-8601"):
            load_checkpoint(payload)

    def test_json_scalars_are_not_coerced_to_strings(self):
        for key, invalid in (
            ("protocol_version", 1.0),
            ("checkpoint_id", 12345678),
            ("user_scope_id", 12345678),
            ("updated_at_utc", 20260827),
            ("mode", 1),
            ("status", True),
            ("next_prompt", 7),
        ):
            with self.subTest(key=key):
                payload = state_to_private_payload(self.state())
                payload[key] = invalid
                with self.assertRaisesRegex(ContinuityPolicyError, "JSON string"):
                    load_checkpoint(payload)

    def test_private_memory_scalars_are_not_coerced(self):
        state = replace(
            self.state(),
            private_pilot_memory=(PilotMemoryPair(
                raw_pilot_wording="Private exact wording",
                ai_interpretation="Private interpreted meaning",
            ),),
        )
        payload = state_to_private_payload(state)
        payload["private_pilot_memory"][0]["raw_pilot_wording"] = 123
        with self.assertRaisesRegex(ContinuityPolicyError, "raw_pilot_wording"):
            load_checkpoint(payload)

    def test_first_checkpoint_cannot_smuggle_approved_history(self):
        bad = replace(
            self.state(),
            transition_event=ContinuityEvent.APPROVED_MATERIAL_CHANGE,
            transition_approved_changes=("Approved A",),
            approved_changes=("Approved A", "Unapproved extra"),
        )
        with self.assertRaisesRegex(ContinuityPolicyError, "extra history"):
            bad.validate()

    def test_first_non_mode_checkpoint_cannot_select_assessment(self):
        bad = replace(
            self.state(),
            transition_event=ContinuityEvent.APPROVED_MATERIAL_CHANGE,
            transition_approved_changes=("Approved A",),
            approved_changes=("Approved A",),
            mode=InteractionMode.ASSESSMENT,
            mode_selected_explicitly=True,
        )
        with self.assertRaisesRegex(ContinuityPolicyError, "non-mode first checkpoint"):
            bad.validate()

    def test_string_cannot_become_tuple_of_characters(self):
        payload = state_to_private_payload(self.state())
        payload["approved_changes"] = "approved"
        with self.assertRaisesRegex(ContinuityPolicyError, "array of strings"):
            load_checkpoint(payload)

    def test_unknown_checkpoint_and_authority_fields_fail_closed(self):
        payload = state_to_private_payload(self.state())
        payload["verified"] = True
        with self.assertRaisesRegex(ContinuityPolicyError, "unknown fields"):
            load_checkpoint(payload)
        payload = state_to_private_payload(self.state())
        payload["authority"]["verified"] = True
        with self.assertRaisesRegex(ContinuityPolicyError, "authority fields are invalid"):
            load_checkpoint(payload)

    def test_unknown_private_memory_fields_fail_closed(self):
        state = replace(
            self.state(),
            private_pilot_memory=(PilotMemoryPair(
                raw_pilot_wording="Private exact wording",
                ai_interpretation="Private interpreted meaning",
            ),),
        )
        payload = state_to_private_payload(state)
        payload["private_pilot_memory"][0]["verified"] = True
        with self.assertRaisesRegex(ContinuityPolicyError, "memory fields are invalid"):
            load_checkpoint(payload)

    def test_tuple_strings_require_canonical_whitespace(self):
        bad = replace(self.state(), controlled_facts=(" padded fact ",))
        with self.assertRaisesRegex(ContinuityPolicyError, "canonical whitespace"):
            bad.validate()

    def test_stored_governed_fingerprint_detects_tamper(self):
        payload = state_to_private_payload(self.state())
        payload["next_prompt"] = "Tampered prompt"
        with self.assertRaisesRegex(ContinuityPolicyError, "fingerprint does not match"):
            load_checkpoint(payload)

    def test_private_memory_round_trips(self):
        state = replace(
            self.state(),
            private_pilot_memory=(PilotMemoryPair(
                raw_pilot_wording="Private exact wording",
                ai_interpretation="Private interpreted meaning",
            ),),
        )
        self.assertEqual(load_checkpoint(state_to_private_payload(state)), state)

    def test_bootstrap_loads_latest_and_returns_brief(self):
        first, second = self.state(), self.successor()
        state, brief = bootstrap_helpyou_session(
            first.user_scope_id,
            MemoryStore((state_to_private_payload(first), state_to_private_payload(second))),
            TestVerifier(),
            trusted_clock=FIXED_CLOCK,
        )
        self.assertEqual(state, second)
        self.assertEqual(brief.checkpoint_id, second.checkpoint_id)
        self.assertEqual(brief.mode, "development")

    def test_trusted_clock_is_read_after_verifier_returns(self):
        calls = []
        state = self.state()
        bootstrap_helpyou_session(
            state.user_scope_id,
            MemoryStore((state_to_private_payload(state),)),
            OrderingVerifier(calls),
            trusted_clock=OrderingClock(calls),
        )
        self.assertEqual(
            calls,
            ["head_verifier", "clock", "verifier", "clock"],
        )

    def test_fractional_receipt_time_is_not_rejected_by_clock_precision(self):
        state = self.state()
        verifier = TestVerifier(
            verified_at_utc="2026-08-27T03:00:00.500000Z",
            expires_at_utc="2026-08-27T03:10:00.500000Z",
        )
        bootstrap_helpyou_session(
            state.user_scope_id,
            MemoryStore((state_to_private_payload(state),)),
            verifier,
            trusted_clock=FractionalClock(),
        )

    def test_resume_brief_uses_current_transition_not_cumulative_tail(self):
        second = self.successor()
        repeated_first_change = record_approved_bundle(
            second,
            event=ContinuityEvent.APPROVED_SOURCE_REVISION,
            approved_changes=(APPROVED_DEFAULTS_V1[0],),
            transition_id="EVT-REPEAT-001",
            approval_evidence_ref="fixture:repeat-approval",
            checkpoint_id="HCP-003",
            updated_at_utc="2026-08-27T02:00:00Z",
            next_prompt="Continue after repeated wording.",
            authority=self.authority("e"),
        )
        _, brief = bootstrap_helpyou_session(
            second.user_scope_id,
            MemoryStore((
                state_to_private_payload(self.state()),
                state_to_private_payload(second),
                state_to_private_payload(repeated_first_change),
            )),
            TestVerifier(),
            trusted_clock=FIXED_CLOCK,
        )
        self.assertEqual(brief.last_approved_change, APPROVED_DEFAULTS_V1[0])
        self.assertEqual(brief.last_transition_id, "EVT-REPEAT-001")

    def test_bootstrap_rejects_mismatched_authority_receipt(self):
        state = self.state()
        store = MemoryStore((state_to_private_payload(state),))
        with self.assertRaisesRegex(ContinuityRecoveryError, "INCOMPLETE") as caught:
            bootstrap_helpyou_session(
                state.user_scope_id, store, TestVerifier(mismatch=True),
                trusted_clock=FIXED_CLOCK,
            )
        brief = caught.exception.recovery_brief
        self.assertEqual(brief.status, "INCOMPLETE")
        self.assertEqual(brief.reason_code, "AUTHORITY_UNVERIFIED")
        self.assertEqual(
            brief.recovered_layers,
            (
                "private checkpoint store",
                "private checkpoint candidate",
                "verified private checkpoint chain",
                "trusted monotonic head",
                "trusted clock",
                "trusted authority verifier",
            ),
        )
        self.assertFalse(brief.safe_to_resume)

    def test_bootstrap_missing_checkpoint_returns_structured_incomplete_brief(self):
        with self.assertRaisesRegex(ContinuityRecoveryError, "INCOMPLETE") as caught:
            bootstrap_helpyou_session(
                "user_12345678", MemoryStore(), TestVerifier(),
                trusted_clock=FIXED_CLOCK,
            )
        brief = caught.exception.recovery_brief
        self.assertEqual(brief.status, "INCOMPLETE")
        self.assertEqual(brief.reason_code, "CHECKPOINT_NOT_FOUND")
        self.assertEqual(brief.recovered_layers, ("private checkpoint store",))
        self.assertEqual(brief.unavailable_layers, ("private checkpoint candidate",))
        self.assertFalse(brief.safe_to_resume)

    def test_bootstrap_validates_user_scope_before_store_io(self):
        class TrackingStore(MemoryStore):
            def __init__(self):
                super().__init__()
                self.list_calls = 0

            def list_checkpoints(self, user_scope_id):
                self.list_calls += 1
                return super().list_checkpoints(user_scope_id)

        store = TrackingStore()
        with self.assertRaisesRegex(ContinuityPolicyError, "pseudonymous"):
            bootstrap_helpyou_session(
                "INVALID/PRIVATE/SCOPE",
                store,
                TestVerifier(),
                trusted_clock=FIXED_CLOCK,
            )
        self.assertEqual(store.list_calls, 0)

    def test_verified_incomplete_checkpoint_is_gated_not_resumed(self):
        state = self.incomplete_state()
        with self.assertRaises(ContinuityRecoveryError) as caught:
            bootstrap_helpyou_session(
                state.user_scope_id,
                MemoryStore((state_to_private_payload(state),)),
                TestVerifier(),
                trusted_clock=FIXED_CLOCK,
            )
        brief = caught.exception.recovery_brief
        self.assertEqual(brief.reason_code, "RUNTIME_INTEGRATION_PENDING")
        self.assertEqual(brief.unavailable_layers, ("hosted startup integration",))
        self.assertFalse(brief.safe_to_resume)

    def test_verified_recorded_authority_gaps_require_status_clearance(self):
        for recorded_layer, reason_code in (
            ("trusted monotonic head", "RUNTIME_INTEGRATION_PENDING"),
            ("GitHub protocol authority", "GITHUB_AUTHORITY_UNAVAILABLE"),
            (
                "human-readable checkpoint authority",
                "HUMAN_RECORD_UNAVAILABLE",
            ),
            ("trusted authority verifier", "RUNTIME_INTEGRATION_PENDING"),
        ):
            with self.subTest(recorded_layer=recorded_layer):
                state = self.incomplete_state(
                    unavailable_layers=(recorded_layer,),
                    reason_code=reason_code,
                )
                with self.assertRaises(ContinuityRecoveryError) as caught:
                    bootstrap_helpyou_session(
                        state.user_scope_id,
                        MemoryStore((state_to_private_payload(state),)),
                        TestVerifier(),
                        trusted_clock=FIXED_CLOCK,
                    )
                brief = caught.exception.recovery_brief
                self.assertEqual(brief.reason_code, "STATUS_CLEARANCE_PENDING")
                self.assertIn(recorded_layer, brief.recovered_layers)
                self.assertEqual(
                    brief.unavailable_layers,
                    ("approved checkpoint status clearance",),
                )
                self.assertFalse(
                    set(brief.recovered_layers).intersection(brief.unavailable_layers)
                )
                self.assertFalse(brief.safe_to_resume)

    def test_verified_mixed_runtime_gap_retains_unresolved_layer(self):
        state = self.incomplete_state(
            unavailable_layers=(
                "trusted authority verifier",
                "hosted startup integration",
            ),
        )
        with self.assertRaises(ContinuityRecoveryError) as caught:
            bootstrap_helpyou_session(
                state.user_scope_id,
                MemoryStore((state_to_private_payload(state),)),
                TestVerifier(),
                trusted_clock=FIXED_CLOCK,
            )
        brief = caught.exception.recovery_brief
        self.assertIn("trusted authority verifier", brief.recovered_layers)
        self.assertEqual(brief.reason_code, "RUNTIME_INTEGRATION_PENDING")
        self.assertEqual(brief.unavailable_layers, ("hosted startup integration",))
        self.assertEqual(brief.next_action, state.next_prompt)

    def test_malformed_accessible_chain_identifies_chain_layer(self):
        payload = state_to_private_payload(self.state())
        payload["unsupported_field"] = "value"
        with self.assertRaises(ContinuityRecoveryError) as caught:
            bootstrap_helpyou_session(
                self.state().user_scope_id,
                MemoryStore((payload,)),
                TestVerifier(),
                trusted_clock=FIXED_CLOCK,
            )
        brief = caught.exception.recovery_brief
        self.assertEqual(brief.reason_code, "CHECKPOINT_CHAIN_UNVERIFIED")
        self.assertIn("private checkpoint store", brief.recovered_layers)
        self.assertEqual(
            brief.unavailable_layers,
            ("verified private checkpoint chain",),
        )

    def test_unsupported_protocol_bootstrap_is_structured_and_gated(self):
        payload = state_to_private_payload(self.state())
        payload["protocol_version"] = "999.999"
        with self.assertRaises(ContinuityRecoveryError) as caught:
            bootstrap_helpyou_session(
                self.state().user_scope_id,
                MemoryStore((payload,)),
                TestVerifier(),
                trusted_clock=FIXED_CLOCK,
            )
        self.assertEqual(
            caught.exception.recovery_brief.reason_code,
            "CHECKPOINT_CHAIN_UNVERIFIED",
        )
        self.assertFalse(caught.exception.recovery_brief.safe_to_resume)

    def test_partial_authority_failures_identify_exact_layer(self):
        state = self.state()
        cases = (
            (
                {
                    "reason_code": "HUMAN_RECORD_UNAVAILABLE",
                    "recovered_layers": ("GitHub protocol authority",),
                    "unavailable_layers": ("human-readable checkpoint authority",),
                },
                "human-readable checkpoint authority",
                "GitHub protocol authority",
            ),
            (
                {
                    "reason_code": "GITHUB_AUTHORITY_UNAVAILABLE",
                    "recovered_layers": ("human-readable checkpoint authority",),
                    "unavailable_layers": ("GitHub protocol authority",),
                },
                "GitHub protocol authority",
                "human-readable checkpoint authority",
            ),
        )
        for failure, unavailable, recovered in cases:
            with self.subTest(reason=failure["reason_code"]):
                with self.assertRaises(ContinuityRecoveryError) as caught:
                    bootstrap_helpyou_session(
                        state.user_scope_id,
                        MemoryStore((state_to_private_payload(state),)),
                        TestVerifier(authority_layer_failure=failure),
                        trusted_clock=FIXED_CLOCK,
                    )
                brief = caught.exception.recovery_brief
                self.assertEqual(brief.unavailable_layers, (unavailable,))
                self.assertIn(recovered, brief.recovered_layers)
                for stage_layer in (
                    "private checkpoint store",
                    "verified private checkpoint chain",
                    "trusted monotonic head",
                    "trusted clock",
                    "trusted authority verifier",
                ):
                    self.assertIn(stage_layer, brief.recovered_layers)
                self.assertFalse(brief.safe_to_resume)

    def test_wrong_stage_typed_failure_is_normalized_without_layer_conflict(self):
        state = self.state()
        wrong_head_failure = {
            "reason_code": "CHECKPOINT_NOT_FOUND",
            "recovered_layers": (),
            "unavailable_layers": ("private checkpoint candidate",),
        }
        with self.assertRaises(ContinuityRecoveryError) as caught:
            bootstrap_helpyou_session(
                state.user_scope_id,
                MemoryStore((state_to_private_payload(state),)),
                TestVerifier(head_layer_failure=wrong_head_failure),
                trusted_clock=FIXED_CLOCK,
            )
        brief = caught.exception.recovery_brief
        self.assertEqual(brief.reason_code, "HEAD_ADAPTER_FAILURE")
        self.assertEqual(brief.unavailable_layers, ("trusted monotonic head",))
        self.assertNotIn("trusted clock", brief.recovered_layers)
        self.assertFalse(
            set(brief.recovered_layers).intersection(brief.unavailable_layers)
        )

        wrong_authority_failure = {
            "reason_code": "CHECKPOINT_NOT_FOUND",
            "recovered_layers": (),
            "unavailable_layers": ("private checkpoint candidate",),
        }
        with self.assertRaises(ContinuityRecoveryError) as caught:
            bootstrap_helpyou_session(
                state.user_scope_id,
                MemoryStore((state_to_private_payload(state),)),
                TestVerifier(authority_layer_failure=wrong_authority_failure),
                trusted_clock=FIXED_CLOCK,
            )
        brief = caught.exception.recovery_brief
        self.assertEqual(brief.reason_code, "AUTHORITY_ADAPTER_FAILURE")
        self.assertEqual(brief.unavailable_layers, ("trusted authority verifier",))

    def test_invalid_verifier_receipt_types_fail_at_adapter_stage_before_clock(self):
        class CountingClock:
            def __init__(self):
                self.calls = 0

            def now_utc(self):
                self.calls += 1
                return NOW_UTC

        class InvalidHeadVerifier(TestVerifier):
            def verify_current_head(self, *args):
                return object()

        class InvalidAuthorityVerifier(TestVerifier):
            def verify(self, *args):
                return object()

        state = self.state()
        clock = CountingClock()
        with self.assertRaises(ContinuityRecoveryError) as caught:
            bootstrap_helpyou_session(
                state.user_scope_id,
                MemoryStore((state_to_private_payload(state),)),
                InvalidHeadVerifier(),
                trusted_clock=clock,
            )
        self.assertEqual(clock.calls, 0)
        self.assertEqual(
            caught.exception.recovery_brief.reason_code,
            "HEAD_ADAPTER_FAILURE",
        )

        clock = CountingClock()
        with self.assertRaises(ContinuityRecoveryError) as caught:
            bootstrap_helpyou_session(
                state.user_scope_id,
                MemoryStore((state_to_private_payload(state),)),
                InvalidAuthorityVerifier(),
                trusted_clock=clock,
            )
        self.assertEqual(clock.calls, 1)
        brief = caught.exception.recovery_brief
        self.assertEqual(brief.reason_code, "AUTHORITY_ADAPTER_FAILURE")
        self.assertEqual(brief.unavailable_layers, ("trusted authority verifier",))
        self.assertNotIn("trusted authority verifier", brief.recovered_layers)

    def test_clock_failure_is_identified_separately(self):
        class FailedClock:
            def now_utc(self):
                raise RuntimeError("backend diagnostic")

        state = self.state()
        with self.assertRaises(ContinuityRecoveryError) as caught:
            bootstrap_helpyou_session(
                state.user_scope_id,
                MemoryStore((state_to_private_payload(state),)),
                TestVerifier(),
                trusted_clock=FailedClock(),
            )
        brief = caught.exception.recovery_brief
        self.assertEqual(brief.reason_code, "CLOCK_UNAVAILABLE")
        self.assertEqual(brief.unavailable_layers, ("trusted clock",))
        self.assertIn("verified private checkpoint chain", brief.recovered_layers)
        self.assertNotIn("trusted clock", brief.recovered_layers)
        self.assertIn("trusted UTC clock", brief.next_action)
        self.assertFalse(brief.safe_to_resume)

    def test_authority_phase_clock_failure_names_clock_recovery_action(self):
        class FailSecondClock:
            def __init__(self):
                self.calls = 0

            def now_utc(self):
                self.calls += 1
                if self.calls == 2:
                    raise RuntimeError("private clock diagnostic")
                return NOW_UTC

        state = self.state()
        with self.assertRaises(ContinuityRecoveryError) as caught:
            bootstrap_helpyou_session(
                state.user_scope_id,
                MemoryStore((state_to_private_payload(state),)),
                TestVerifier(),
                trusted_clock=FailSecondClock(),
            )
        brief = caught.exception.recovery_brief
        self.assertEqual(brief.reason_code, "CLOCK_UNAVAILABLE")
        self.assertEqual(brief.unavailable_layers, ("trusted clock",))
        self.assertIn("trusted monotonic head", brief.recovered_layers)
        self.assertIn("trusted authority verifier", brief.recovered_layers)
        self.assertNotIn("trusted clock", brief.recovered_layers)
        self.assertIn("trusted UTC clock", brief.next_action)

    def test_bootstrap_does_not_expose_adapter_exception_text(self):
        secret = "secret token=do-not-expose"

        class SecretStore(MemoryStore):
            def list_checkpoints(self, user_scope_id):
                raise RuntimeError(secret)

        class SecretVerifier(TestVerifier):
            def verify(self, authority, governed_fingerprint, checkpoint_envelope_fingerprint):
                raise RuntimeError(secret)

        class SecretClock:
            def now_utc(self):
                raise RuntimeError(secret)

        state = self.state()
        cases = (
            (SecretStore(), TestVerifier(), FIXED_CLOCK),
            (MemoryStore((state_to_private_payload(state),)), SecretVerifier(), FIXED_CLOCK),
            (MemoryStore((state_to_private_payload(state),)), TestVerifier(), SecretClock()),
        )
        for store, verifier, clock in cases:
            with self.subTest(store=type(store).__name__, verifier=type(verifier).__name__):
                with self.assertRaises(ContinuityRecoveryError) as caught:
                    bootstrap_helpyou_session(
                        state.user_scope_id, store, verifier, trusted_clock=clock
                    )
                rendered = "".join(
                    traceback.format_exception(caught.exception)
                )
                self.assertNotIn(secret, str(caught.exception))
                self.assertNotIn(secret, rendered)
                self.assertIsNone(caught.exception.__context__)

    def test_typed_failure_channel_rejects_secret_or_ambiguous_layers(self):
        secret = "backend secret token=typed"
        with self.assertRaises(ContinuityPolicyError) as caught:
            VerificationLayerFailure(
                reason_code="HUMAN_RECORD_UNAVAILABLE",
                recovered_layers=("GitHub protocol authority",),
                unavailable_layers=(secret,),
            )
        self.assertNotIn(secret, str(caught.exception))
        with self.assertRaisesRegex(ContinuityPolicyError, "both recovered and unavailable"):
            VerificationLayerFailure(
                reason_code="AUTHORITY_UNVERIFIED",
                recovered_layers=("GitHub protocol authority",),
                unavailable_layers=("GitHub protocol authority",),
            )
        with self.assertRaisesRegex(ContinuityPolicyError, "duplicate"):
            VerificationLayerFailure(
                reason_code="AUTHORITY_UNVERIFIED",
                recovered_layers=(),
                unavailable_layers=("trusted clock", "trusted clock"),
            )

    def test_typed_failure_channel_rejects_uncontrolled_reason_code(self):
        secret = "SECRET_TOKEN_AKIA1234567890"
        with self.assertRaises(ContinuityPolicyError) as caught:
            VerificationLayerFailure(
                reason_code=secret,
                recovered_layers=("GitHub protocol authority",),
                unavailable_layers=("human-readable checkpoint authority",),
            )
        self.assertNotIn(secret, str(caught.exception))

    def test_typed_failure_rejects_recovered_layers_outside_adapter_stage(self):
        with self.assertRaisesRegex(ContinuityPolicyError, "outside"):
            VerificationLayerFailure(
                reason_code="HEAD_UNVERIFIED",
                recovered_layers=("approved checkpoint status clearance",),
                unavailable_layers=("trusted monotonic head",),
            )
        with self.assertRaisesRegex(ContinuityPolicyError, "outside"):
            VerificationLayerFailure(
                reason_code="HUMAN_RECORD_UNAVAILABLE",
                recovered_layers=("trusted clock",),
                unavailable_layers=("human-readable checkpoint authority",),
            )

    def test_reason_code_must_match_named_unavailable_layer(self):
        with self.assertRaisesRegex(ContinuityPolicyError, "does not match"):
            VerificationLayerFailure(
                reason_code="HUMAN_RECORD_UNAVAILABLE",
                recovered_layers=("human-readable checkpoint authority",),
                unavailable_layers=("GitHub protocol authority",),
            )
        with self.assertRaisesRegex(ContinuityPolicyError, "does not match"):
            replace(
                self.incomplete_state(),
                status_reason_code="HUMAN_RECORD_UNAVAILABLE",
            ).validate()

    def test_receipt_binds_complete_governed_checkpoint_state(self):
        original = self.state()
        tampered = replace(original, next_prompt="Tampered but internally rehashed prompt")
        store = MemoryStore((state_to_private_payload(tampered),))
        verifier = TestVerifier(
            expected_governed_fingerprint=governed_state_fingerprint(original)
        )
        with self.assertRaisesRegex(ContinuityRecoveryError, "INCOMPLETE"):
            bootstrap_helpyou_session(
                original.user_scope_id, store, verifier, trusted_clock=FIXED_CLOCK
            )

    def test_digest_split_avoids_human_record_hash_circularity(self):
        original = self.state()
        changed_record_hash = replace(
            original,
            authority=replace(
                original.authority,
                human_record_fingerprint="sha256:" + "9" * 64,
            ),
        )
        self.assertEqual(
            governed_state_fingerprint(original),
            governed_state_fingerprint(changed_record_hash),
        )
        self.assertNotEqual(
            checkpoint_fingerprint(original),
            checkpoint_fingerprint(changed_record_hash),
        )

    def test_receipt_binds_repository_and_path(self):
        state = self.state()
        store = MemoryStore((state_to_private_payload(state),))
        for verifier in (
            TestVerifier(repository="OtherOwner/other-repository"),
            TestVerifier(path="docs/helpyou/OTHER_PROTOCOL.md"),
        ):
            with self.subTest(verifier=verifier):
                with self.assertRaisesRegex(ContinuityRecoveryError, "INCOMPLETE"):
                    bootstrap_helpyou_session(
                        state.user_scope_id, store, verifier, trusted_clock=FIXED_CLOCK
                    )

    def test_expired_authority_receipt_fails_closed(self):
        state = self.state()
        store = MemoryStore((state_to_private_payload(state),))
        verifier = TestVerifier(expires_at_utc="2026-08-27T02:59:59Z")
        with self.assertRaisesRegex(ContinuityRecoveryError, "INCOMPLETE"):
            bootstrap_helpyou_session(
                state.user_scope_id, store, verifier, trusted_clock=FIXED_CLOCK
            )

    def test_oversized_receipt_validity_fails_closed(self):
        state = self.state()
        store = MemoryStore((state_to_private_payload(state),))
        verifier = TestVerifier(
            verified_at_utc="2026-08-27T02:30:00Z",
            expires_at_utc="2026-08-27T03:30:00Z",
        )
        with self.assertRaisesRegex(ContinuityRecoveryError, "INCOMPLETE"):
            bootstrap_helpyou_session(
                state.user_scope_id, store, verifier, trusted_clock=FIXED_CLOCK
            )

    def test_bootstrap_requires_private_store_capability(self):
        state = self.state()
        store = PublicStore((state_to_private_payload(state),))
        with self.assertRaisesRegex(ContinuityRecoveryError, "INCOMPLETE"):
            bootstrap_helpyou_session(
                state.user_scope_id, store, TestVerifier(), trusted_clock=FIXED_CLOCK
            )

    def test_competing_successors_fail_closed(self):
        first, second = self.state(), self.successor()
        conflict = replace(second, checkpoint_id="HCP-099")
        store = MemoryStore((
            state_to_private_payload(first), state_to_private_payload(second),
            state_to_private_payload(conflict),
        ))
        with self.assertRaisesRegex(ContinuityRecoveryError, "INCOMPLETE"):
            bootstrap_helpyou_session(
                first.user_scope_id, store, TestVerifier(), trusted_clock=FIXED_CLOCK
            )

    def test_valid_but_stale_chain_prefix_fails_head_verification(self):
        first, third = self.state(), self.third()
        verifier = TestVerifier(
            head_override=(
                third.sequence,
                third.checkpoint_id,
                checkpoint_fingerprint(third),
            )
        )
        with self.assertRaises(ContinuityRecoveryError) as caught:
            bootstrap_helpyou_session(
                first.user_scope_id,
                MemoryStore((state_to_private_payload(first),)),
                verifier,
                trusted_clock=FIXED_CLOCK,
            )
        brief = caught.exception.recovery_brief
        self.assertEqual(brief.reason_code, "HEAD_UNVERIFIED")
        self.assertEqual(brief.unavailable_layers, ("trusted monotonic head",))
        for recovered in (
            "private checkpoint store",
            "private checkpoint candidate",
            "verified private checkpoint chain",
            "trusted clock",
        ):
            self.assertIn(recovered, brief.recovered_layers)
        self.assertFalse(brief.safe_to_resume)

    def test_broken_predecessor_chain_fails(self):
        first, second = self.state(), self.successor()
        bad = replace(second, previous_checkpoint_id="HCP-XXX")
        store = MemoryStore((state_to_private_payload(first), state_to_private_payload(bad)))
        with self.assertRaisesRegex(ContinuityRecoveryError, "INCOMPLETE"):
            bootstrap_helpyou_session(
                first.user_scope_id, store, TestVerifier(), trusted_clock=FIXED_CLOCK
            )

    def test_broken_governed_state_hash_chain_fails(self):
        first, second = self.state(), self.successor()
        bad = replace(
            second,
            previous_checkpoint_fingerprint="sha256:" + "f" * 64,
        )
        store = MemoryStore((state_to_private_payload(first), state_to_private_payload(bad)))
        with self.assertRaisesRegex(ContinuityRecoveryError, "INCOMPLETE"):
            bootstrap_helpyou_session(
                first.user_scope_id, store, TestVerifier(), trusted_clock=FIXED_CLOCK
            )

    def test_historical_human_record_substitution_breaks_hash_chain(self):
        first, second = self.state(), self.successor()
        substituted = replace(
            first,
            authority=replace(
                first.authority,
                human_record_fingerprint="sha256:" + "9" * 64,
            ),
        )
        store = MemoryStore(
            (state_to_private_payload(substituted), state_to_private_payload(second))
        )
        with self.assertRaisesRegex(ContinuityRecoveryError, "INCOMPLETE"):
            bootstrap_helpyou_session(
                first.user_scope_id, store, TestVerifier(), trusted_clock=FIXED_CLOCK
            )

    def test_checkpoint_id_cannot_be_reused_later_in_chain(self):
        first, second = self.state(), self.successor()
        third = replace(
            self.third(),
            checkpoint_id=first.checkpoint_id,
        )
        store = MemoryStore(tuple(state_to_private_payload(item) for item in (first, second, third)))
        with self.assertRaisesRegex(ContinuityRecoveryError, "INCOMPLETE"):
            bootstrap_helpyou_session(
                first.user_scope_id, store, TestVerifier(), trusted_clock=FIXED_CLOCK
            )

    def test_persist_round_trip_verifies(self):
        store = MemoryStore()
        persist_checkpoint(store, self.state(), TestVerifier(), trusted_clock=FIXED_CLOCK)
        self.assertEqual(len(store.payloads), 1)

    def test_persist_sanitizes_raw_store_exceptions(self):
        secret = "secret token=persist-do-not-expose"

        class FailedReadStore(MemoryStore):
            def list_checkpoints(self, user_scope_id):
                raise RuntimeError(secret)

        class FailedCasStore(MemoryStore):
            def compare_and_swap_checkpoint(
                self, expected_checkpoint_id, expected_checkpoint_fingerprint, payload
            ):
                raise RuntimeError(secret)

        class FailedPostWriteReadStore(MemoryStore):
            def __init__(self):
                super().__init__()
                self.reads = 0

            def list_checkpoints(self, user_scope_id):
                self.reads += 1
                if self.reads > 1:
                    raise RuntimeError(secret)
                return super().list_checkpoints(user_scope_id)

        for store in (FailedReadStore(), FailedCasStore(), FailedPostWriteReadStore()):
            with self.subTest(store=type(store).__name__):
                with self.assertRaises(ContinuityPolicyError) as caught:
                    persist_checkpoint(
                        store,
                        self.state(),
                        TestVerifier(),
                        trusted_clock=FIXED_CLOCK,
                    )
                rendered = "".join(traceback.format_exception(caught.exception))
                self.assertNotIn(secret, str(caught.exception))
                self.assertNotIn(secret, rendered)
                self.assertIsNone(caught.exception.__context__)

    def test_persist_reconciles_commit_then_transport_error(self):
        secret = "secret token=commit-timeout"

        class CommitThenRaiseStore(MemoryStore):
            def compare_and_swap_checkpoint(
                self, expected_checkpoint_id, expected_checkpoint_fingerprint, payload
            ):
                super().compare_and_swap_checkpoint(
                    expected_checkpoint_id,
                    expected_checkpoint_fingerprint,
                    payload,
                )
                raise RuntimeError(secret)

        store = CommitThenRaiseStore()
        persist_checkpoint(
            store,
            self.state(),
            TestVerifier(),
            trusted_clock=FIXED_CLOCK,
        )
        self.assertEqual(len(store.payloads), 1)

    def test_persist_sanitizes_store_originated_decode_and_capability_failures(self):
        secret = "secret token=stored-private-key"

        class SecretMapping(dict):
            def __iter__(self):
                raise RuntimeError(secret)

        class SecretCapabilityStore(MemoryStore):
            @property
            def privacy_class(self):
                raise ContinuityPolicyError(secret)

        payload_with_secret_key = state_to_private_payload(self.state())
        payload_with_secret_key[secret] = "value"
        stores = (
            MemoryStore((SecretMapping(state_to_private_payload(self.state())),)),
            MemoryStore((payload_with_secret_key,)),
            SecretCapabilityStore(),
        )
        for store in stores:
            with self.subTest(store=type(store).__name__):
                with self.assertRaises(ContinuityPolicyError) as caught:
                    persist_checkpoint(
                        store,
                        self.state(),
                        TestVerifier(),
                        trusted_clock=FIXED_CLOCK,
                    )
                rendered = "".join(traceback.format_exception(caught.exception))
                self.assertNotIn(secret, str(caught.exception))
                self.assertNotIn(secret, rendered)
                self.assertIsNone(caught.exception.__context__)

    def test_idempotent_retry_verifies_authority_of_current_tail(self):
        first, candidate, follower = self.state(), self.successor(), self.third()
        store = MemoryStore(tuple(
            state_to_private_payload(item) for item in (first, candidate, follower)
        ))
        with self.assertRaises(ContinuityPolicyError):
            persist_checkpoint(
                store,
                candidate,
                BadLatestAuthorityVerifier(follower.authority.human_record_id),
                trusted_clock=FIXED_CLOCK,
            )

    def test_snapshot_verification_retries_when_head_advances_after_read(self):
        registry = HeadRegistry(state_to_private_payload(self.state()))
        first, candidate, follower = self.state(), self.successor(), self.third()
        store = FollowBetweenListAndHeadStore(
            registry,
            (state_to_private_payload(first),),
            state_to_private_payload(follower),
        )
        persist_checkpoint(
            store,
            candidate,
            RegistryVerifier(registry),
            trusted_clock=FIXED_CLOCK,
        )
        self.assertEqual(
            [payload["checkpoint_id"] for payload in store.payloads],
            [first.checkpoint_id, candidate.checkpoint_id, follower.checkpoint_id],
        )

    def test_persist_atomically_advances_independent_head_and_is_recoverable(self):
        registry = HeadRegistry()
        store = RegistryStore(registry)
        verifier = RegistryVerifier(registry)
        first, second = self.state(), self.successor()
        persist_checkpoint(store, first, verifier, trusted_clock=FIXED_CLOCK)
        persist_checkpoint(store, second, verifier, trusted_clock=FIXED_CLOCK)
        recovered, brief = bootstrap_helpyou_session(
            first.user_scope_id, store, verifier, trusted_clock=FIXED_CLOCK
        )
        self.assertEqual(recovered, second)
        self.assertEqual(brief.checkpoint_id, second.checkpoint_id)

    def test_persist_fails_if_store_does_not_advance_independent_head(self):
        registry = HeadRegistry()
        store = RegistryStore(registry, advance_head=False)
        with self.assertRaisesRegex(ContinuityPolicyError, "verified chain state"):
            persist_checkpoint(
                store, self.state(), RegistryVerifier(registry),
                trusted_clock=FIXED_CLOCK,
            )
        self.assertEqual(len(store.payloads), 1)

    def test_persist_retry_of_identical_checkpoint_is_idempotent(self):
        store = MemoryStore()
        state = self.state()
        persist_checkpoint(store, state, TestVerifier(), trusted_clock=FIXED_CLOCK)
        persist_checkpoint(store, state, TestVerifier(), trusted_clock=FIXED_CLOCK)
        self.assertEqual(len(store.payloads), 1)

    def test_same_candidate_race_is_treated_as_success(self):
        first, candidate = self.state(), self.successor()
        store = SameCandidateRaceStore((state_to_private_payload(first),))
        persist_checkpoint(store, candidate, TestVerifier(), trusted_clock=FIXED_CLOCK)
        self.assertEqual(len(store.payloads), 2)

    def test_fast_follower_does_not_make_committed_write_look_failed(self):
        first, candidate, follower = self.state(), self.successor(), self.third()
        store = FastFollowStore(
            (state_to_private_payload(first),), state_to_private_payload(follower)
        )
        persist_checkpoint(store, candidate, TestVerifier(), trusted_clock=FIXED_CLOCK)
        self.assertEqual(len(store.payloads), 3)

    def test_semantic_mode_bypass_is_rejected_before_cas(self):
        first = self.state()
        invalid = replace(
            self.successor(),
            mode=InteractionMode.ASSESSMENT,
            mode_selected_explicitly=True,
        )
        store = MemoryStore((state_to_private_payload(first),))
        with self.assertRaisesRegex(ContinuityPolicyError, "Only an approved mode-change"):
            persist_checkpoint(
                store, invalid, TestVerifier(), trusted_clock=FIXED_CLOCK
            )
        self.assertEqual(store.cas_calls, 0)

    def test_semantic_status_bypass_is_rejected_before_cas(self):
        first = self.state()
        invalid = replace(
            self.successor(),
            status=CheckpointStatus.INCOMPLETE,
            status_reason_code="RUNTIME_INTEGRATION_PENDING",
            unavailable_layers=("hosted startup integration",),
            safe_to_resume=False,
        )
        store = MemoryStore((state_to_private_payload(first),))
        with self.assertRaisesRegex(ContinuityPolicyError, "approved status-change"):
            persist_checkpoint(
                store, invalid, TestVerifier(), trusted_clock=FIXED_CLOCK
            )
        self.assertEqual(store.cas_calls, 0)

    def test_material_change_cannot_migrate_policy_authority(self):
        first = self.state()
        invalid = replace(
            self.successor(),
            authority=replace(
                self.successor().authority,
                github_commit_sha="f" * 40,
            ),
        )
        store = MemoryStore((state_to_private_payload(first),))
        with self.assertRaisesRegex(ContinuityPolicyError, "approved source revision"):
            persist_checkpoint(
                store, invalid, TestVerifier(), trusted_clock=FIXED_CLOCK
            )
        self.assertEqual(store.cas_calls, 0)

    def test_failed_persistence_is_not_reported_as_success(self):
        with self.assertRaisesRegex(ContinuityPolicyError, "compare-and-swap"):
            persist_checkpoint(
                MemoryStore(drop_writes=True), self.state(), TestVerifier(),
                trusted_clock=FIXED_CLOCK,
            )

    def test_compare_and_swap_rejects_competing_successor(self):
        first, candidate = self.state(), self.successor()
        competing = replace(
            candidate,
            checkpoint_id="HCP-099",
            sequence=2,
            previous_checkpoint_id=first.checkpoint_id,
            updated_at_utc="2026-08-27T01:30:00Z",
            authority=self.authority("e"),
            applied_human_record_ids=("HCP-C001", "HCP-E001"),
        )
        store = RaceStore(
            (state_to_private_payload(first),), state_to_private_payload(competing)
        )
        with self.assertRaisesRegex(ContinuityPolicyError, "compare-and-swap"):
            persist_checkpoint(
                store, candidate, TestVerifier(), trusted_clock=FIXED_CLOCK
            )

    def test_append_only_audit_histories_cannot_be_erased(self):
        first = replace(
            self.state(),
            source_manifest=("Source 1",),
            controlled_facts=("Fact 1",),
            superseded_positions=("Superseded position 1",),
        )
        candidate = record_approved_bundle(
            first,
            event=ContinuityEvent.APPROVED_MATERIAL_CHANGE,
            approved_changes=("Second approved change",),
            transition_id="EVT-AUDIT-002",
            approval_evidence_ref="fixture:audit-approval",
            checkpoint_id="HCP-002",
            updated_at_utc="2026-08-27T01:00:00Z",
            next_prompt="Continue.",
            authority=self.authority("d"),
        )
        invalid = replace(
            candidate,
            source_manifest=(),
            controlled_facts=(),
            superseded_positions=(),
        )
        store = MemoryStore((state_to_private_payload(first),))
        with self.assertRaisesRegex(ContinuityPolicyError, "history is not append-only"):
            persist_checkpoint(
                store, invalid, TestVerifier(), trusted_clock=FIXED_CLOCK
            )
        self.assertEqual(store.cas_calls, 0)

    def test_active_memory_deactivation_requires_approved_memory_change(self):
        first = replace(
            self.state(),
            private_pilot_memory=(PilotMemoryPair(
                raw_pilot_wording="Remember my exact wording.",
                ai_interpretation="The pilot asked to retain the exact wording.",
            ),),
        )
        candidate = record_approved_bundle(
            first,
            event=ContinuityEvent.APPROVED_MATERIAL_CHANGE,
            approved_changes=("Second approved change",),
            transition_id="EVT-MATERIAL-002",
            approval_evidence_ref="fixture:material-approval",
            checkpoint_id="HCP-002",
            updated_at_utc="2026-08-27T01:00:00Z",
            next_prompt="Continue.",
            authority=self.authority("d"),
        )
        invalid = replace(candidate, private_pilot_memory=())
        store = MemoryStore((state_to_private_payload(first),))
        with self.assertRaisesRegex(ContinuityPolicyError, "approved memory change"):
            persist_checkpoint(
                store, invalid, TestVerifier(), trusted_clock=FIXED_CLOCK
            )
        self.assertEqual(store.cas_calls, 0)

    def test_approved_memory_change_can_deactivate_active_pilot_memory(self):
        first = replace(
            self.state(),
            private_pilot_memory=(PilotMemoryPair(
                raw_pilot_wording="Forget this exact wording.",
                ai_interpretation="The pilot requested removal of this memory.",
            ),),
        )
        candidate = record_approved_bundle(
            first,
            event=ContinuityEvent.APPROVED_MEMORY_CHANGE,
            approved_changes=("User approved deactivation from the active memory view.",),
            transition_id="EVT-MEMORY-002",
            approval_evidence_ref="fixture:memory-removal-approval",
            checkpoint_id="HCP-002",
            updated_at_utc="2026-08-27T01:00:00Z",
            next_prompt="Continue.",
            authority=self.authority("d"),
        )
        candidate = replace(candidate, private_pilot_memory=())
        store = MemoryStore((state_to_private_payload(first),))
        persist_checkpoint(
            store, candidate, TestVerifier(), trusted_clock=FIXED_CLOCK
        )
        self.assertEqual(load_checkpoint(store.payloads[-1]), candidate)

    def test_invalid_sequence_is_rejected_before_store_mutation(self):
        first = self.state()
        invalid = self.third()
        store = MemoryStore((state_to_private_payload(first),))
        with self.assertRaisesRegex(ContinuityPolicyError, "not the next sequence"):
            persist_checkpoint(
                store, invalid, TestVerifier(), trusted_clock=FIXED_CLOCK
            )
        self.assertEqual(len(store.payloads), 1)

    def test_reused_historical_id_is_rejected_before_store_mutation(self):
        first, second = self.state(), self.successor()
        invalid = replace(
            self.third(),
            checkpoint_id=first.checkpoint_id,
        )
        store = MemoryStore(
            (state_to_private_payload(first), state_to_private_payload(second))
        )
        with self.assertRaisesRegex(ContinuityPolicyError, "already exists with different"):
            persist_checkpoint(
                store, invalid, TestVerifier(), trusted_clock=FIXED_CLOCK
            )
        self.assertEqual(len(store.payloads), 2)

    def test_development_string_uses_development_sequence(self):
        steps = facilitation_sequence("development")
        self.assertIn("Explain the controlling policy", steps[1])
        self.assertIn("Present the materially different viable options", steps[2])

    def test_assessment_does_not_coach_before_commitment(self):
        self.assertTrue(any("Do not coach" in step for step in facilitation_sequence("assessment")))

    def test_public_projection_excludes_private_identifiers_and_text(self):
        state = replace(
            self.state(), status=CheckpointStatus.ACTIVE,
            controlled_facts=("Sensitive fact",),
            private_pilot_memory=(PilotMemoryPair(
                raw_pilot_wording="Private exact wording",
                ai_interpretation="Private interpreted meaning",
            ),),
        )
        projection = str(public_checkpoint_projection(state))
        for prohibited in (
            state.checkpoint_id, state.user_scope_id, state.active_case_ref,
            state.authority.github_repository, "Sensitive fact", "Private exact wording",
        ):
            self.assertNotIn(prohibited, projection)


if __name__ == "__main__":
    unittest.main()
