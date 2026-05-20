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
