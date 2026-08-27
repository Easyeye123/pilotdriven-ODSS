from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import unittest

from helpyou_continuity import (
    APPROVED_DEFAULTS_V1,
    AuthorityPointers,
    CheckpointStatus,
    ContinuityEvent,
    ContinuityPolicyError,
    ContinuityState,
    InteractionMode,
    PilotMemoryPair,
    bootstrap_helpyou_session,
    checkpoint_required,
    facilitation_sequence,
    load_checkpoint,
    persist_checkpoint,
    public_checkpoint_projection,
    record_approved_bundle,
    record_mode_change,
    select_mode,
    state_to_payload,
)


EXPECTED_DEFAULTS = (
    "D1: GitHub protocol plus persistent human-readable authority",
    "D2: checkpoint after every approved material change",
    "D3: automatic load with a visible status brief",
    "D4: Development Mode unless Assessment or Research is explicitly selected",
)


class MemoryStore:
    def __init__(self, payloads=(), *, drop_writes=False):
        self.payloads = [deepcopy(item) for item in payloads]
        self.drop_writes = drop_writes

    def list_checkpoints(self, user_scope_id):
        return deepcopy(self.payloads)

    def put_checkpoint(self, payload):
        if not self.drop_writes:
            self.payloads.append(deepcopy(payload))


class HelpyouContinuityV2Tests(unittest.TestCase):
    def authority(self, marker="a") -> AuthorityPointers:
        return AuthorityPointers(
            github_repository="Easyeye123/pilotdriven-ODSS",
            github_path="docs/helpyou/HELPYOU_CONTINUITY_PROTOCOL_V1.md",
            github_commit_sha="a" * 40,
            policy_fingerprint="sha256:" + "b" * 64,
            human_record_id=f"HCP-{marker.upper()}001",
            human_record_fingerprint="sha256:" + marker * 64,
            github_main_verified=True,
            human_record_verified=True,
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

    def test_string_false_is_not_a_verified_boolean(self):
        payload = state_to_payload(self.state())
        payload["authority"]["github_main_verified"] = "false"
        with self.assertRaisesRegex(ContinuityPolicyError, "JSON boolean"):
            load_checkpoint(payload)

    def test_invalid_sha_and_fingerprint_fail(self):
        payload = state_to_payload(self.state())
        payload["authority"]["github_commit_sha"] = "not-a-sha"
        with self.assertRaisesRegex(ContinuityPolicyError, "40 lowercase hex"):
            load_checkpoint(payload)
        payload = state_to_payload(self.state())
        payload["authority"]["policy_fingerprint"] = "sha256:bad"
        with self.assertRaisesRegex(ContinuityPolicyError, "64 lowercase hex"):
            load_checkpoint(payload)

    def test_invalid_timestamp_fails(self):
        payload = state_to_payload(self.state())
        payload["updated_at_utc"] = "not-a-dateZ"
        with self.assertRaisesRegex(ContinuityPolicyError, "ISO-8601"):
            load_checkpoint(payload)

    def test_string_cannot_become_tuple_of_characters(self):
        payload = state_to_payload(self.state())
        payload["approved_changes"] = "approved"
        with self.assertRaisesRegex(ContinuityPolicyError, "array of strings"):
            load_checkpoint(payload)

    def test_private_memory_round_trips(self):
        state = replace(
            self.state(),
            private_pilot_memory=(PilotMemoryPair(
                raw_pilot_wording="Private exact wording",
                ai_interpretation="Private interpreted meaning",
            ),),
        )
        self.assertEqual(load_checkpoint(state_to_payload(state)), state)

    def test_bootstrap_loads_latest_and_returns_brief(self):
        first, second = self.state(), self.successor()
        state, brief = bootstrap_helpyou_session(
            first.user_scope_id, MemoryStore((state_to_payload(first), state_to_payload(second)))
        )
        self.assertEqual(state, second)
        self.assertEqual(brief.checkpoint_id, second.checkpoint_id)
        self.assertEqual(brief.mode, "development")

    def test_competing_successors_fail_closed(self):
        first, second = self.state(), self.successor()
        conflict = replace(second, checkpoint_id="HCP-099")
        store = MemoryStore((state_to_payload(first), state_to_payload(second), state_to_payload(conflict)))
        with self.assertRaisesRegex(ContinuityPolicyError, "Conflicting checkpoints"):
            bootstrap_helpyou_session(first.user_scope_id, store)

    def test_broken_predecessor_chain_fails(self):
        first, second = self.state(), self.successor()
        bad = replace(second, previous_checkpoint_id="HCP-XXX")
        store = MemoryStore((state_to_payload(first), state_to_payload(bad)))
        with self.assertRaisesRegex(ContinuityPolicyError, "predecessor chain"):
            bootstrap_helpyou_session(first.user_scope_id, store)

    def test_persist_round_trip_verifies(self):
        store = MemoryStore()
        persist_checkpoint(store, self.state())
        self.assertEqual(len(store.payloads), 1)

    def test_failed_persistence_is_not_reported_as_success(self):
        with self.assertRaisesRegex(ContinuityPolicyError, "No continuity checkpoint"):
            persist_checkpoint(MemoryStore(drop_writes=True), self.state())

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
