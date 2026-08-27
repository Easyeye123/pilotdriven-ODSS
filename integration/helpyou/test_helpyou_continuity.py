from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import unittest

from helpyou_continuity import (
    APPROVED_DEFAULTS_V1,
    AuthorityPointers,
    AuthorityVerificationReceipt,
    CheckpointStatus,
    ContinuityEvent,
    ContinuityPolicyError,
    ContinuityRecoveryError,
    ContinuityState,
    InteractionMode,
    PilotMemoryPair,
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


class TestVerifier:
    def __init__(
        self,
        *,
        mismatch=False,
        repository=None,
        path=None,
        expected_governed_fingerprint=None,
        expected_checkpoint_fingerprint=None,
        verified_at_utc="2026-08-27T02:55:00Z",
        expires_at_utc="2026-08-27T03:10:00Z",
    ):
        self.mismatch = mismatch
        self.repository = repository
        self.path = path
        self.expected_governed_fingerprint = expected_governed_fingerprint
        self.expected_checkpoint_fingerprint = expected_checkpoint_fingerprint
        self.verified_at_utc = verified_at_utc
        self.expires_at_utc = expires_at_utc

    def verify(self, authority, governed_fingerprint, checkpoint_envelope_fingerprint):
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
        self.assertEqual(calls, ["verifier", "clock"])

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
        with self.assertRaisesRegex(ContinuityRecoveryError, "does not match binding") as caught:
            bootstrap_helpyou_session(
                state.user_scope_id, store, TestVerifier(mismatch=True),
                trusted_clock=FIXED_CLOCK,
            )
        brief = caught.exception.recovery_brief
        self.assertEqual(brief.status, "INCOMPLETE")
        self.assertEqual(brief.recovered_layers, ("private checkpoint candidate",))
        self.assertFalse(brief.safe_to_resume)

    def test_bootstrap_missing_checkpoint_returns_structured_incomplete_brief(self):
        with self.assertRaisesRegex(ContinuityRecoveryError, "INCOMPLETE") as caught:
            bootstrap_helpyou_session(
                "user_12345678", MemoryStore(), TestVerifier(),
                trusted_clock=FIXED_CLOCK,
            )
        brief = caught.exception.recovery_brief
        self.assertEqual(brief.status, "INCOMPLETE")
        self.assertEqual(brief.recovered_layers, ())
        self.assertIn("verified private checkpoint", brief.unavailable_layers)
        self.assertFalse(brief.safe_to_resume)

    def test_receipt_binds_complete_governed_checkpoint_state(self):
        original = self.state()
        tampered = replace(original, next_prompt="Tampered but internally rehashed prompt")
        store = MemoryStore((state_to_private_payload(tampered),))
        verifier = TestVerifier(
            expected_governed_fingerprint=governed_state_fingerprint(original)
        )
        with self.assertRaisesRegex(ContinuityPolicyError, "does not match binding"):
            bootstrap_helpyou_session(
                original.user_scope_id, store, verifier, trusted_clock=FIXED_CLOCK
            )

    def test_receipt_binds_repository_and_path(self):
        state = self.state()
        store = MemoryStore((state_to_private_payload(state),))
        for verifier in (
            TestVerifier(repository="OtherOwner/other-repository"),
            TestVerifier(path="docs/helpyou/OTHER_PROTOCOL.md"),
        ):
            with self.subTest(verifier=verifier):
                with self.assertRaisesRegex(ContinuityPolicyError, "does not match binding"):
                    bootstrap_helpyou_session(
                        state.user_scope_id, store, verifier, trusted_clock=FIXED_CLOCK
                    )

    def test_expired_authority_receipt_fails_closed(self):
        state = self.state()
        store = MemoryStore((state_to_private_payload(state),))
        verifier = TestVerifier(expires_at_utc="2026-08-27T02:59:59Z")
        with self.assertRaisesRegex(ContinuityPolicyError, "not currently valid"):
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
        with self.assertRaisesRegex(ContinuityPolicyError, "exceeds 15 minutes"):
            bootstrap_helpyou_session(
                state.user_scope_id, store, verifier, trusted_clock=FIXED_CLOCK
            )

    def test_bootstrap_requires_private_store_capability(self):
        state = self.state()
        store = PublicStore((state_to_private_payload(state),))
        with self.assertRaisesRegex(ContinuityPolicyError, "PRIVATE store"):
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
        with self.assertRaisesRegex(ContinuityPolicyError, "Conflicting checkpoints"):
            bootstrap_helpyou_session(
                first.user_scope_id, store, TestVerifier(), trusted_clock=FIXED_CLOCK
            )

    def test_broken_predecessor_chain_fails(self):
        first, second = self.state(), self.successor()
        bad = replace(second, previous_checkpoint_id="HCP-XXX")
        store = MemoryStore((state_to_private_payload(first), state_to_private_payload(bad)))
        with self.assertRaisesRegex(ContinuityPolicyError, "predecessor chain"):
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
        with self.assertRaisesRegex(ContinuityPolicyError, "hash chain is broken"):
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
        with self.assertRaisesRegex(ContinuityPolicyError, "hash chain is broken"):
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
        with self.assertRaisesRegex(ContinuityPolicyError, "reused within the chain"):
            bootstrap_helpyou_session(
                first.user_scope_id, store, TestVerifier(), trusted_clock=FIXED_CLOCK
            )

    def test_persist_round_trip_verifies(self):
        store = MemoryStore()
        persist_checkpoint(store, self.state(), TestVerifier(), trusted_clock=FIXED_CLOCK)
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

    def test_pilot_memory_removal_requires_approved_memory_change(self):
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

    def test_approved_memory_change_can_remove_pilot_memory(self):
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
            approved_changes=("User approved removal of the retained memory.",),
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
