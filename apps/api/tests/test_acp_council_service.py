import unittest
from unittest.mock import patch

from app.models import ParticipantToken
from app.services.acp_council_service import ACPCouncilGenerationResult, generate_acp_council_step
from app.services.adaptive_scenario_service import generate_adaptive_step


def _candidate(title: str = "Proxy Guidance", step_type: str = "duel") -> dict:
    options = (
        ["Keep me comfortable at home if possible.", "Move me to more intensive care if risk rises."]
        if step_type == "duel"
        else [
            "Keep me comfortable at home if possible.",
            "Move me to more intensive care if risk rises.",
            "Ask my spouse to decide after hearing the care team's view.",
        ]
    )
    return {
        "type": step_type,
        "title": title,
        "prompt": "If your health worsened and your spouse had to speak for you, what should guide the decision first?",
        "options": options,
        "acp_domain": "proxy_guidance",
        "life_state": "loss_of_capacity",
        "signal_goal": "Tests what the proxy should prioritize when capacity is reduced.",
        "singapore_context_notes": ["Does not assume children are available as decision makers."],
    }


class SettingsStub:
    openrouter_api_key = "test-key"
    openrouter_model = "chair-model"
    openrouter_acp_council_models = "model-a,model-b,model-c,model-d"
    openrouter_acp_council_min_successes = 3
    openrouter_acp_chair_model = "chair-model"
    openrouter_acp_council_timeout_seconds = 5

    @property
    def has_openrouter_key(self) -> bool:
        return bool(self.openrouter_api_key)


class NoCouncilSettingsStub(SettingsStub):
    openrouter_api_key = ""
    openrouter_acp_council_models = ""

    @property
    def has_openrouter_key(self) -> bool:
        return False


class FakeCouncilClient:
    def __init__(self, responses: dict[str, object]):
        self.responses = responses
        self.calls: list[str] = []

    def request_json(self, model: str, system: str, user: str, temperature: float, timeout_seconds: float) -> dict:
        self.calls.append(model)
        response = self.responses.get(model)
        if isinstance(response, Exception):
            raise response
        if response is None:
            raise ValueError(f"No fake response for {model}")
        return response


class ACPCouncilServiceTests(unittest.TestCase):
    def setUp(self):
        self.participant = ParticipantToken(id="token-1", label="Liying", token_hash="hash", user_profile="Singapore ACP planning")
        self.settings = SettingsStub()

    def test_council_success_uses_three_or_more_distinct_models(self):
        client = FakeCouncilClient(
            {
                "model-a": _candidate("A"),
                "model-b": _candidate("B"),
                "model-c": _candidate("C"),
                "model-d": _candidate("D"),
                "chair-model": {
                    "selected_step": _candidate("Chair pick"),
                    "rationale": "Best proxy-focused framing.",
                    "cultural_sensitivity_flags": ["Check spouse wording remains non-coercive."],
                },
            }
        )

        result = generate_acp_council_step(self.participant, [], {}, 0, client=client, settings=self.settings)

        self.assertIsNotNone(result.next_step)
        self.assertEqual(result.metadata["status"], "generated")
        self.assertEqual(result.next_step["generation_source"], "acp_council")
        self.assertEqual(result.next_step["title"], "Chair pick")
        self.assertEqual(result.metadata["council_models_successful"], ["model-a", "model-b", "model-c", "model-d"])
        self.assertEqual(result.metadata["council_models_failed"], [])

    def test_council_failure_does_not_fallback_when_too_few_models_succeed(self):
        client = FakeCouncilClient(
            {
                "model-a": _candidate("A"),
                "model-b": _candidate("B"),
                "model-c": ValueError("bad json"),
                "model-d": ValueError("provider down"),
            }
        )

        result = generate_acp_council_step(self.participant, [], {}, 0, client=client, settings=self.settings)

        self.assertIsNone(result.next_step)
        self.assertEqual(result.metadata["status"], "council_failed")
        self.assertEqual(result.metadata["reason"], "insufficient_successful_council_models")
        self.assertEqual(result.metadata["council_models_successful"], ["model-a", "model-b"])
        self.assertEqual(len(result.metadata["council_models_failed"]), 2)

    def test_malformed_candidate_counts_as_model_failure_and_invalid_chair_falls_back(self):
        invalid_chair = _candidate("Invalid chair")
        invalid_chair["options"] = ["only one"]
        client = FakeCouncilClient(
            {
                "model-a": _candidate("A"),
                "model-b": {"type": "duel", "title": "Malformed"},
                "model-c": _candidate("C"),
                "model-d": _candidate("D"),
                "chair-model": {"selected_step": invalid_chair},
            }
        )

        result = generate_acp_council_step(self.participant, [], {}, 0, client=client, settings=self.settings)

        self.assertIsNotNone(result.next_step)
        self.assertEqual(result.metadata["status"], "generated")
        self.assertEqual(result.next_step["title"], "A")
        self.assertEqual(result.metadata["council_chair_status"], "fallback_candidate")
        self.assertEqual(result.metadata["council_models_successful"], ["model-a", "model-c", "model-d"])
        self.assertEqual(len(result.metadata["council_models_failed"]), 1)

    def test_adaptive_generation_uses_council_when_configured(self):
        council_step = _candidate("Council adaptive")
        council_step["generation_source"] = "acp_council"
        council_step["council_models_successful"] = ["model-a", "model-b", "model-c"]
        council_step["council_models_failed"] = []
        council_step["council_min_successes"] = 3
        result = ACPCouncilGenerationResult(
            hidden_state={"confidence": 0.2, "axis_scores": {}, "signals": []},
            next_step=council_step,
            should_complete=False,
            metadata={"status": "generated", "generation_source": "acp_council"},
        )

        with patch("app.services.adaptive_scenario_service.get_settings", return_value=self.settings), patch(
            "app.services.adaptive_scenario_service.generate_acp_council_step",
            return_value=result,
        ):
            generated = generate_adaptive_step(self.participant, [], None, None, 0)

        self.assertEqual(generated.metadata["generation_source"], "acp_council")
        self.assertEqual(generated.next_step["generation_source"], "acp_council")
        self.assertEqual(generated.next_step["id"], "adaptive_q_1")
        self.assertEqual(generated.next_step["council_models_successful"], ["model-a", "model-b", "model-c"])

    def test_no_council_setting_preserves_local_fallback(self):
        with patch("app.services.adaptive_scenario_service.get_settings", return_value=NoCouncilSettingsStub()):
            generated = generate_adaptive_step(self.participant, [], None, None, 0)

        self.assertEqual(generated.metadata["status"], "fallback")
        self.assertIsNotNone(generated.next_step)
        self.assertNotEqual(generated.next_step.get("generation_source"), "acp_council")


if __name__ == "__main__":
    unittest.main()
