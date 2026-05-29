from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal, Protocol

import httpx
from pydantic import BaseModel, Field, ValidationError, model_validator

from app.config import get_settings
from app.models import ParticipantToken, RawEvent, now_utc
from app.services.profile_service import build_model_profile_context


ACPDomain = Literal["medical_care", "daily_living", "support_network", "worries_concerns", "proxy_guidance", "legacy"]
LifeState = Literal["well", "unwell", "loss_of_capacity", "after_death"]


class ACPCouncilCandidate(BaseModel):
    type: Literal["triad", "duel"]
    title: str = Field(min_length=1, max_length=160)
    prompt: str = Field(min_length=1, max_length=800)
    options: list[str] = Field(min_length=2, max_length=3)
    acp_domain: ACPDomain
    life_state: LifeState
    signal_goal: str = Field(min_length=1, max_length=300)
    singapore_context_notes: list[str] = Field(default_factory=list, max_length=5)

    @model_validator(mode="after")
    def validate_options(self) -> "ACPCouncilCandidate":
        expected_count = 2 if self.type == "duel" else 3
        if len(self.options) != expected_count:
            raise ValueError(f"{self.type} steps must include exactly {expected_count} options")
        cleaned = [option.strip() for option in self.options if option.strip()]
        if len(cleaned) != expected_count:
            raise ValueError("Options must be non-empty strings")
        if len(set(cleaned)) != expected_count:
            raise ValueError("Options must be distinct")
        self.options = cleaned
        return self


class ACPCouncilChairPayload(BaseModel):
    selected_step: ACPCouncilCandidate | None = None
    rationale: str = Field(default="", max_length=500)
    cultural_sensitivity_flags: list[str] = Field(default_factory=list, max_length=8)


class ACPCouncilJSONClient(Protocol):
    def request_json(self, model: str, system: str, user: str, temperature: float, timeout_seconds: float) -> dict[str, Any]:
        """Return parsed JSON from the given model."""


@dataclass(frozen=True)
class ACPCouncilGenerationResult:
    hidden_state: dict[str, Any]
    next_step: dict[str, Any] | None
    should_complete: bool
    metadata: dict[str, Any]


class OpenRouterCouncilClient:
    def request_json(self, model: str, system: str, user: str, temperature: float, timeout_seconds: float) -> dict[str, Any]:
        settings = get_settings()
        request_body = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "response_format": {"type": "json_object"},
        }
        url = f"{settings.openrouter_base_url.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {settings.openrouter_api_key}",
            "HTTP-Referer": settings.openrouter_site_url,
            "X-Title": settings.openrouter_app_name,
            "Content-Type": "application/json",
        }
        with httpx.Client(timeout=timeout_seconds) as client:
            response = client.post(url, headers=headers, json=request_body)
            response.raise_for_status()
            data = response.json()
        content = data["choices"][0]["message"]["content"]
        return json.loads(_strip_json_wrapper(str(content)))


def council_configured(settings: Any | None = None) -> bool:
    settings = settings or get_settings()
    return bool(_model_list(getattr(settings, "openrouter_acp_council_models", "")))


def generate_acp_council_step(
    participant: ParticipantToken,
    events: list[RawEvent],
    current_state: dict[str, Any],
    adaptive_answer_count: int,
    *,
    client: ACPCouncilJSONClient | None = None,
    settings: Any | None = None,
) -> ACPCouncilGenerationResult:
    settings = settings or get_settings()
    models = _model_list(getattr(settings, "openrouter_acp_council_models", ""))
    min_successes = max(1, int(getattr(settings, "openrouter_acp_council_min_successes", 3) or 3))
    timeout_seconds = float(getattr(settings, "openrouter_acp_council_timeout_seconds", 35.0) or 35.0)
    chair_model = str(getattr(settings, "openrouter_acp_chair_model", "") or "").strip() or str(getattr(settings, "openrouter_model", "")).strip()
    metadata_base = _metadata_base(models, min_successes, chair_model)

    if len(models) < min_successes:
        return _failure(current_state, metadata_base, "not_enough_distinct_configured_models")
    if not getattr(settings, "has_openrouter_key", False):
        return _failure(current_state, metadata_base, "openrouter_not_configured")

    active_client = client or OpenRouterCouncilClient()
    user_payload = _council_user_payload(participant, events, current_state, adaptive_answer_count)
    successes: list[tuple[str, ACPCouncilCandidate]] = []
    failures: list[dict[str, str]] = []

    for model in models:
        try:
            payload = active_client.request_json(
                model=model,
                system=_candidate_system_prompt(),
                user=user_payload,
                temperature=0.45,
                timeout_seconds=timeout_seconds,
            )
            candidate = _candidate_from_payload(payload)
            successes.append((model, candidate))
        except (httpx.HTTPError, KeyError, TypeError, ValueError, ValidationError, json.JSONDecodeError) as exc:
            failures.append({"model": model, "error": str(exc)[:500]})

    if len(successes) < min_successes:
        metadata = {
            **metadata_base,
            "status": "council_failed",
            "reason": "insufficient_successful_council_models",
            "council_models_successful": [model for model, _candidate in successes],
            "council_models_failed": failures,
            "successful_count": len(successes),
            "degraded": True,
            "updated_at": now_utc().isoformat(),
        }
        return ACPCouncilGenerationResult(current_state, None, False, metadata)

    selected = successes[0][1]
    chair_status = "not_configured"
    chair_rationale = ""
    cultural_flags: list[str] = []
    if chair_model:
        try:
            chair_payload = active_client.request_json(
                model=chair_model,
                system=_chair_system_prompt(),
                user=_chair_user_payload(user_payload, successes),
                temperature=0.2,
                timeout_seconds=timeout_seconds,
            )
            parsed = _chair_from_payload(chair_payload)
            if parsed.selected_step is not None:
                selected = parsed.selected_step
                chair_status = "selected"
            else:
                chair_status = "fallback_candidate"
            chair_rationale = parsed.rationale
            cultural_flags = parsed.cultural_sensitivity_flags
        except (httpx.HTTPError, KeyError, TypeError, ValueError, ValidationError, json.JSONDecodeError) as exc:
            chair_status = "fallback_candidate"
            chair_rationale = f"Chair synthesis failed validation: {str(exc)[:240]}"

    next_step = {
        **selected.model_dump(),
        "generation_source": "acp_council",
        "council_models_successful": [model for model, _candidate in successes],
        "council_models_failed": failures,
        "council_min_successes": min_successes,
        "council_chair_model": chair_model,
        "council_chair_status": chair_status,
        "council_chair_rationale": chair_rationale,
        "cultural_sensitivity_flags": cultural_flags,
    }
    metadata = {
        **metadata_base,
        "status": "generated",
        "reason": None,
        "degraded": False,
        "successful_count": len(successes),
        "council_models_successful": [model for model, _candidate in successes],
        "council_models_failed": failures,
        "acp_domain": selected.acp_domain,
        "life_state": selected.life_state,
        "signal_goal": selected.signal_goal,
        "singapore_context_notes": selected.singapore_context_notes,
        "council_chair_status": chair_status,
        "council_chair_rationale": chair_rationale,
        "cultural_sensitivity_flags": cultural_flags,
        "updated_at": now_utc().isoformat(),
    }
    return ACPCouncilGenerationResult(current_state, next_step, False, metadata)


def _metadata_base(models: list[str], min_successes: int, chair_model: str) -> dict[str, Any]:
    return {
        "generation_source": "acp_council",
        "attempted_models": models,
        "council_min_successes": min_successes,
        "council_chair_model": chair_model,
    }


def _failure(current_state: dict[str, Any], metadata_base: dict[str, Any], reason: str) -> ACPCouncilGenerationResult:
    metadata = {
        **metadata_base,
        "status": "council_failed",
        "reason": reason,
        "degraded": True,
        "council_models_successful": [],
        "council_models_failed": [],
        "successful_count": 0,
        "updated_at": now_utc().isoformat(),
    }
    return ACPCouncilGenerationResult(current_state, None, False, metadata)


def _candidate_from_payload(payload: dict[str, Any]) -> ACPCouncilCandidate:
    raw = payload.get("candidate") if isinstance(payload.get("candidate"), dict) else payload
    return ACPCouncilCandidate.model_validate(raw)


def _chair_from_payload(payload: dict[str, Any]) -> ACPCouncilChairPayload:
    if isinstance(payload.get("selected_step"), dict):
        return ACPCouncilChairPayload.model_validate(payload)
    return ACPCouncilChairPayload(selected_step=ACPCouncilCandidate.model_validate(payload))


def _model_list(value: str) -> list[str]:
    seen: set[str] = set()
    models: list[str] = []
    for item in value.split(","):
        model = item.strip()
        if model and model not in seen:
            seen.add(model)
            models.append(model)
    return models


def _council_user_payload(
    participant: ParticipantToken,
    events: list[RawEvent],
    current_state: dict[str, Any],
    adaptive_answer_count: int,
) -> str:
    payload = {
        "participant_context": build_model_profile_context(participant) or participant.user_profile or participant.label,
        "current_hidden_state": current_state,
        "adaptive_answers_so_far": adaptive_answer_count,
        "recent_answer_history": _history_summary(events),
        "scenario": {
            "participant": "Liying-style ACP calibration participant",
            "context": "Singapore, older-age planning, wealthy couple, no children, spouse likely present as trusted proxy.",
            "goal": "Generate one humane ACP-informed forced-choice probe that helps a future proxy understand the participant's values.",
        },
        "required_shape": {
            "type": "triad or duel",
            "title": "Short title",
            "prompt": "One concrete question",
            "options": ["Comparable answer option"],
            "acp_domain": "medical_care | daily_living | support_network | worries_concerns | proxy_guidance | legacy",
            "life_state": "well | unwell | loss_of_capacity | after_death",
            "signal_goal": "What preference signal this tests",
            "singapore_context_notes": ["Bias or cultural fit note"],
        },
    }
    return json.dumps(payload, ensure_ascii=True)


def _chair_user_payload(original_user_payload: str, successes: list[tuple[str, ACPCouncilCandidate]]) -> str:
    return json.dumps(
        {
            "original_request": json.loads(original_user_payload),
            "candidates": [
                {
                    "model": model,
                    "candidate": candidate.model_dump(),
                }
                for model, candidate in successes
            ],
            "required_shape": {
                "selected_step": "One validated candidate shape",
                "rationale": "Why this probe was selected",
                "cultural_sensitivity_flags": ["Any remaining caution"],
            },
        },
        ensure_ascii=True,
    )


def _candidate_system_prompt() -> str:
    return """
You are one member of a multi-model ACP probe council for a Singapore digital-twin calibration session.
Return exactly one JSON object and no markdown.

Generate one forced-choice probe for a participant like Liying: a wealthy Singapore-based donor planning for aging, possible loss of capacity, and spouse-as-proxy decision support. Do not assume children exist. Avoid legal or clinical advice. Keep the wording humane, concrete, and culturally aware.

The probe must test values that a future proxy would need: care preferences, daily living, support network, worries, proxy guidance, or legacy. Options must be balanced, non-leading, and comparable in length.
""".strip()


def _chair_system_prompt() -> str:
    return """
You are the chair of a multi-model ACP probe council.
Return exactly one JSON object and no markdown.

Select or lightly revise one candidate. Prefer humane wording, Singapore-context fit, non-leading options, and usefulness for a future proxy. Reject questions that assume children, over-medicalize the participant, shame wealth, or turn ACP into legal advice.
""".strip()


def _history_summary(events: list[RawEvent]) -> list[dict[str, Any]]:
    summary: list[dict[str, Any]] = []
    for event in events[-10:]:
        payload = event.payload if isinstance(event.payload, dict) else {}
        step = payload.get("step_snapshot") if isinstance(payload.get("step_snapshot"), dict) else {}
        answer = payload.get("answer") if isinstance(payload.get("answer"), dict) else {}
        if payload.get("step_type") not in {"triad", "duel", "context_flip", "twin_rank", "correction"}:
            continue
        summary.append(
            {
                "step_id": payload.get("step_id"),
                "step_type": payload.get("step_type"),
                "prompt": step.get("prompt"),
                "answer": {
                    key: answer.get(key)
                    for key in ("selected_index", "selected_option", "text", "ranked_options", "correction_text")
                    if key in answer
                },
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
