from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal

import httpx
from pydantic import BaseModel, Field, ValidationError, model_validator

from app.config import get_settings
from app.models import ParticipantToken, RawEvent, now_utc
from app.scenario import (
    MAX_ADAPTIVE_QUESTIONS,
    REPLAY_SCENARIO_COUNT,
    TWIN_RESPONSES_PER_REPLAY,
    fallback_step,
    initial_adaptive_state,
    normalize_generated_step,
    should_complete,
    trait_axis_for_choice,
)
from app.services.profile_service import build_model_profile_context


class GeneratedStepPayload(BaseModel):
    type: Literal["triad", "duel"]
    title: str = Field(min_length=1, max_length=160)
    prompt: str = Field(min_length=1, max_length=700)
    options: list[str] = Field(min_length=2, max_length=3)

    @model_validator(mode="after")
    def validate_option_count(self) -> "GeneratedStepPayload":
        expected_count = 2 if self.type == "duel" else 3
        if len(self.options) != expected_count:
            raise ValueError(f"{self.type} steps must include exactly {expected_count} options")
        if any(not option.strip() for option in self.options):
            raise ValueError("Options must be non-empty strings")
        return self


class GeneratedContextFlipPayload(BaseModel):
    type: Literal["context_flip"] = "context_flip"
    title: str = Field(min_length=1, max_length=160)
    prompt: str = Field(min_length=1, max_length=900)
    context_title: str | None = Field(default=None, max_length=120)
    context_items: list[str] = Field(default_factory=list, max_length=4)


class GeneratedTwinRankPayload(BaseModel):
    type: Literal["twin_rank"] = "twin_rank"
    title: str = Field(min_length=1, max_length=160)
    prompt: str = Field(min_length=1, max_length=800)
    options: list[str] = Field(min_length=TWIN_RESPONSES_PER_REPLAY, max_length=TWIN_RESPONSES_PER_REPLAY)
    context_title: str | None = Field(default=None, max_length=120)
    context_items: list[str] = Field(default_factory=list, max_length=4)

    @model_validator(mode="after")
    def validate_response_count(self) -> "GeneratedTwinRankPayload":
        if len(self.options) != TWIN_RESPONSES_PER_REPLAY:
            raise ValueError(f"twin_rank steps must include exactly {TWIN_RESPONSES_PER_REPLAY} options")
        if any(not option.strip() for option in self.options):
            raise ValueError("Twin responses must be non-empty strings")
        if len({option.strip() for option in self.options}) != len(self.options):
            raise ValueError("Twin responses must be distinct")
        return self


class AdaptiveModelPayload(BaseModel):
    hidden_state: dict[str, Any] = Field(default_factory=dict)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    should_complete: bool = False
    next_step: GeneratedStepPayload | None = None


@dataclass
class AdaptiveGenerationResult:
    hidden_state: dict[str, Any]
    next_step: dict[str, Any] | None
    should_complete: bool
    metadata: dict[str, Any]


def generate_adaptive_step(
    participant: ParticipantToken,
    events: list[RawEvent],
    last_step: dict[str, Any] | None,
    last_answer: dict[str, Any] | None,
    adaptive_answer_count: int,
) -> AdaptiveGenerationResult:
    current_state = _state_with_local_signal(
        participant.adaptive_scenario_state or initial_adaptive_state(),
        last_step,
        last_answer,
        adaptive_answer_count,
    )
    if adaptive_answer_count >= MAX_ADAPTIVE_QUESTIONS:
        return AdaptiveGenerationResult(
            hidden_state=current_state,
            next_step=None,
            should_complete=True,
            metadata=_metadata("completed", "max_questions_reached"),
        )

    settings = get_settings()
    question_number = adaptive_answer_count + 1
    if settings.has_openrouter_key:
        model_result = _generate_with_openrouter(
            participant=participant,
            events=events,
            current_state=current_state,
            last_step=last_step,
            last_answer=last_answer,
            adaptive_answer_count=adaptive_answer_count,
        )
        hidden_state = _normalize_hidden_state(model_result.hidden_state, fallback=current_state)
        if should_complete(adaptive_answer_count, _confidence(hidden_state)):
            return AdaptiveGenerationResult(
                hidden_state=hidden_state,
                next_step=None,
                should_complete=True,
                metadata=model_result.metadata,
            )
        next_step = model_result.next_step or fallback_step(question_number)
        return AdaptiveGenerationResult(
            hidden_state=hidden_state,
            next_step=normalize_generated_step(next_step, question_number),
            should_complete=False,
            metadata=model_result.metadata,
        )

    if should_complete(adaptive_answer_count, _confidence(current_state)):
        return AdaptiveGenerationResult(
            hidden_state=current_state,
            next_step=None,
            should_complete=True,
            metadata=_metadata("fallback", "openrouter_not_configured"),
        )

    return AdaptiveGenerationResult(
        hidden_state=current_state,
        next_step=fallback_step(question_number),
        should_complete=False,
        metadata=_metadata("fallback", "openrouter_not_configured", degraded=True),
    )


def record_adaptive_choice_signal(
    participant: ParticipantToken,
    last_step: dict[str, Any],
    last_answer: dict[str, Any],
    adaptive_answer_count: int,
) -> AdaptiveGenerationResult:
    current_state = _state_with_local_signal(
        participant.adaptive_scenario_state or initial_adaptive_state(),
        last_step,
        last_answer,
        adaptive_answer_count,
    )
    return AdaptiveGenerationResult(
        hidden_state=current_state,
        next_step=None,
        should_complete=False,
        metadata=_metadata("updated", "local_choice_signal"),
    )


def generate_context_flip_step(
    participant: ParticipantToken,
    events: list[RawEvent],
    replay_index: int,
    adaptive_answer_count: int,
) -> AdaptiveGenerationResult:
    current_state = _normalize_hidden_state(
        participant.adaptive_scenario_state or initial_adaptive_state(),
        fallback=initial_adaptive_state(),
    )
    fallback = _fallback_context_flip_step(participant, events, replay_index)
    settings = get_settings()
    if settings.has_openrouter_key:
        first_error: str | None = None
        for attempt in (1, 2):
            try:
                payload = _call_context_flip_openrouter(
                    participant=participant,
                    events=events,
                    current_state=current_state,
                    replay_index=replay_index,
                    adaptive_answer_count=adaptive_answer_count,
                    repair_error=first_error if attempt == 2 else None,
                )
                parsed = GeneratedContextFlipPayload.model_validate(payload)
                return AdaptiveGenerationResult(
                    hidden_state=current_state,
                    next_step=_context_flip_step(parsed.model_dump(), replay_index),
                    should_complete=False,
                    metadata=_step_metadata("generated", None, "context_flip", replay_index, attempts=attempt),
                )
            except (httpx.HTTPError, KeyError, TypeError, ValueError, ValidationError, json.JSONDecodeError) as exc:
                first_error = str(exc)

        return AdaptiveGenerationResult(
            hidden_state=current_state,
            next_step=fallback,
            should_complete=False,
            metadata=_step_metadata("fallback", first_error or "context_flip_generation_failed", "context_flip", replay_index, attempts=2, degraded=True),
        )

    return AdaptiveGenerationResult(
        hidden_state=current_state,
        next_step=fallback,
        should_complete=False,
        metadata=_step_metadata("fallback", "openrouter_not_configured", "context_flip", replay_index, degraded=True),
    )


def generate_twin_rank_step(
    participant: ParticipantToken,
    events: list[RawEvent],
    context_event: RawEvent,
    replay_index: int,
) -> AdaptiveGenerationResult:
    current_state = _normalize_hidden_state(
        participant.adaptive_scenario_state or initial_adaptive_state(),
        fallback=initial_adaptive_state(),
    )
    fallback = _fallback_twin_rank_step(participant, events, context_event, replay_index)
    settings = get_settings()
    if settings.has_openrouter_key:
        first_error: str | None = None
        for attempt in (1, 2):
            try:
                payload = _call_twin_rank_openrouter(
                    participant=participant,
                    events=events,
                    current_state=current_state,
                    context_event=context_event,
                    replay_index=replay_index,
                    repair_error=first_error if attempt == 2 else None,
                )
                parsed = GeneratedTwinRankPayload.model_validate(payload)
                return AdaptiveGenerationResult(
                    hidden_state=current_state,
                    next_step=_twin_rank_step(parsed.model_dump(), context_event, replay_index),
                    should_complete=False,
                    metadata=_step_metadata("generated", None, "twin_rank", replay_index, attempts=attempt),
                )
            except (httpx.HTTPError, KeyError, TypeError, ValueError, ValidationError, json.JSONDecodeError) as exc:
                first_error = str(exc)

        return AdaptiveGenerationResult(
            hidden_state=current_state,
            next_step=fallback,
            should_complete=False,
            metadata=_step_metadata("fallback", first_error or "twin_rank_generation_failed", "twin_rank", replay_index, attempts=2, degraded=True),
        )

    return AdaptiveGenerationResult(
        hidden_state=current_state,
        next_step=fallback,
        should_complete=False,
        metadata=_step_metadata("fallback", "openrouter_not_configured", "twin_rank", replay_index, degraded=True),
    )


def initialize_generation_metadata() -> dict[str, Any]:
    return {
        "status": "initialized",
        "degraded": False,
        "attempts": 0,
        "updated_at": now_utc().isoformat(),
    }


def _generate_with_openrouter(
    participant: ParticipantToken,
    events: list[RawEvent],
    current_state: dict[str, Any],
    last_step: dict[str, Any] | None,
    last_answer: dict[str, Any] | None,
    adaptive_answer_count: int,
) -> AdaptiveGenerationResult:
    first_error: str | None = None
    for attempt in (1, 2):
        try:
            payload = _call_openrouter(
                participant=participant,
                events=events,
                current_state=current_state,
                last_step=last_step,
                last_answer=last_answer,
                adaptive_answer_count=adaptive_answer_count,
                repair_error=first_error if attempt == 2 else None,
            )
            parsed = AdaptiveModelPayload.model_validate(payload)
            hidden_state = dict(parsed.hidden_state)
            if parsed.confidence is not None:
                hidden_state["confidence"] = parsed.confidence
            return AdaptiveGenerationResult(
                hidden_state=hidden_state,
                next_step=parsed.next_step.model_dump() if parsed.next_step else None,
                should_complete=parsed.should_complete,
                metadata=_metadata("generated", None, attempts=attempt),
            )
        except (httpx.HTTPError, KeyError, TypeError, ValueError, ValidationError, json.JSONDecodeError) as exc:
            first_error = str(exc)

    question_number = adaptive_answer_count + 1
    return AdaptiveGenerationResult(
        hidden_state=current_state,
        next_step=fallback_step(question_number),
        should_complete=False,
        metadata=_metadata("fallback", first_error or "openrouter_generation_failed", attempts=2, degraded=True),
    )


def _call_openrouter(
    participant: ParticipantToken,
    events: list[RawEvent],
    current_state: dict[str, Any],
    last_step: dict[str, Any] | None,
    last_answer: dict[str, Any] | None,
    adaptive_answer_count: int,
    repair_error: str | None,
) -> dict[str, Any]:
    settings = get_settings()
    url = f"{settings.openrouter_base_url.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.openrouter_api_key}",
        "HTTP-Referer": settings.openrouter_site_url,
        "X-Title": settings.openrouter_app_name,
        "Content-Type": "application/json",
    }
    messages = [
        {"role": "system", "content": _system_prompt()},
        {
            "role": "user",
            "content": json.dumps(
                {
                    "model_profile_context": build_model_profile_context(participant),
                    "current_hidden_state": current_state,
                    "adaptive_answers_so_far": adaptive_answer_count,
                    "max_questions": MAX_ADAPTIVE_QUESTIONS,
                    "recent_answer_history": _history_summary(events),
                    "last_step": last_step,
                    "last_answer": last_answer,
                    "repair_previous_error": repair_error,
                },
                ensure_ascii=True,
            ),
        },
    ]
    request_body = {
        "model": settings.openrouter_model,
        "messages": messages,
        "temperature": 0.4,
        "response_format": {"type": "json_object"},
    }
    with httpx.Client(timeout=30.0) as client:
        response = client.post(url, headers=headers, json=request_body)
        response.raise_for_status()
        data = response.json()

    content = data["choices"][0]["message"]["content"]
    return json.loads(_strip_json_wrapper(content))


def _call_context_flip_openrouter(
    participant: ParticipantToken,
    events: list[RawEvent],
    current_state: dict[str, Any],
    replay_index: int,
    adaptive_answer_count: int,
    repair_error: str | None,
) -> dict[str, Any]:
    user = json.dumps(
        {
            "model_profile_context": build_model_profile_context(participant),
            "current_hidden_state": current_state,
            "adaptive_answers_so_far": adaptive_answer_count,
            "replay_index": replay_index,
            "max_replay_scenarios": REPLAY_SCENARIO_COUNT,
            "recent_answer_history": _replay_history_summary(events),
            "repair_previous_error": repair_error,
            "required_shape": {
                "type": "context_flip",
                "title": "Short title",
                "prompt": "Open-ended replay prompt that flips one meaningful context variable.",
                "context_title": "Optional context heading",
                "context_items": ["Optional short context line"],
            },
        },
        ensure_ascii=True,
    )
    return _openrouter_json_payload(_context_flip_system_prompt(), user, temperature=0.5)


def _call_twin_rank_openrouter(
    participant: ParticipantToken,
    events: list[RawEvent],
    current_state: dict[str, Any],
    context_event: RawEvent,
    replay_index: int,
    repair_error: str | None,
) -> dict[str, Any]:
    context_payload = context_event.payload if isinstance(context_event.payload, dict) else {}
    context_answer = context_payload.get("answer", {}) if isinstance(context_payload.get("answer"), dict) else {}
    context_step = context_payload.get("step_snapshot", {}) if isinstance(context_payload.get("step_snapshot"), dict) else {}
    user = json.dumps(
        {
            "model_profile_context": build_model_profile_context(participant),
            "current_hidden_state": current_state,
            "replay_index": replay_index,
            "context_flip_prompt": context_step.get("prompt"),
            "context_flip_answer": context_answer.get("text"),
            "recent_answer_history": _replay_history_summary(events),
            "repair_previous_error": repair_error,
            "required_shape": {
                "type": "twin_rank",
                "title": "Short title",
                "prompt": "Ask the user to rank which preliminary twin response is closest.",
                "options": ["Twin response 1", "Twin response 2", "Twin response 3"],
                "context_title": "Optional context heading",
                "context_items": ["Optional short context line"],
            },
        },
        ensure_ascii=True,
    )
    return _openrouter_json_payload(_twin_rank_system_prompt(), user, temperature=0.55)


def _openrouter_json_payload(system: str, user: str, temperature: float) -> dict[str, Any]:
    settings = get_settings()
    url = f"{settings.openrouter_base_url.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.openrouter_api_key}",
        "HTTP-Referer": settings.openrouter_site_url,
        "X-Title": settings.openrouter_app_name,
        "Content-Type": "application/json",
    }
    request_body = {
        "model": settings.openrouter_model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
        "response_format": {"type": "json_object"},
    }
    with httpx.Client(timeout=30.0) as client:
        response = client.post(url, headers=headers, json=request_body)
        response.raise_for_status()
        data = response.json()

    return json.loads(_strip_json_wrapper(str(data["choices"][0]["message"]["content"])))


def _system_prompt() -> str:
    return """
You generate one adaptive psychometric scenario question at a time.
Return one JSON object only. Do not use markdown.

The backend controls IDs, stop rules, and scoring, so do not include an id.
Allowed next_step types:
- triad: exactly 3 options. Option index 0 measures risk to people / user impact. Option index 1 measures speed of execution / quick mitigation. Option index 2 measures long-term architectural stability / rules / quality.
- duel: exactly 2 options. Option index 0 measures protect quality / guardrails even if execution slows. Option index 1 measures ship fast / iterate and improve details later.

The JSON object must have:
{
  "hidden_state": {"confidence": 0.0, "axis_scores": {}, "signals": []},
  "confidence": 0.0,
  "should_complete": false,
  "next_step": {"type": "triad", "title": "...", "prompt": "...", "options": ["...", "...", "..."]}
}

Use the user profile and prior answers to make the next situation concrete and domain-specific. Keep options comparable in length and avoid asking for personal secrets.
""".strip()


def _context_flip_system_prompt() -> str:
    return """
You generate one open-ended replay scenario for a digital twin onboarding flow.
Return one JSON object only. Do not use markdown.

Create a concrete replay of a recent choice pattern, then flip exactly one context variable such as audience, public visibility, reversibility, time pressure, team impact, or accountability.
The user should answer in a few sentences, not choose from options.
Do not ask for secrets, protected traits, credentials, or unnecessary sensitive details.
""".strip()


def _twin_rank_system_prompt() -> str:
    return f"""
You generate preliminary digital-twin response candidates after an open-ended context-flip answer.
Return one JSON object only. Do not use markdown.

Create exactly {TWIN_RESPONSES_PER_REPLAY} distinct candidate twin responses. Each option should be a concise first-person reasoning response that might plausibly match the user, while staying uncertain and corrigible.
The options should differ in decision policy, not just wording.
Do not claim to know the user with certainty.
""".strip()


def _context_flip_step(raw_step: dict[str, Any], replay_index: int) -> dict[str, Any]:
    return {
        "id": f"context_flip_{replay_index}",
        "type": "context_flip",
        "title": _string_or_default(raw_step.get("title"), f"Replay {replay_index}: Context Flip"),
        "prompt": _string_or_default(raw_step.get("prompt"), _fallback_context_prompt(replay_index)),
        "context_title": _optional_string(raw_step.get("context_title")) or "Replay context",
        "context_items": _string_list(raw_step.get("context_items"), limit=4),
        "replay_scenario_id": f"replay_{replay_index}",
        "replay_index": replay_index,
    }


def _twin_rank_step(raw_step: dict[str, Any], context_event: RawEvent, replay_index: int) -> dict[str, Any]:
    default_options = [
        "I would keep my original priority, but narrow the action so the flipped context does not create avoidable risk.",
        "I would change course because the flipped context changes who absorbs the cost and what I am accountable for.",
        "I would pause for one more concrete signal, then choose the path that stays reversible and easiest to explain.",
    ]
    options = _string_list(raw_step.get("options"), limit=TWIN_RESPONSES_PER_REPLAY)
    if len(options) != TWIN_RESPONSES_PER_REPLAY:
        options = default_options
    return {
        "id": f"twin_rank_{replay_index}",
        "type": "twin_rank",
        "title": _string_or_default(raw_step.get("title"), f"Replay {replay_index}: Twin Responses"),
        "prompt": _string_or_default(raw_step.get("prompt"), "Rank which preliminary twin response sounds closest to your reasoning."),
        "options": options,
        "context_title": _optional_string(raw_step.get("context_title")) or "Context flip answer",
        "context_items": _string_list(raw_step.get("context_items"), limit=4) or _context_items_from_event(context_event),
        "replay_scenario_id": f"replay_{replay_index}",
        "replay_index": replay_index,
        "source_context_step_id": _step_id_from_event(context_event),
    }


def _fallback_context_flip_step(participant: ParticipantToken, events: list[RawEvent], replay_index: int) -> dict[str, Any]:
    latest_choice = _latest_choice_event(events)
    context_items: list[str] = []
    prompt = _fallback_context_prompt(replay_index)
    if latest_choice is not None:
        step = _step_snapshot(latest_choice)
        answer = _answer(latest_choice)
        selected = _optional_string(answer.get("selected_option"))
        original_prompt = _optional_string(step.get("prompt"))
        if original_prompt:
            context_items.append(f"Original situation: {original_prompt}")
        if selected:
            context_items.append(f"Earlier answer: {selected}")
            flip = "only affected you instead of a team" if replay_index == 1 else "became visible to people who depend on the outcome"
            prompt = (
                f"Replay that decision with one context flip: imagine the same situation {flip}. "
                "Would your choice change, and what detail would decide it?"
            )
    else:
        profile = build_model_profile_context(participant)
        if profile:
            context_items.append(f"Profile signal: {profile[:180]}")

    return _context_flip_step(
        {
            "title": f"Replay {replay_index}: Context Flip",
            "prompt": prompt,
            "context_title": "Earlier signal",
            "context_items": context_items,
        },
        replay_index,
    )


def _fallback_twin_rank_step(
    participant: ParticipantToken | None,
    events: list[RawEvent],
    context_event: RawEvent,
    replay_index: int,
) -> dict[str, Any]:
    return _twin_rank_step(
        {
            "title": f"Replay {replay_index}: Twin Responses",
            "prompt": "Rank which preliminary twin response sounds closest to your reasoning.",
            "options": [
                "I would keep my original priority, but narrow the action so the flipped context does not create avoidable risk.",
                "I would change course because the flipped context changes who absorbs the cost and what I am accountable for.",
                "I would pause for one more concrete signal, then choose the path that stays reversible and easiest to explain.",
            ],
            "context_title": "Context flip answer",
            "context_items": _context_items_from_event(context_event),
        },
        context_event,
        replay_index,
    )


def _fallback_context_prompt(replay_index: int) -> str:
    if replay_index == 1:
        return "Replay a recent decision pattern with this context flip: the outcome affects only you, not a team. Would your answer change, and why?"
    return "Replay a recent decision pattern with this context flip: the outcome becomes public to people who rely on you. Would your answer change, and why?"


def _context_items_from_event(event: RawEvent) -> list[str]:
    context_answer = _optional_string(_answer(event).get("text")) or "the context flip changes the decision boundary"
    context_prompt = _optional_string(_step_snapshot(event).get("prompt"))
    items = [f"Your context-flip answer: {context_answer[:240]}"]
    if context_prompt:
        items.insert(0, f"Replay prompt: {context_prompt}")
    return items[:4]


def _latest_choice_event(events: list[RawEvent]) -> RawEvent | None:
    for event in reversed(events):
        payload = event.payload if isinstance(event.payload, dict) else {}
        if payload.get("step_type") in {"triad", "duel"}:
            return event
    return None


def _step_snapshot(event: RawEvent) -> dict[str, Any]:
    payload = event.payload if isinstance(event.payload, dict) else {}
    step = payload.get("step_snapshot")
    return step if isinstance(step, dict) else {}


def _answer(event: RawEvent) -> dict[str, Any]:
    payload = event.payload if isinstance(event.payload, dict) else {}
    answer = payload.get("answer")
    return answer if isinstance(answer, dict) else {}


def _step_id_from_event(event: RawEvent) -> str | None:
    payload = event.payload if isinstance(event.payload, dict) else {}
    step_id = payload.get("step_id")
    return str(step_id) if step_id else None


def _string_or_default(value: Any, default: str) -> str:
    cleaned = _optional_string(value)
    return cleaned or default


def _optional_string(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _string_list(value: Any, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    cleaned: list[str] = []
    for item in value:
        text = _optional_string(item)
        if text:
            cleaned.append(text[:900])
        if len(cleaned) >= limit:
            break
    return cleaned


def _replay_history_summary(events: list[RawEvent]) -> list[dict[str, Any]]:
    summary: list[dict[str, Any]] = []
    for event in events[-14:]:
        payload = event.payload if isinstance(event.payload, dict) else {}
        answer = payload.get("answer", {})
        step = payload.get("step_snapshot") or {}
        step_type = payload.get("step_type")
        if step_type not in {"triad", "duel", "context_flip", "twin_rank"}:
            continue
        answer_summary: dict[str, Any] = {}
        if isinstance(answer, dict):
            for key in ("selected_index", "selected_option", "text", "ranked_options", "rejected_options", "correction_text"):
                if key in answer:
                    answer_summary[key] = answer[key]
        summary.append(
            {
                "step_id": payload.get("step_id"),
                "step_type": step_type,
                "prompt": step.get("prompt") if isinstance(step, dict) else None,
                "answer": answer_summary,
            }
        )
    return summary


def _state_with_local_signal(
    state: dict[str, Any],
    last_step: dict[str, Any] | None,
    last_answer: dict[str, Any] | None,
    adaptive_answer_count: int,
) -> dict[str, Any]:
    normalized = _normalize_hidden_state(state, fallback=initial_adaptive_state())
    if not last_step or not last_answer:
        return normalized

    selected_index = last_answer.get("selected_index")
    if not isinstance(selected_index, int):
        return normalized

    axis = trait_axis_for_choice(str(last_step.get("type")), selected_index)
    if axis is None:
        return normalized

    axis_scores = normalized.setdefault("axis_scores", {})
    axis_scores[axis] = int(axis_scores.get(axis, 0)) + 1
    signals = normalized.setdefault("signals", [])
    if isinstance(signals, list):
        signals.append(
            {
                "step_id": last_step.get("id"),
                "step_type": last_step.get("type"),
                "selected_index": selected_index,
                "axis": axis,
            }
        )
        normalized["signals"] = signals[-12:]
    normalized["confidence"] = max(_confidence(normalized), min(0.95, adaptive_answer_count * 0.14))
    return normalized


def _normalize_hidden_state(state: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(fallback)
    if isinstance(state, dict):
        normalized.update(state)
    normalized["confidence"] = _confidence(normalized)
    if not isinstance(normalized.get("axis_scores"), dict):
        normalized["axis_scores"] = {}
    if not isinstance(normalized.get("signals"), list):
        normalized["signals"] = []
    return normalized


def _confidence(state: dict[str, Any]) -> float:
    try:
        return max(0.0, min(1.0, float(state.get("confidence", 0.0))))
    except (TypeError, ValueError):
        return 0.0


def _history_summary(events: list[RawEvent]) -> list[dict[str, Any]]:
    summary: list[dict[str, Any]] = []
    for event in events[-10:]:
        payload = event.payload if isinstance(event.payload, dict) else {}
        answer = payload.get("answer", {})
        step = payload.get("step_snapshot") or {}
        if payload.get("step_type") not in {"triad", "duel"}:
            continue
        summary.append(
            {
                "step_id": payload.get("step_id"),
                "step_type": payload.get("step_type"),
                "prompt": step.get("prompt"),
                "selected_index": answer.get("selected_index") if isinstance(answer, dict) else None,
                "selected_option": answer.get("selected_option") if isinstance(answer, dict) else None,
            }
        )
    return summary


def _strip_json_wrapper(content: str) -> str:
    stripped = content.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`").strip()
        if stripped.startswith("json"):
            stripped = stripped[4:].strip()
    return stripped


def _metadata(
    status: str,
    reason: str | None,
    attempts: int = 0,
    degraded: bool = False,
) -> dict[str, Any]:
    return {
        "status": status,
        "reason": reason,
        "attempts": attempts,
        "degraded": degraded,
        "updated_at": now_utc().isoformat(),
    }


def _step_metadata(
    status: str,
    reason: str | None,
    step_type: str,
    replay_index: int,
    attempts: int = 0,
    degraded: bool = False,
) -> dict[str, Any]:
    metadata = _metadata(status, reason, attempts=attempts, degraded=degraded)
    metadata.update(
        {
            "step_type": step_type,
            "replay_scenario_id": f"replay_{replay_index}",
            "replay_index": replay_index,
        }
    )
    return metadata
