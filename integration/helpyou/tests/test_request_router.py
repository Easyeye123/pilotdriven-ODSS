from __future__ import annotations

import unittest

from helpyou_core.contracts import TaskRoute
from helpyou_core.request_router import RequestEnvelope, route_request, routes_only


class RequestRouterTests(unittest.TestCase):
    def test_sq23_attachment_routes_to_odss(self) -> None:
        tasks = route_request(RequestEnvelope(attachment_names=("SQ02325072026JFK.pdf",)))
        self.assertEqual(routes_only(tasks), (TaskRoute.ODSS_CFP,))
        self.assertFalse(tasks[0].cognitive_models_permitted)

    def test_cfp_and_scenario_are_split(self) -> None:
        tasks = route_request(
            RequestEnvelope(
                attachment_names=("SQ02325072026JFK.pdf",),
                intents=("scenario",),
                pilot_reasoning_present=True,
                asks_for_developmental_review=True,
            )
        )
        self.assertEqual(
            routes_only(tasks),
            (TaskRoute.ODSS_CFP, TaskRoute.CFP_GROUNDED_SCENARIO),
        )
        self.assertFalse(tasks[0].cognitive_models_permitted)
        self.assertTrue(tasks[1].cognitive_models_permitted)
        self.assertTrue(tasks[1].cbta_permitted)

    def test_manual_lookup_does_not_activate_cognitive_models(self) -> None:
        task = route_request(
            RequestEnvelope(
                intents=("manual_lookup",),
                pilot_reasoning_present=True,
                asks_for_developmental_review=True,
            )
        )[0]
        self.assertEqual(task.route, TaskRoute.AUTHORITATIVE_RETRIEVAL)
        self.assertFalse(task.cognitive_models_permitted)
        self.assertFalse(task.cbta_permitted)

    def test_mixed_request_preserves_independent_routes(self) -> None:
        tasks = route_request(
            RequestEnvelope(
                intents=("compile_manuals", "review_my_reasoning"),
                attachment_names=("SQ02325072026JFK.pdf",),
                pilot_reasoning_present=True,
            )
        )
        self.assertEqual(
            routes_only(tasks),
            (
                TaskRoute.ODSS_CFP,
                TaskRoute.AUTHORITATIVE_COMPILATION,
                TaskRoute.PILOT_REASONING_REVIEW,
            ),
        )


if __name__ == "__main__":
    unittest.main()
