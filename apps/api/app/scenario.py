from __future__ import annotations

from copy import deepcopy
from typing import Any


MIN_ADAPTIVE_QUESTIONS = 20
MAX_ADAPTIVE_QUESTIONS = 25
COMPLETION_CONFIDENCE = 0.80
MIN_REPLAY_START_QUESTIONS = 8
REPLAY_SCENARIO_COUNT = 2
TWIN_RESPONSES_PER_REPLAY = 3

ONBOARDING_STEP: dict[str, Any] = {
    "id": "onboarding_profile",
    "type": "onboarding",
    "title": "Tailor Your Behavioral Mirror",
    "prompt": "Share a short overview of your background, regular hobbies, work, or a project you are currently focused on.",
}

FALLBACK_QUESTIONS: list[dict[str, Any]] = [
    {
        "type": "triad",
        "title": "Pressure Around a Real Project",
        "prompt": "A project connected to your background suddenly has a visible problem. What do you prioritize first?",
        "options": [
            "Find who could be affected and reduce their risk first.",
            "Make the smallest fast fix that gets momentum back.",
            "Slow down enough to protect the long-term structure and standards.",
        ],
    },
    {
        "type": "duel",
        "title": "Guardrails or Speed",
        "prompt": "You can either add stronger checks now or move faster and refine after feedback. Which would you defend?",
        "options": [
            "Add the guardrails now, even if the next step takes longer.",
            "Ship the next useful version now and improve the details after feedback.",
        ],
    },
    {
        "type": "triad",
        "title": "Ambiguous Trade-Off",
        "prompt": "A decision in your domain has incomplete information and competing expectations. What deserves the most attention?",
        "options": [
            "The people who might absorb the cost of a wrong decision.",
            "The fastest reversible action that reveals more information.",
            "The principle or architecture that should still hold after the rush.",
        ],
    },
    {
        "type": "duel",
        "title": "Quality Threshold",
        "prompt": "A useful outcome is close, but quality checks may delay it. Which path better matches your default instinct?",
        "options": [
            "Protect the quality threshold before widening access.",
            "Get the useful version in front of people and tighten quality as it evolves.",
        ],
    },
    {
        "type": "triad",
        "title": "Trust Under Pressure",
        "prompt": "When others are waiting on your call, which signal most shapes whether you trust the next move?",
        "options": [
            "It clearly reduces harm or confusion for affected people.",
            "It can be executed quickly enough to prevent drift.",
            "It keeps the system understandable and maintainable later.",
        ],
    },
    {
        "type": "triad",
        "title": "Public Outcome",
        "prompt": "If the decision became public in your community or workplace, what would you most want to be able to explain?",
        "options": [
            "How you protected the people most exposed to the outcome.",
            "Why moving quickly was the practical way to limit damage.",
            "Why the decision preserved standards that matter beyond this moment.",
        ],
    },
    {
        "type": "duel",
        "title": "Iteration Boundary",
        "prompt": "A fast iteration would teach you a lot, but it may create cleanup work. Which trade-off do you choose?",
        "options": [
            "Set firmer constraints first so the cleanup does not compound.",
            "Run the iteration now and use what it teaches to decide the cleanup.",
        ],
    },
    {
        "type": "triad",
        "title": "Final Calibration",
        "prompt": "At the end of a pressured cycle, what evidence would most change your next decision?",
        "options": [
            "A clearer view of who was helped, confused, or put at risk.",
            "Proof that the fast path created enough learning or relief.",
            "Evidence that the solution remains stable, fair, and reusable.",
        ],
    },
]

TRIAD_TRAIT_AXES = {
    0: "risk_to_people",
    1: "speed_of_execution",
    2: "long_term_stability",
}

DUEL_TRAIT_AXES = {
    0: "quality_guardrails",
    1: "ship_fast_iteration",
}


def initial_adaptive_state() -> dict[str, Any]:
    return {
        "confidence": 0.0,
        "axis_scores": {
            "risk_to_people": 0,
            "speed_of_execution": 0,
            "long_term_stability": 0,
            "quality_guardrails": 0,
            "ship_fast_iteration": 0,
        },
        "signals": [],
    }


def normalize_generated_step(raw_step: dict[str, Any], question_number: int) -> dict[str, Any]:
    step_type = raw_step.get("type")
    option_count = 2 if step_type == "duel" else 3
    options = raw_step.get("options")
    if not isinstance(options, list):
        options = []

    normalized_options = [
        str(option).strip()
        for option in options[:option_count]
        if isinstance(option, str) and option.strip()
    ]
    if len(normalized_options) != option_count:
        fallback = fallback_step(question_number)
        normalized_options = fallback["options"]
        step_type = fallback["type"]

    if step_type not in {"triad", "duel"}:
        fallback = fallback_step(question_number)
        step_type = fallback["type"]
        normalized_options = fallback["options"]

    normalized = {
        "id": f"adaptive_q_{question_number}",
        "type": step_type,
        "title": _string_or_default(raw_step.get("title"), f"Adaptive Question {question_number}"),
        "prompt": _string_or_default(raw_step.get("prompt"), fallback_step(question_number)["prompt"]),
        "options": normalized_options,
    }
    for key in (
        "generation_source",
        "acp_domain",
        "life_state",
        "signal_goal",
        "singapore_context_notes",
        "council_models_successful",
        "council_models_failed",
        "council_min_successes",
        "council_chair_model",
        "council_chair_status",
        "council_chair_rationale",
        "cultural_sensitivity_flags",
    ):
        if key in raw_step:
            normalized[key] = raw_step[key]
    return normalized


def fallback_step(question_number: int) -> dict[str, Any]:
    raw_step = deepcopy(FALLBACK_QUESTIONS[(question_number - 1) % len(FALLBACK_QUESTIONS)])
    raw_step["id"] = f"adaptive_q_{question_number}"
    return raw_step


def scenario_steps_for_token(adaptive_steps: list[dict[str, Any]] | None, include_onboarding: bool = True) -> list[dict[str, Any]]:
    steps = [deepcopy(ONBOARDING_STEP)] if include_onboarding else []
    steps.extend(deepcopy(adaptive_steps or []))
    return steps


def get_token_step(adaptive_steps: list[dict[str, Any]] | None, step_id: str) -> dict[str, Any] | None:
    if step_id == ONBOARDING_STEP["id"]:
        return deepcopy(ONBOARDING_STEP)
    for step in adaptive_steps or []:
        if step.get("id") == step_id:
            return deepcopy(step)
    return None


def event_type_for_step(step_type: str) -> str:
    return {
        "onboarding": "profile_submitted",
        "triad": "triad_answered",
        "duel": "duel_answered",
        "context_flip": "context_flip_answered",
        "correction": "correction_answered",
        "twin_rank": "twin_response_ranked",
        "indifference": "indifference_answered",
    }.get(step_type, "scenario_step_answered")


def trait_axis_for_choice(step_type: str, selected_index: int) -> str | None:
    if step_type == "triad":
        return TRIAD_TRAIT_AXES.get(selected_index)
    if step_type == "duel":
        return DUEL_TRAIT_AXES.get(selected_index)
    return None


def should_complete(adaptive_answer_count: int, confidence: float) -> bool:
    return adaptive_answer_count >= MAX_ADAPTIVE_QUESTIONS or (
        adaptive_answer_count >= MIN_ADAPTIVE_QUESTIONS and confidence >= COMPLETION_CONFIDENCE
    )


def _string_or_default(value: Any, default: str) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return default
