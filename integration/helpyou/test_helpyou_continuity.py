from __future__ import annotations

import unittest

from helpyou_continuity import (
    AuthorityPointers,
    ContinuityEvent,
    ContinuityPolicyError,
    ContinuityState,
    InteractionMode,
    PilotMemoryPair,
    APPROVED_DEFAULTS_V1,
    bootstrap_session,
    checkpoint_required,
    facilitation_sequence,
    load_checkpoint,
    public_checkpoint_projection,
    record_approved_change,
    record_approved_bundle,
    select_mode,
    visible_resume_brief,
)


class HelpyouContinuityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.authority = AuthorityPointers(
            github_repository="Easyeye123/pilotdriven-ODSS",
            github_path="docs/helpyou/HELPYOU_CONTINUITY_PROTOCOL_V1.md",
            github_commit_sha="a" * 40,
            policy_fingerprint="sha256:protocol",
            human_record_id="HR-20260827-001",
            human_record_fingerprint="sha256:human-record",
            github_main_verified=True,
            human_record_verified=True,
        )
        self.state = ContinuityState(
            protocol_version="1.0",
            checkpoint_id="CP-001",
            updated_at_utc="2026-08-27T00:00:00Z",
            authority=self.authority,
            active_case_ref="private-case-reference",
            next_prompt="Continue the controlled case review.",
        )

    def test_development_is_the_default_mode(self) -> None:
        mode, selected = select_mode(None)
        self.assertIs(mode, InteractionMode.DEVELOPMENT)
        self.assertFalse(selected)

    def test_four_defaults_are_hardcoded_exactly(self) -> None:
        self.assertEqual(len(APPROVED_DEFAULTS_V1), 4)
        self.assertIn("GitHub protocol", APPROVED_DEFAULTS_V1[0])
        self.assertIn("every approved material change", APPROVED_DEFAULTS_V1[1])
        self.assertIn("visible status brief", APPROVED_DEFAULTS_V1[2])
        self.assertIn("Development Mode", APPROVED_DEFAULTS_V1[3])

    def test_assessment_and_research_require_explicit_selection(self) -> None:
        mode, selected = select_mode("assessment")
        self.assertIs(mode, InteractionMode.ASSESSMENT)
        self.assertTrue(selected)
        with self.assertRaises(ContinuityPolicyError):
            ContinuityState(
                protocol_version="1.0",
                checkpoint_id="CP-X",
                updated_at_utc="2026-08-27T00:00:00Z",
                authority=self.authority,
                mode=InteractionMode.RESEARCH,
                mode_selected_explicitly=False,
            ).validate()

    def test_every_approved_material_event_requires_checkpoint(self) -> None:
        self.assertTrue(checkpoint_required(ContinuityEvent.APPROVED_MATERIAL_CHANGE))
        self.assertTrue(checkpoint_required(ContinuityEvent.APPROVED_SOURCE_REVISION))
        self.assertTrue(checkpoint_required(ContinuityEvent.APPROVED_MODE_CHANGE))
        self.assertFalse(checkpoint_required(ContinuityEvent.DRAFT_CHANGE))

    def test_approved_change_creates_successor_checkpoint(self) -> None:
        successor = record_approved_change(
            self.state,
            event=ContinuityEvent.APPROVED_MATERIAL_CHANGE,
            approved_change="Four continuity defaults approved.",
            checkpoint_id="CP-002",
            updated_at_utc="2026-08-27T01:00:00Z",
            next_prompt="Calibrate Development Mode prompting.",
        )
        self.assertEqual(successor.checkpoint_id, "CP-002")
        self.assertEqual(successor.approved_changes[-1], "Four continuity defaults approved.")

    def test_four_item_approval_is_one_atomic_checkpoint(self) -> None:
        successor = record_approved_bundle(
            self.state,
            event=ContinuityEvent.APPROVED_MATERIAL_CHANGE,
            approved_changes=APPROVED_DEFAULTS_V1,
            checkpoint_id="CP-FOUR",
            updated_at_utc="2026-08-27T01:00:00Z",
            next_prompt="Calibrate Development Mode prompting.",
        )
        self.assertEqual(successor.checkpoint_id, "CP-FOUR")
        self.assertEqual(successor.approved_changes, APPROVED_DEFAULTS_V1)
        replay = record_approved_bundle(
            successor,
            event=ContinuityEvent.APPROVED_MATERIAL_CHANGE,
            approved_changes=APPROVED_DEFAULTS_V1,
            checkpoint_id="CP-SHOULD-NOT-APPEAR",
            updated_at_utc="2026-08-27T02:00:00Z",
            next_prompt="Different prompt",
        )
        self.assertIs(replay, successor)

    def test_draft_cannot_be_recorded_as_approved_checkpoint(self) -> None:
        with self.assertRaises(ContinuityPolicyError):
            record_approved_change(
                self.state,
                event=ContinuityEvent.DRAFT_CHANGE,
                approved_change="Unapproved draft",
                checkpoint_id="CP-002",
                updated_at_utc="2026-08-27T01:00:00Z",
                next_prompt="Continue.",
            )

    def test_dual_authority_is_required(self) -> None:
        bad = ContinuityState(
            protocol_version="1.0",
            checkpoint_id="CP-X",
            updated_at_utc="2026-08-27T00:00:00Z",
            authority=AuthorityPointers(
                github_repository="Easyeye123/pilotdriven-ODSS",
                github_path="docs/helpyou/protocol.md",
                github_commit_sha="a" * 40,
                policy_fingerprint="sha256:protocol",
                human_record_id="",
                human_record_fingerprint="sha256:human-record",
                github_main_verified=True,
                human_record_verified=True,
            ),
        )
        with self.assertRaises(ContinuityPolicyError):
            bad.validate()

    def test_resume_brief_is_always_visible(self) -> None:
        brief = visible_resume_brief(self.state)
        self.assertEqual(brief.mode, "development")
        self.assertIn("GitHub", brief.authority_status)
        self.assertEqual(brief.next_prompt, self.state.next_prompt)

    def test_presence_without_external_verification_is_rejected(self) -> None:
        unverified = AuthorityPointers(
            github_repository="Easyeye123/pilotdriven-ODSS",
            github_path="docs/helpyou/HELPYOU_CONTINUITY_PROTOCOL_V1.md",
            github_commit_sha="a" * 40,
            policy_fingerprint="sha256:protocol",
            human_record_id="HR-001",
            human_record_fingerprint="sha256:record",
            github_main_verified=False,
            human_record_verified=True,
        )
        with self.assertRaisesRegex(ContinuityPolicyError, "merged main-branch"):
            unverified.validate()

    def test_missing_checkpoint_fields_fail_closed(self) -> None:
        with self.assertRaisesRegex(ContinuityPolicyError, "cannot be reconstructed"):
            load_checkpoint({"protocol_version": "1.0"})
        with self.assertRaisesRegex(ContinuityPolicyError, "No continuity checkpoint"):
            bootstrap_session(None)

    def test_development_mode_teaches_before_it_probes(self) -> None:
        steps = facilitation_sequence(InteractionMode.DEVELOPMENT)
        self.assertIn("Explain the controlling policy", steps[1])
        self.assertIn("Present the materially different viable options", steps[2])
        self.assertIn("Ask one focused question", steps[3])

    def test_assessment_mode_does_not_coach_before_commitment(self) -> None:
        steps = facilitation_sequence(InteractionMode.ASSESSMENT)
        self.assertTrue(any("Do not coach" in step for step in steps))

    def test_private_pilot_wording_is_not_in_public_projection(self) -> None:
        private_state = ContinuityState(
            protocol_version="1.0",
            checkpoint_id="CP-PRIVATE",
            updated_at_utc="2026-08-27T02:00:00Z",
            authority=self.authority,
            private_pilot_memory=(
                PilotMemoryPair(
                    raw_pilot_wording="Private exact wording",
                    ai_interpretation="Private interpreted meaning",
                ),
            ),
        )
        projection = str(public_checkpoint_projection(private_state))
        self.assertNotIn("Private exact wording", projection)
        self.assertNotIn("Private interpreted meaning", projection)
        self.assertNotIn("human_record_id", projection)

    def test_facilitator_word_alone_does_not_select_assessment(self) -> None:
        with self.assertRaises(ContinuityPolicyError):
            select_mode("facilitator")


if __name__ == "__main__":
    unittest.main()
