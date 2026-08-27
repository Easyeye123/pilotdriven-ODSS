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
    ContinuityState,
    InteractionMode,
    PilotMemoryPair,
    bootstrap_helpyou_session,
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

    def list_checkpoints(self, user_scope_id):
        return deepcopy(self.payloads)

    def compare_and_swap_checkpoint(self, expected_checkpoint_id, payload):
        if self.drop_writes:
            return False
        latest = max(self.payloads, key=lambda item: item["sequence"], default=None)
        current_id = latest["checkpoint_id"] if latest else None
        if current_id != expected_checkpoint_id:
            return False
        self.payloads.append(deepcopy(payload))
        return True


class PublicStore(MemoryStore):
    privacy_class = "PUBLIC"


class RaceStore(MemoryStore):
    def __init__(self, payloads, competing_payload):
        super().__init__(payloads)
        self.competing_payload = deepcopy(competing_payload)

    def compare_and_swap_checkpoint(self, expected_checkpoint_id, payload):
        self.payloads.append(deepcopy(self.competing_payload))
        return super().compare_and_swap_checkpoint(expected_checkpoint_id, payload)


class TestVerifier:
    def __init__(
        self,
        *,
        mismatch=False,
        repository=None,
        path=None,
        expected_governed_fingerprint=None,
        verified_at_utc="2026-08-27T02:55:00Z",
        expires_at_utc="2026-08-27T03:10:00Z",
    ):
        self.mismatch = mismatch
        self.repository = repository
        self.path = path
        self.expected_governed_fingerprint = expected_governed_fingerprint
        self.verified_at_utc = verified_at_utc
        self.expires_at_utc = expires_at_utc

    def verify(self, authority, governed_fingerprint):
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
            verified_at_utc=self.verified_at_utc,
            expires_at_utc=self.expires_at_utc,
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
            user_scope_id="user_12345678",
            updated_at_utc="2026-08-27T00:00:00Z",
            authority=self.authority("c"),
            active_case_ref="private-case-reference",
            next_prompt="Continue the controlled case review.",
        )

    def successor(self) -> ContinuityState:
        return record_approved_bundle(
            self.state(),
            event=ContinuityEvent.APPROVED_MATERIAL_CHANGE,
            approved_changes=APPROVED_DEFAULTS_V1,
            checkpoint_id="HCP-002",
            updated_at_utc="2026-08-27T01:00:00Z",
            next_prompt="Calibrate Development Mode prompting.",
            authority=self.authority("d"),
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
        self.assertFalse(checkpoint_required(ContinuityEvent.DRAFT_CHANGE))

    def test_four_item_bundle_creates_one_successor(self):
        result = self.successor()
        self.assertEqual(result.sequence, 2)
        self.assertEqual(result.previous_checkpoint_id, "HCP-001")
        self.assertEqual(result.approved_changes, EXPECTED_DEFAULTS)

    def test_bundle_replay_is_idempotent(self):
        result = self.successor()
        replay = record_approved_bundle(
            result,
            event=ContinuityEvent.APPROVED_MATERIAL_CHANGE,
            approved_changes=APPROVED_DEFAULTS_V1,
            checkpoint_id="HCP-003",
            updated_at_utc="2026-08-27T02:00:00Z",
            next_prompt="Different prompt",
            authority=self.authority("e"),
        )
        self.assertIs(replay, result)

    def test_successor_rejects_reused_id(self):
        with self.assertRaisesRegex(ContinuityPolicyError, "new checkpoint_id"):
            record_approved_bundle(
                self.state(), event=ContinuityEvent.APPROVED_MATERIAL_CHANGE,
                approved_changes=("Approved change",), checkpoint_id="HCP-001",
                updated_at_utc="2026-08-27T01:00:00Z", next_prompt="Continue.",
                authority=self.authority("d"),
            )

    def test_successor_rejects_stale_time(self):
        with self.assertRaisesRegex(ContinuityPolicyError, "timestamp"):
            record_approved_bundle(
                self.state(), event=ContinuityEvent.APPROVED_MATERIAL_CHANGE,
                approved_changes=("Approved change",), checkpoint_id="HCP-002",
                updated_at_utc="2026-08-26T23:00:00Z", next_prompt="Continue.",
                authority=self.authority("d"),
            )

    def test_successor_requires_new_human_record(self):
        with self.assertRaisesRegex(ContinuityPolicyError, "newly verified human record"):
            record_approved_bundle(
                self.state(), event=ContinuityEvent.APPROVED_MATERIAL_CHANGE,
                approved_changes=("Approved change",), checkpoint_id="HCP-002",
                updated_at_utc="2026-08-27T01:00:00Z", next_prompt="Continue.",
                authority=self.authority("c"),
            )

    def test_mode_change_changes_the_mode(self):
        result = record_mode_change(
            self.state(), new_mode="assessment", approved_change="Assessment selected.",
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
                updated_at_utc="2026-08-27T01:00:00Z", next_prompt="Begin.",
                authority=self.authority("d"),
            )

    def test_serialized_mode_event_cannot_bypass_mode_gate(self):
        with self.assertRaisesRegex(ContinuityPolicyError, "record_mode_change"):
            record_approved_bundle(
                self.state(), event="approved_mode_change",
                approved_changes=("Assessment selected.",), checkpoint_id="HCP-002",
                updated_at_utc="2026-08-27T01:00:00Z", next_prompt="Begin.",
                authority=self.authority("d"),
            )

    def test_mutation_rejects_string_change_collection(self):
        with self.assertRaisesRegex(ContinuityPolicyError, "array of strings"):
            record_approved_bundle(
                self.state(), event=ContinuityEvent.APPROVED_MATERIAL_CHANGE,
                approved_changes="ABC", checkpoint_id="HCP-002",
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

    def test_string_cannot_become_tuple_of_characters(self):
        payload = state_to_private_payload(self.state())
        payload["approved_changes"] = "approved"
        with self.assertRaisesRegex(ContinuityPolicyError, "array of strings"):
            load_checkpoint(payload)

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
            now_utc=NOW_UTC,
        )
        self.assertEqual(state, second)
        self.assertEqual(brief.checkpoint_id, second.checkpoint_id)
        self.assertEqual(brief.mode, "development")

    def test_bootstrap_rejects_mismatched_authority_receipt(self):
        state = self.state()
        store = MemoryStore((state_to_private_payload(state),))
        with self.assertRaisesRegex(ContinuityPolicyError, "does not match binding"):
            bootstrap_helpyou_session(
                state.user_scope_id, store, TestVerifier(mismatch=True), now_utc=NOW_UTC
            )

    def test_receipt_binds_complete_governed_checkpoint_state(self):
        original = self.state()
        tampered = replace(original, next_prompt="Tampered but internally rehashed prompt")
        store = MemoryStore((state_to_private_payload(tampered),))
        verifier = TestVerifier(
            expected_governed_fingerprint=governed_state_fingerprint(original)
        )
        with self.assertRaisesRegex(ContinuityPolicyError, "does not match binding"):
            bootstrap_helpyou_session(
                original.user_scope_id, store, verifier, now_utc=NOW_UTC
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
                        state.user_scope_id, store, verifier, now_utc=NOW_UTC
                    )

    def test_expired_authority_receipt_fails_closed(self):
        state = self.state()
        store = MemoryStore((state_to_private_payload(state),))
        verifier = TestVerifier(expires_at_utc="2026-08-27T02:59:59Z")
        with self.assertRaisesRegex(ContinuityPolicyError, "not currently valid"):
            bootstrap_helpyou_session(
                state.user_scope_id, store, verifier, now_utc=NOW_UTC
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
                state.user_scope_id, store, verifier, now_utc=NOW_UTC
            )

    def test_bootstrap_requires_private_store_capability(self):
        state = self.state()
        store = PublicStore((state_to_private_payload(state),))
        with self.assertRaisesRegex(ContinuityPolicyError, "PRIVATE store"):
            bootstrap_helpyou_session(
                state.user_scope_id, store, TestVerifier(), now_utc=NOW_UTC
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
                first.user_scope_id, store, TestVerifier(), now_utc=NOW_UTC
            )

    def test_broken_predecessor_chain_fails(self):
        first, second = self.state(), self.successor()
        bad = replace(second, previous_checkpoint_id="HCP-XXX")
        store = MemoryStore((state_to_private_payload(first), state_to_private_payload(bad)))
        with self.assertRaisesRegex(ContinuityPolicyError, "predecessor chain"):
            bootstrap_helpyou_session(
                first.user_scope_id, store, TestVerifier(), now_utc=NOW_UTC
            )

    def test_checkpoint_id_cannot_be_reused_later_in_chain(self):
        first, second = self.state(), self.successor()
        third = replace(
            second,
            checkpoint_id=first.checkpoint_id,
            sequence=3,
            previous_checkpoint_id=second.checkpoint_id,
            updated_at_utc="2026-08-27T02:00:00Z",
            authority=self.authority("e"),
        )
        store = MemoryStore(tuple(state_to_private_payload(item) for item in (first, second, third)))
        with self.assertRaisesRegex(ContinuityPolicyError, "reused within the chain"):
            bootstrap_helpyou_session(
                first.user_scope_id, store, TestVerifier(), now_utc=NOW_UTC
            )

    def test_persist_round_trip_verifies(self):
        store = MemoryStore()
        persist_checkpoint(store, self.state(), TestVerifier(), now_utc=NOW_UTC)
        self.assertEqual(len(store.payloads), 1)

    def test_failed_persistence_is_not_reported_as_success(self):
        with self.assertRaisesRegex(ContinuityPolicyError, "compare-and-swap"):
            persist_checkpoint(
                MemoryStore(drop_writes=True), self.state(), TestVerifier(),
                now_utc=NOW_UTC,
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
        )
        store = RaceStore(
            (state_to_private_payload(first),), state_to_private_payload(competing)
        )
        with self.assertRaisesRegex(ContinuityPolicyError, "compare-and-swap"):
            persist_checkpoint(store, candidate, TestVerifier(), now_utc=NOW_UTC)

    def test_invalid_sequence_is_rejected_before_store_mutation(self):
        first = self.state()
        invalid = replace(
            self.successor(),
            checkpoint_id="HCP-003",
            sequence=3,
            previous_checkpoint_id=first.checkpoint_id,
            updated_at_utc="2026-08-27T02:00:00Z",
            authority=self.authority("e"),
        )
        store = MemoryStore((state_to_private_payload(first),))
        with self.assertRaisesRegex(ContinuityPolicyError, "not the next sequence"):
            persist_checkpoint(store, invalid, TestVerifier(), now_utc=NOW_UTC)
        self.assertEqual(len(store.payloads), 1)

    def test_reused_historical_id_is_rejected_before_store_mutation(self):
        first, second = self.state(), self.successor()
        invalid = replace(
            second,
            checkpoint_id=first.checkpoint_id,
            sequence=3,
            previous_checkpoint_id=second.checkpoint_id,
            updated_at_utc="2026-08-27T02:00:00Z",
            authority=self.authority("e"),
        )
        store = MemoryStore(
            (state_to_private_payload(first), state_to_private_payload(second))
        )
        with self.assertRaisesRegex(ContinuityPolicyError, "historical checkpoint_id"):
            persist_checkpoint(store, invalid, TestVerifier(), now_utc=NOW_UTC)
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
