from typing import Any


SCENARIO_STEPS: list[dict[str, Any]] = [
    {
        "id": "intro",
        "type": "intro",
        "title": "Behavioral Mirror Setup",
        "prompt": "This short scenario learns how your values interact under pressure. There are no right answers.",
    },
    {
        "id": "triad_1",
        "type": "triad",
        "title": "Triad 1: Pressure Response",
        "prompt": "When a decision is urgent and information is incomplete, which do you notice first?",
        "options": ["Risk to people", "Speed of execution", "Long-term consequences"],
    },
    {
        "id": "triad_2",
        "type": "triad",
        "title": "Triad 2: Ambiguity Frame",
        "prompt": "When a situation is ambiguous, which framing feels most natural?",
        "options": ["Clarify the rules", "Look for hidden trade-offs", "Test with a small action"],
    },
    {
        "id": "triad_3",
        "type": "triad",
        "title": "Triad 3: Trust Signal",
        "prompt": "Which signal most increases your trust in a recommendation?",
        "options": ["Transparent reasoning", "Past performance", "Alignment with values"],
    },
    {
        "id": "duel_1",
        "type": "duel",
        "title": "Trade-off Duel 1",
        "prompt": "Choose the option you would defend if resources are limited.",
        "options": ["Protect quality even if delivery slows", "Ship sooner and improve later"],
    },
    {
        "id": "duel_2",
        "type": "duel",
        "title": "Trade-off Duel 2",
        "prompt": "Which is more acceptable in a prototype?",
        "options": ["More manual control with fewer surprises", "More automation with more monitoring"],
    },
    {
        "id": "duel_3",
        "type": "duel",
        "title": "Trade-off Duel 3",
        "prompt": "If users disagree with the twin, what should the system prioritize?",
        "options": ["Ask for correction immediately", "Show why it inferred that answer first"],
    },
    {
        "id": "context_flip_1",
        "type": "context_flip",
        "title": "Context Flip 1",
        "prompt": "You chose a cautious path. Would your answer change if the decision only affected you, not a team? Explain briefly.",
    },
    {
        "id": "context_flip_2",
        "type": "context_flip",
        "title": "Context Flip 2",
        "prompt": "You chose speed or control earlier. Would your answer change if the outcome became public? Explain briefly.",
    },
    {
        "id": "twin_rank_1",
        "type": "twin_rank",
        "title": "Twin Response Ranking",
        "prompt": "Rank which preliminary twin response sounds closest to you.",
        "options": [
            "I would slow down, clarify the hidden risks, then act.",
            "I would move quickly with a reversible decision and monitor closely.",
            "I would ask who is affected first, then choose the least harmful path.",
        ],
    },
    {
        "id": "correction_1",
        "type": "correction",
        "title": "Correction Loop",
        "prompt": "What did the preliminary twin misunderstand or miss about your reasoning?",
    },
]


STEP_BY_ID = {step["id"]: step for step in SCENARIO_STEPS}
STEP_IDS = [step["id"] for step in SCENARIO_STEPS]


def get_step(step_id: str) -> dict[str, Any] | None:
    return STEP_BY_ID.get(step_id)


def get_next_step_id(step_id: str) -> str | None:
    try:
        index = STEP_IDS.index(step_id)
    except ValueError:
        return None

    next_index = index + 1
    if next_index >= len(STEP_IDS):
        return None
    return STEP_IDS[next_index]


def event_type_for_step(step_type: str) -> str:
    return {
        "intro": "scenario_started",
        "triad": "triad_answered",
        "duel": "duel_answered",
        "context_flip": "context_flip_answered",
        "twin_rank": "twin_response_ranked",
        "correction": "correction_submitted",
    }.get(step_type, "scenario_step_answered")