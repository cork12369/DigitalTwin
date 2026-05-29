from __future__ import annotations

import hashlib
import json
import math
import re
import time
from typing import Any, Literal

import httpx
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import SessionLocal
from app.models import (
    ConfigEvent,
    ErrorCategory,
    ErrorReport,
    ExperimentVariant,
    MemoryCard,
    MemoryCardPillarLink,
    ParticipantToken,
    PendingSubagentEval,
    RawEvent,
    SubagentVerdict,
    now_utc,
)
from app.services.profile_service import build_model_profile_context
from app.services.training_service import PILLARS


CARD_TYPES = ("biographical", "disposition", "trigger", "stylistic", "competence", "relational")
V2_STEP_TYPES = ("triad", "duel", "context_flip", "correction", "twin_rank", "indifference", "chat_extract")
CALIBRATION_BANDS = ("unmeasured", "green", "amber", "red", "preliminary_green", "preliminary_amber", "preliminary_red")

DEFAULT_DELTA_W_MATRIX: dict[str, dict[str, float]] = {
    "triad": {"reinforce": 0.30, "contradict": 0.45},
    "duel": {"reinforce": 0.50, "contradict": 0.65},
    "context_flip": {"reinforce": 0.20, "contradict": 0.30},
    "correction": {"reinforce": 0.40, "contradict": 0.55},
    "twin_rank": {"reinforce": 0.35, "contradict": 0.50},
    "indifference": {"reinforce": 0.00, "contradict": 0.00},
    "chat_extract": {"reinforce": 0.15, "contradict": 0.20},
}

TYPE_RELEVANCE: dict[str, set[str]] = {
    "triad": {"disposition", "trigger"},
    "duel": {"disposition", "trigger", "competence"},
    "context_flip": {"trigger"},
    "correction": {"stylistic", "disposition"},
    "twin_rank": {"disposition", "trigger", "stylistic", "competence", "relational"},
    "chat_extract": {"disposition", "trigger", "stylistic", "competence", "relational"},
    "indifference": set(),
}

PROMPT_TEMPLATE_VERSION = "v2_subagent_verdict_v1"
PROMPT_TEMPLATE_HASH = hashlib.sha256(PROMPT_TEMPLATE_VERSION.encode("utf-8")).hexdigest()
LOW_CONFIDENCE_ABSTAIN_THRESHOLD = 0.40
MAX_MOVED_CARDS_PER_EVENT = 4


class SubagentVerdictPayload(BaseModel):
    card_id: str
    polarity: Literal["reinforce", "contradict", "abstain"]
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str = Field(default="", max_length=1200)
    spectrum_position: float | None = Field(default=None, ge=-1.0, le=1.0)


class SubagentResponsePayload(BaseModel):
    verdicts: list[SubagentVerdictPayload] = Field(default_factory=list)
    unanchored: bool = False
    unanchored_note: str | None = Field(default=None, max_length=1200)


def ensure_default_variant(db: Session) -> ExperimentVariant:
    settings = get_settings()
    model_id = settings.openrouter_subagent_model.strip() or "deepseek/deepseek-v4-pro"
    variant = (
        db.query(ExperimentVariant)
        .filter(
            ExperimentVariant.label == "v2_default",
            ExperimentVariant.prompt_template_hash == PROMPT_TEMPLATE_HASH,
            ExperimentVariant.subagent_model_id == model_id,
        )
        .first()
    )
    if variant is not None:
        return variant

    variant = ExperimentVariant(
        label="v2_default",
        delta_w_matrix=DEFAULT_DELTA_W_MATRIX,
        subagent_model_id=model_id,
        subagent_reasoning_effort=settings.openrouter_subagent_reasoning_effort.strip() or "high",
        compaction_model_id=settings.openrouter_compaction_model.strip() or model_id,
        prompt_template_hash=PROMPT_TEMPLATE_HASH,
        session_time_budget_seconds=3600,
        target_accuracy_band={"min": 0.70, "stretch": 0.80},
    )
    db.add(variant)
    db.flush()
    return variant


def activate_v2_token(db: Session, participant: ParticipantToken, changed_by: str = "admin") -> ParticipantToken:
    variant_before = participant.active_experiment_variant_id
    variant = ensure_default_variant(db)
    if not _cards_for_token(db, participant.id):
        preseed_cards(db, participant)

    participant.active_experiment_variant_id = variant.id
    participant.dynamic_flow_modifiers = {
        **(participant.dynamic_flow_modifiers or {}),
        "v2_enabled": True,
        "holdout_every_n": 5,
        "warmup_event_count": 3,
        "target_holdout_count": 10,
    }
    participant.calibration_band = "unmeasured"
    participant.calibration_ece = None
    participant.calibration_temperature = 1.0
    participant.session_time_budget_seconds = variant.session_time_budget_seconds
    db.add(
        ConfigEvent(
            token_id=participant.id,
            variant_id_before=variant_before,
            variant_id_after=variant.id,
            changed_by=changed_by,
        )
    )
    db.add(participant)
    db.flush()
    return participant


def preseed_cards(db: Session, participant: ParticipantToken) -> list[MemoryCard]:
    existing = (
        db.query(MemoryCard)
        .filter(MemoryCard.token_id == participant.id, MemoryCard.seed_source.in_(["profile", "cv"]))
        .order_by(MemoryCard.created_at.asc())
        .all()
    )
    if existing:
        return existing

    context = build_model_profile_context(participant) or participant.user_profile or participant.label
    compact_context = _clean_text(context)[:1200]
    seed_specs = [
        {
            "title": f"{participant.label} background context",
            "body": compact_context or "Known participant profile context for this calibration session.",
            "card_type": "biographical",
            "pillar_keys": [],
            "priority": "core",
        },
        {
            "title": "Decision framing from profile",
            "body": _profile_claim(compact_context, "They likely anchor decisions in the concrete context surfaced by their profile."),
            "card_type": "disposition",
            "pillar_keys": ["situation_framing"],
            "priority": "high",
        },
        {
            "title": "Available-option preference",
            "body": _profile_claim(compact_context, "They appear to prefer options that can be explained and acted on with clear trade-offs."),
            "card_type": "disposition",
            "pillar_keys": ["option_generation", "valuation_expectancies"],
            "priority": "medium",
        },
        {
            "title": "Competence signal from profile",
            "body": _profile_claim(compact_context, "Their profile suggests a repeatable working method that should shape technical or operational choices."),
            "card_type": "competence",
            "pillar_keys": ["option_generation"],
            "priority": "medium",
        },
        {
            "title": "Pressure boundary hypothesis",
            "body": _profile_claim(compact_context, "The calibration should test what changes their decision under visibility, time pressure, and reversibility shifts."),
            "card_type": "trigger",
            "pillar_keys": ["counterfactual_stress"],
            "priority": "medium",
        },
        {
            "title": "Feedback integration hypothesis",
            "body": _profile_claim(compact_context, "The calibration should watch how outcomes and critique update their future policy."),
            "card_type": "stylistic",
            "pillar_keys": ["feedback_integration"],
            "priority": "low",
        },
    ]

    cards: list[MemoryCard] = []
    for spec in seed_specs:
        card = MemoryCard(
            token_id=participant.id,
            title=spec["title"][:180],
            body=spec["body"][:1200],
            status="reviewed",
            priority=spec["priority"],
            card_type=spec["card_type"],
            seed_source=participant.profile_source_type or "profile",
            promoted_at=now_utc(),
            metadata_json={"source": "v2_preseed", "profile_context_hash": hashlib.sha256(compact_context.encode("utf-8")).hexdigest()[:16]},
        )
        db.add(card)
        db.flush()
        pillar_keys = [key for key in spec["pillar_keys"] if _valid_pillar_key(key)]
        weight = 1.0 / len(pillar_keys) if pillar_keys else 0.0
        for pillar_key in pillar_keys:
            db.add(MemoryCardPillarLink(card_id=card.id, pillar_key=pillar_key, weight=weight))
        cards.append(card)
    db.flush()
    return cards


def queue_subagent_eval_for_event(event_id: str) -> None:
    db = SessionLocal()
    try:
        event = db.get(RawEvent, event_id)
        if event is None:
            return
        participant = db.get(ParticipantToken, event.token_id)
        if participant is None or not participant.active_experiment_variant_id:
            return
        if event.holdout_slot:
            record_holdout_prediction(db, participant, event)
        else:
            evaluate_training_event(db, participant, event)
        db.commit()
    finally:
        db.close()


def evaluate_training_event(db: Session, participant: ParticipantToken, event: RawEvent) -> list[SubagentVerdict]:
    if db.query(SubagentVerdict).filter(SubagentVerdict.raw_event_id == event.id).first() is not None:
        return []
    if _effective_step_type(event) == "indifference":
        return []

    variant = participant.active_experiment_variant or ensure_default_variant(db)
    cards = relevant_cards_for_event(db, participant, event)
    if not cards:
        return []

    started = time.perf_counter()
    if get_settings().has_openrouter_key:
        try:
            payload = _call_subagent_with_repair(participant, event, cards, variant)
        except httpx.HTTPError as exc:
            _queue_pending_eval(db, participant, event, variant, str(exc))
            _log_error(db, participant.id, "subagent_provider_unavailable", str(exc), category=ErrorCategory.model_provider)
            return []
        except (ValidationError, ValueError, KeyError, json.JSONDecodeError) as exc:
            _log_error(db, participant.id, "subagent_malformed_response", str(exc), category=ErrorCategory.validation)
            payload = SubagentResponsePayload(verdicts=[], unanchored=True, unanchored_note="Malformed subagent response; abstained.")
    else:
        payload = _local_subagent_response(event, cards)

    latency_ms = int((time.perf_counter() - started) * 1000)
    return apply_subagent_response(db, participant, event, variant, payload, latency_ms)


def relevant_cards_for_event(db: Session, participant: ParticipantToken, event: RawEvent) -> list[MemoryCard]:
    step_type = _effective_step_type(event)
    relevant_types = TYPE_RELEVANCE.get(step_type, set())
    if not relevant_types:
        return []
    return (
        db.query(MemoryCard)
        .filter(MemoryCard.token_id == participant.id)
        .filter(MemoryCard.status.in_(["draft", "reviewed"]))
        .filter(MemoryCard.card_type.in_(sorted(relevant_types)))
        .order_by(MemoryCard.updated_at.desc())
        .limit(25)
        .all()
    )


def apply_subagent_response(
    db: Session,
    participant: ParticipantToken,
    event: RawEvent,
    variant: ExperimentVariant,
    payload: SubagentResponsePayload,
    latency_ms: int = 0,
) -> list[SubagentVerdict]:
    cards_by_id = {card.id: card for card in relevant_cards_for_event(db, participant, event)}
    normalized = _top_verdicts(payload.verdicts, cards_by_id)
    if len(payload.verdicts) > len(normalized):
        _log_error(
            db,
            participant.id,
            "subagent_verdict_overage",
            f"Subagent returned {len(payload.verdicts)} verdicts; kept top {len(normalized)}.",
            severity="warning",
        )

    rows: list[SubagentVerdict] = []
    matrix = variant.delta_w_matrix or DEFAULT_DELTA_W_MATRIX
    step_type = _effective_step_type(event)
    for item in normalized:
        card = cards_by_id.get(item.card_id)
        if card is None:
            continue
        delta = calculate_delta_w(
            step_type=step_type,
            polarity=item.polarity,
            confidence=item.confidence,
            matrix=matrix,
            spectrum_position=item.spectrum_position,
            card_type=card.card_type,
        )
        row = SubagentVerdict(
            raw_event_id=event.id,
            token_id=participant.id,
            variant_id=variant.id,
            card_id=card.id,
            polarity=item.polarity,
            confidence=item.confidence,
            spectrum_position=item.spectrum_position,
            delta_w_applied=delta,
            rationale=item.rationale,
            model_latency_ms=latency_ms,
        )
        db.add(row)
        rows.append(row)
        if delta:
            _apply_delta_to_card_links(db, card, event, delta)
            if item.polarity == "reinforce" and item.confidence >= 0.5:
                card.reinforcement_count = int(card.reinforcement_count or 0) + 1
                if card.status == "draft" and card.reinforcement_count >= 3:
                    card.status = "reviewed"
                    card.promoted_at = now_utc()
            card.updated_at = now_utc()
            db.add(card)

    if payload.unanchored:
        metadata = dict(event.payload or {})
        metadata["unanchored_note"] = payload.unanchored_note
        event.payload = metadata
        db.add(event)
    db.flush()
    return rows


def calculate_delta_w(
    step_type: str,
    polarity: str,
    confidence: float,
    matrix: dict[str, dict[str, float]] | None = None,
    spectrum_position: float | None = None,
    card_type: str | None = None,
) -> float:
    if card_type == "biographical":
        return 0.0
    if polarity == "abstain" or confidence < LOW_CONFIDENCE_ABSTAIN_THRESHOLD:
        return 0.0
    if step_type == "indifference":
        return 0.0

    config = matrix or DEFAULT_DELTA_W_MATRIX
    base = float(config.get(step_type, {}).get(polarity, 0.0))
    if base <= 0:
        return 0.0
    sign = 1.0 if polarity == "reinforce" else -1.0
    magnitude = 1.0
    if spectrum_position is not None:
        clipped = max(-1.0, min(1.0, float(spectrum_position)))
        magnitude = abs(clipped)
        if clipped < 0:
            sign *= -1.0
    return round(sign * base * max(0.0, min(1.0, confidence)) * magnitude, 6)


def record_holdout_prediction(db: Session, participant: ParticipantToken, event: RawEvent) -> dict[str, Any] | None:
    payload = dict(event.payload or {})
    if payload.get("holdout_prediction"):
        return payload["holdout_prediction"]
    step = payload.get("step_snapshot") if isinstance(payload.get("step_snapshot"), dict) else {}
    options = step.get("options") if isinstance(step.get("options"), list) else []
    if not options:
        return None

    distribution = predict_distribution_for_step(db, participant, step)
    actual_label = _actual_label_from_event(event)
    prediction = {
        "distribution": distribution,
        "actual_label": actual_label,
        "predicted_label": max(distribution, key=distribution.get) if distribution else None,
        "log_loss": _log_loss(distribution, actual_label),
    }
    payload["holdout_prediction"] = prediction
    event.payload = payload
    db.add(event)
    db.flush()
    return prediction


def predict_distribution_for_step(db: Session, participant: ParticipantToken, step: dict[str, Any]) -> dict[str, float]:
    options = [str(option) for option in (step.get("options") or []) if isinstance(option, str)]
    if not options:
        return {}
    cards = _cards_for_token(db, participant.id)
    scores = [0.0 for _ in options]
    for card in cards:
        if card.card_type == "biographical":
            continue
        card_text = f"{card.title} {card.body}"
        card_tokens = _tokens(card_text)
        card_weight = _card_current_weight(card)
        for index, option in enumerate(options):
            overlap = len(card_tokens.intersection(_tokens(option)))
            if overlap:
                scores[index] += min(1.5, 0.25 * overlap) * card_weight
    probabilities = _softmax(scores)
    return {str(index): round(probabilities[index], 6) for index in range(len(options))}


def finalize_calibration(db: Session, participant: ParticipantToken, preliminary: bool = False) -> dict[str, Any]:
    events = (
        db.query(RawEvent)
        .filter(RawEvent.token_id == participant.id, RawEvent.holdout_slot.is_(True))
        .order_by(RawEvent.created_at.asc())
        .all()
    )
    predictions: list[dict[str, Any]] = []
    for event in events:
        payload = dict(event.payload or {})
        prediction = payload.get("holdout_prediction")
        if not isinstance(prediction, dict):
            prediction = record_holdout_prediction(db, participant, event)
        if isinstance(prediction, dict) and prediction.get("actual_label") is not None:
            predictions.append(prediction)

    if not predictions:
        participant.calibration_band = "unmeasured"
        participant.calibration_ece = None
        participant.calibration_temperature = 1.0
        return {"band": "unmeasured", "accuracy": None, "brier": None, "ece": None, "temperature": 1.0}

    metrics = calibration_metrics(predictions)
    band = band_for_ece(metrics["ece"])
    temperature = 1.0
    if band == "red":
        temperature = fit_temperature(predictions)
        adjusted = [_temperature_adjusted_prediction(prediction, temperature) for prediction in predictions]
        adjusted_metrics = calibration_metrics(adjusted)
        if adjusted_metrics["ece"] < metrics["ece"]:
            metrics = adjusted_metrics
            band = band_for_ece(metrics["ece"])
    if preliminary and band in {"green", "amber", "red"}:
        band = f"preliminary_{band}"

    participant.calibration_band = band
    participant.calibration_ece = metrics["ece"]
    participant.calibration_temperature = temperature
    db.add(participant)
    db.flush()
    return {**metrics, "band": band, "temperature": temperature}


def calibration_metrics(predictions: list[dict[str, Any]]) -> dict[str, float]:
    usable = [item for item in predictions if isinstance(item.get("distribution"), dict) and item.get("actual_label") is not None]
    if not usable:
        return {"accuracy": 0.0, "brier": 0.0, "ece": 1.0}

    correct_count = 0
    brier_total = 0.0
    confidence_rows: list[tuple[float, bool]] = []
    for item in usable:
        distribution = {str(key): float(value) for key, value in item["distribution"].items()}
        actual = str(item["actual_label"])
        predicted = max(distribution, key=distribution.get)
        correct = predicted == actual
        correct_count += int(correct)
        labels = sorted(distribution)
        brier_total += sum((distribution[label] - (1.0 if label == actual else 0.0)) ** 2 for label in labels) / max(1, len(labels))
        confidence_rows.append((distribution[predicted], correct))

    return {
        "accuracy": round(correct_count / len(usable), 6),
        "brier": round(brier_total / len(usable), 6),
        "ece": round(_adaptive_ece(confidence_rows), 6),
    }


def band_for_ece(ece: float) -> str:
    if ece < 0.05:
        return "green"
    if ece < 0.10:
        return "amber"
    return "red"


def fit_temperature(predictions: list[dict[str, Any]]) -> float:
    candidates = [round(0.5 + index * 0.1, 2) for index in range(36)]
    best_t = 1.0
    best_nll = math.inf
    for temperature in candidates:
        adjusted = [_temperature_adjusted_prediction(item, temperature) for item in predictions]
        nll = sum(float(item.get("log_loss") or 0.0) for item in adjusted)
        if nll < best_nll:
            best_nll = nll
            best_t = temperature
    return best_t


def build_v2_state(db: Session, participant: ParticipantToken) -> dict[str, Any]:
    variant = participant.active_experiment_variant
    cards = _cards_for_token(db, participant.id)
    recent_verdicts = (
        db.query(SubagentVerdict)
        .filter(SubagentVerdict.token_id == participant.id)
        .order_by(SubagentVerdict.created_at.desc())
        .limit(25)
        .all()
    )
    event_count = db.query(RawEvent).filter(RawEvent.token_id == participant.id).count()
    holdout_count = db.query(RawEvent).filter(RawEvent.token_id == participant.id, RawEvent.holdout_slot.is_(True)).count()
    pending_count = (
        db.query(PendingSubagentEval)
        .filter(PendingSubagentEval.token_id == participant.id, PendingSubagentEval.processed_at.is_(None))
        .count()
    )
    return {
        "token_id": participant.id,
        "v2_enabled": bool(participant.active_experiment_variant_id),
        "calibration_band": participant.calibration_band,
        "calibration_ece": participant.calibration_ece,
        "calibration_temperature": participant.calibration_temperature,
        "active_variant": _variant_payload(variant) if variant else None,
        "event_counts": {
            "total": event_count,
            "holdout": holdout_count,
            "training": max(0, event_count - holdout_count),
            "pending_subagent": pending_count,
        },
        "cards": [_card_payload(card) for card in cards],
        "recent_verdicts": [_verdict_payload(row) for row in recent_verdicts],
    }


def _call_subagent_with_repair(
    participant: ParticipantToken,
    event: RawEvent,
    cards: list[MemoryCard],
    variant: ExperimentVariant,
) -> SubagentResponsePayload:
    first_error: str | None = None
    for attempt in (1, 2):
        payload = _call_subagent_openrouter(participant, event, cards, variant, repair_error=first_error)
        try:
            return SubagentResponsePayload.model_validate(payload)
        except ValidationError as exc:
            first_error = str(exc)
            if attempt == 2:
                raise
    raise ValueError("subagent response validation failed")


def _call_subagent_openrouter(
    participant: ParticipantToken,
    event: RawEvent,
    cards: list[MemoryCard],
    variant: ExperimentVariant,
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
    request_body = {
        "model": variant.subagent_model_id,
        "messages": [
            {"role": "system", "content": _subagent_system_prompt()},
            {"role": "user", "content": json.dumps(_subagent_user_payload(participant, event, cards, repair_error), ensure_ascii=True)},
        ],
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "reasoning": {"effort": variant.subagent_reasoning_effort or "high", "exclude": True},
    }
    with httpx.Client(timeout=8.0) as client:
        response = client.post(url, headers=headers, json=request_body)
        response.raise_for_status()
        data = response.json()
    return json.loads(_strip_json_wrapper(str(data["choices"][0]["message"]["content"])))


def _subagent_system_prompt() -> str:
    return """
You are an independent evaluator for a digital twin calibration session.
Return JSON only. Do not use markdown.
Score how the participant answer reinforces or contradicts the supplied memory cards.
Use abstain when the answer does not provide direct evidence for a card.
Biographical cards are grounding context only and should not receive updates.
""".strip()


def _subagent_user_payload(
    participant: ParticipantToken,
    event: RawEvent,
    cards: list[MemoryCard],
    repair_error: str | None,
) -> dict[str, Any]:
    payload = event.payload if isinstance(event.payload, dict) else {}
    return {
        "participant_context": build_model_profile_context(participant),
        "step_type": _effective_step_type(event),
        "answer_mode": event.answer_mode,
        "event": {
            "id": event.id,
            "payload": payload,
        },
        "candidate_cards": [
            {
                "card_id": card.id,
                "title": card.title,
                "body": card.body,
                "card_type": card.card_type,
                "pillar_links": [{"pillar_key": link.pillar_key, "weight": link.weight} for link in card.pillar_links],
            }
            for card in cards
        ],
        "required_shape": {
            "verdicts": [
                {
                    "card_id": "card uuid",
                    "polarity": "reinforce | contradict | abstain",
                    "confidence": 0.0,
                    "rationale": "Short audit rationale.",
                    "spectrum_position": None,
                }
            ],
            "unanchored": False,
            "unanchored_note": None,
        },
        "repair_previous_error": repair_error,
    }


def _local_subagent_response(event: RawEvent, cards: list[MemoryCard]) -> SubagentResponsePayload:
    answer_text = _event_text(event)
    answer_tokens = _tokens(answer_text)
    verdicts: list[SubagentVerdictPayload] = []
    for card in cards:
        card_tokens = _tokens(f"{card.title} {card.body}")
        overlap = len(answer_tokens.intersection(card_tokens))
        if overlap <= 0:
            continue
        negative = bool({"avoid", "reject", "not", "never", "less", "instead"}.intersection(answer_tokens))
        confidence = min(0.90, 0.42 + (overlap * 0.08))
        verdicts.append(
            SubagentVerdictPayload(
                card_id=card.id,
                polarity="contradict" if negative and overlap >= 2 else "reinforce",
                confidence=confidence,
                rationale=f"Local lexical overlap found {overlap} shared terms between answer and card.",
                spectrum_position=_local_spectrum_position(event, negative),
            )
        )

    if not verdicts and cards:
        card = cards[0]
        verdicts.append(
            SubagentVerdictPayload(
                card_id=card.id,
                polarity="reinforce",
                confidence=0.45,
                rationale="Local fallback applied a weak provisional update to keep lineage testable without an LLM key.",
                spectrum_position=_local_spectrum_position(event, False),
            )
        )
    return SubagentResponsePayload(verdicts=verdicts[:MAX_MOVED_CARDS_PER_EVENT], unanchored=not bool(verdicts))


def _local_spectrum_position(event: RawEvent, negative: bool) -> float | None:
    if event.answer_mode != "custom_text":
        return None
    return -0.6 if negative else 0.6


def _top_verdicts(verdicts: list[SubagentVerdictPayload], cards_by_id: dict[str, MemoryCard]) -> list[SubagentVerdictPayload]:
    seen: set[str] = set()
    filtered: list[SubagentVerdictPayload] = []
    for verdict in sorted(verdicts, key=lambda item: item.confidence, reverse=True):
        if verdict.card_id in seen or verdict.card_id not in cards_by_id:
            continue
        seen.add(verdict.card_id)
        filtered.append(verdict)
        if len(filtered) >= MAX_MOVED_CARDS_PER_EVENT:
            break
    return filtered


def _apply_delta_to_card_links(db: Session, card: MemoryCard, event: RawEvent, delta: float) -> None:
    if card.card_type == "biographical":
        return
    for link in card.pillar_links:
        link.cumulative_delta_w = round(float(link.cumulative_delta_w or 0.0) + delta, 6)
        link.weight = round(max(0.0, float(link.weight or 0.0) + delta), 6)
        link.update_count = int(link.update_count or 0) + 1
        link.source_event_id = event.id
        link.last_updated_at = now_utc()
        db.add(link)


def _queue_pending_eval(db: Session, participant: ParticipantToken, event: RawEvent, variant: ExperimentVariant, error: str) -> None:
    existing = (
        db.query(PendingSubagentEval)
        .filter(PendingSubagentEval.raw_event_id == event.id, PendingSubagentEval.processed_at.is_(None))
        .first()
    )
    if existing is not None:
        existing.attempts = int(existing.attempts or 0) + 1
        existing.last_error = error
        db.add(existing)
        return
    db.add(PendingSubagentEval(raw_event_id=event.id, token_id=participant.id, variant_id=variant.id, attempts=1, last_error=error))


def _log_error(
    db: Session,
    token_id: str | None,
    summary: str,
    raw_detail: str,
    category: ErrorCategory = ErrorCategory.infrastructure,
    severity: str = "error",
) -> None:
    db.add(ErrorReport(token_id=token_id, category=category, severity=severity, summary=summary, raw_detail=raw_detail[:4000]))


def _effective_step_type(event: RawEvent) -> str:
    if event.answer_mode == "indifferent":
        return "indifference"
    payload = event.payload if isinstance(event.payload, dict) else {}
    value = payload.get("step_type")
    if isinstance(value, str) and value in V2_STEP_TYPES:
        return value
    original = payload.get("original_step_type")
    if isinstance(original, str) and original in V2_STEP_TYPES:
        return original
    return "chat_extract" if event.answer_mode == "chat" else str(value or "triad")


def _actual_label_from_event(event: RawEvent) -> str | None:
    payload = event.payload if isinstance(event.payload, dict) else {}
    answer = payload.get("answer") if isinstance(payload.get("answer"), dict) else {}
    selected = answer.get("selected_index")
    if isinstance(selected, int):
        return str(selected)
    ranked = answer.get("ranked_options")
    step = payload.get("step_snapshot") if isinstance(payload.get("step_snapshot"), dict) else {}
    options = step.get("options") if isinstance(step.get("options"), list) else []
    if isinstance(ranked, list) and ranked:
        try:
            return str(options.index(ranked[0]))
        except ValueError:
            return None
    return None


def _event_text(event: RawEvent) -> str:
    payload = event.payload if isinstance(event.payload, dict) else {}
    step = payload.get("step_snapshot") if isinstance(payload.get("step_snapshot"), dict) else {}
    answer = payload.get("answer") if isinstance(payload.get("answer"), dict) else {}
    values: list[str] = []
    for key in ("title", "prompt"):
        if isinstance(step.get(key), str):
            values.append(step[key])
    for key in ("selected_option", "text", "correction_text"):
        if isinstance(answer.get(key), str):
            values.append(answer[key])
    for key in ("ranked_options", "rejected_options"):
        if isinstance(answer.get(key), list):
            values.extend(str(item) for item in answer[key])
    return " ".join(values)


def _cards_for_token(db: Session, token_id: str) -> list[MemoryCard]:
    return db.query(MemoryCard).filter(MemoryCard.token_id == token_id).order_by(MemoryCard.created_at.asc()).all()


def _card_current_weight(card: MemoryCard) -> float:
    if card.card_type == "biographical":
        return 0.0
    if not card.pillar_links:
        return 1.0
    return sum(max(0.0, float(link.weight or 0.0)) for link in card.pillar_links) / len(card.pillar_links)


def _profile_claim(context: str, fallback: str) -> str:
    sentence = _first_sentence(context)
    if sentence:
        return f"{fallback} Profile signal: {sentence}"
    return fallback


def _first_sentence(value: str) -> str:
    chunks = re.split(r"(?<=[.!?])\s+", value.strip())
    for chunk in chunks:
        cleaned = _clean_text(chunk)
        if len(cleaned) > 20:
            return cleaned[:260]
    return ""


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _valid_pillar_key(key: str) -> bool:
    return any(pillar["key"] == key for pillar in PILLARS)


def _tokens(value: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9]+", value.lower()) if len(token) > 2}


def _softmax(scores: list[float]) -> list[float]:
    if not scores:
        return []
    max_score = max(scores)
    weights = [math.exp(score - max_score) for score in scores]
    total = sum(weights) or 1.0
    return [weight / total for weight in weights]


def _log_loss(distribution: dict[str, float], actual_label: str | None) -> float | None:
    if actual_label is None:
        return None
    probability = max(1e-9, float(distribution.get(str(actual_label), 0.0)))
    return round(-math.log(probability), 6)


def _adaptive_ece(rows: list[tuple[float, bool]]) -> float:
    if not rows:
        return 1.0
    sorted_rows = sorted(rows, key=lambda item: item[0])
    bin_count = max(1, min(5, int(math.sqrt(len(sorted_rows))) or 1))
    bin_size = math.ceil(len(sorted_rows) / bin_count)
    ece = 0.0
    for start in range(0, len(sorted_rows), bin_size):
        bucket = sorted_rows[start : start + bin_size]
        if not bucket:
            continue
        avg_confidence = sum(item[0] for item in bucket) / len(bucket)
        avg_accuracy = sum(1.0 if item[1] else 0.0 for item in bucket) / len(bucket)
        ece += (len(bucket) / len(sorted_rows)) * abs(avg_accuracy - avg_confidence)
    return ece


def _temperature_adjusted_prediction(prediction: dict[str, Any], temperature: float) -> dict[str, Any]:
    distribution = {str(key): max(1e-9, float(value)) for key, value in dict(prediction.get("distribution") or {}).items()}
    if not distribution:
        return prediction
    inv_t = 1.0 / max(0.01, temperature)
    weights = {label: probability**inv_t for label, probability in distribution.items()}
    total = sum(weights.values()) or 1.0
    adjusted = {label: value / total for label, value in weights.items()}
    actual = prediction.get("actual_label")
    return {
        **prediction,
        "distribution": adjusted,
        "predicted_label": max(adjusted, key=adjusted.get),
        "log_loss": _log_loss(adjusted, str(actual) if actual is not None else None),
    }


def _variant_payload(variant: ExperimentVariant) -> dict[str, Any]:
    return {
        "id": variant.id,
        "label": variant.label,
        "delta_w_matrix": variant.delta_w_matrix,
        "subagent_model_id": variant.subagent_model_id,
        "subagent_reasoning_effort": variant.subagent_reasoning_effort,
        "prompt_template_hash": variant.prompt_template_hash,
        "session_time_budget_seconds": variant.session_time_budget_seconds,
        "target_accuracy_band": variant.target_accuracy_band,
        "created_at": variant.created_at,
    }


def _card_payload(card: MemoryCard) -> dict[str, Any]:
    return {
        "id": card.id,
        "title": card.title,
        "body": card.body,
        "status": card.status,
        "priority": card.priority,
        "card_type": card.card_type,
        "seed_source": card.seed_source,
        "reinforcement_count": card.reinforcement_count,
        "promoted_at": card.promoted_at,
        "current_weight": round(_card_current_weight(card), 6),
        "pillar_links": [
            {
                "id": link.id,
                "pillar_key": link.pillar_key,
                "weight": link.weight,
                "cumulative_delta_w": link.cumulative_delta_w,
                "update_count": link.update_count,
                "last_updated_at": link.last_updated_at,
            }
            for link in card.pillar_links
        ],
    }


def _verdict_payload(row: SubagentVerdict) -> dict[str, Any]:
    return {
        "id": row.id,
        "raw_event_id": row.raw_event_id,
        "card_id": row.card_id,
        "polarity": row.polarity,
        "confidence": row.confidence,
        "spectrum_position": row.spectrum_position,
        "delta_w_applied": row.delta_w_applied,
        "rationale": row.rationale,
        "model_latency_ms": row.model_latency_ms,
        "created_at": row.created_at,
    }


def _strip_json_wrapper(content: str) -> str:
    stripped = content.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`").strip()
        if stripped.startswith("json"):
            stripped = stripped[4:].strip()
    return stripped
