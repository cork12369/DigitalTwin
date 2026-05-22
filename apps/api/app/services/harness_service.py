from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Protocol

import httpx
from sqlalchemy.orm import Session, selectinload

from app.config import get_settings
from app.database import SessionLocal
from app.models import (
    HarnessStatus,
    MemoryCard,
    ParticipantToken,
    RawEvent,
    TokenStatus,
    TwinHarnessCase,
    TwinHarnessRun,
    TwinHarnessScore,
    now_utc,
)
from app.services.profile_service import build_model_profile_context


PROMPT_VERSION = "harness_discrete_logprob_v1"
MAX_CASES = 3
MAX_SOURCES_PER_TYPE = 6
MAX_CONTEXT_CHARS = 5200
LOGPROB_FLOOR_DELTA = 20.0
POSITIVE_LIFT_THRESHOLD = 0.15
ZERO_LIFT_THRESHOLD = 0.05
NEGATIVE_LIFT_THRESHOLD = -0.15
HIGH_KL_THRESHOLD = 0.35
EPSILON = 1e-12


class UnsupportedLogprobsError(RuntimeError):
    """Raised when the configured model/provider cannot return usable label logprobs."""


class LogprobScorer(Protocol):
    model_name: str

    def score(self, prompt: str, labels: list[str]) -> dict[str, float]:
        """Return next-token logprobs keyed by action label."""


@dataclass(frozen=True)
class HarnessCaseCandidate:
    target_event_id: str
    target_step_id: str | None
    target_step_type: str
    replay_scenario_id: str | None
    human_target_label: str
    human_target_text: str
    candidate_actions: list[dict[str, str]]
    situation: str
    metadata: dict[str, Any]


@dataclass(frozen=True)
class HarnessSource:
    source_type: str
    source_id: str
    source_label: str
    text: str


class OpenRouterLogprobScorer:
    def __init__(self) -> None:
        settings = get_settings()
        self.settings = settings
        self.model_name = settings.openrouter_model
        if not settings.has_openrouter_key:
            raise UnsupportedLogprobsError(_unsupported_guidance("OpenRouter is not configured."))

    def score(self, prompt: str, labels: list[str]) -> dict[str, float]:
        request_body = {
            "model": self.model_name,
            "messages": [
                {
                    "role": "system",
                    "content": "You are a deterministic policy evaluator. Return exactly one uppercase action label.",
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0,
            "max_tokens": 1,
            "logprobs": True,
            "top_logprobs": 20,
        }
        settings = self.settings
        url = f"{settings.openrouter_base_url.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {settings.openrouter_api_key}",
            "HTTP-Referer": settings.openrouter_site_url,
            "X-Title": settings.openrouter_app_name,
            "Content-Type": "application/json",
        }
        try:
            with httpx.Client(timeout=45.0) as client:
                response = client.post(url, headers=headers, json=request_body)
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPError as exc:
            raise UnsupportedLogprobsError(_unsupported_guidance(f"Logprob request failed: {exc}")) from exc
        return _extract_label_logprobs(data, labels)


class FakeLogprobScorer:
    """Small deterministic adapter for local smoke tests and unit-level metric checks."""

    model_name = "fake-logprob-adapter"

    def score(self, prompt: str, labels: list[str]) -> dict[str, float]:
        preferred = "A"
        if "prefer_label=B" in prompt:
            preferred = "B"
        if "prefer_label=C" in prompt:
            preferred = "C"
        return {label: (-0.08 if label == preferred else -2.4 - index) for index, label in enumerate(labels)}


def queue_harness_run(db: Session, participant: ParticipantToken, trigger_reason: str) -> TwinHarnessRun | None:
    if not _participant_completed(participant):
        return None
    existing = (
        db.query(TwinHarnessRun)
        .filter(
            TwinHarnessRun.token_id == participant.id,
            TwinHarnessRun.status.in_([HarnessStatus.queued, HarnessStatus.running]),
        )
        .order_by(TwinHarnessRun.created_at.desc())
        .first()
    )
    if existing is not None:
        return existing
    run = TwinHarnessRun(
        token_id=participant.id,
        status=HarnessStatus.queued,
        trigger_reason=trigger_reason,
        model_name=get_settings().openrouter_model,
        prompt_version=PROMPT_VERSION,
        input_summary="Queued after a completed-token update.",
        aggregate_metrics={"queued_reason": trigger_reason},
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def run_harness_job(run_id: str) -> None:
    db = SessionLocal()
    try:
        run = db.get(TwinHarnessRun, run_id)
        if run is None or run.status not in {HarnessStatus.queued, HarnessStatus.failed}:
            return
        _execute_harness_run(db, run)
    finally:
        db.close()


def run_harness_for_token(
    db: Session,
    participant: ParticipantToken,
    trigger_reason: str = "manual_admin",
    scorer: LogprobScorer | None = None,
) -> TwinHarnessRun:
    run = TwinHarnessRun(
        token_id=participant.id,
        status=HarnessStatus.queued,
        trigger_reason=trigger_reason,
        model_name=(scorer.model_name if scorer is not None else get_settings().openrouter_model),
        prompt_version=PROMPT_VERSION,
        input_summary="Manual admin diagnostics harness run.",
        aggregate_metrics={},
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    _execute_harness_run(db, run, scorer=scorer)
    return get_harness_run(db, run.id) or run


def get_harness_run(db: Session, run_id: str) -> TwinHarnessRun | None:
    return (
        db.query(TwinHarnessRun)
        .options(selectinload(TwinHarnessRun.cases), selectinload(TwinHarnessRun.scores))
        .filter(TwinHarnessRun.id == run_id)
        .first()
    )


def information_gain_bits(lift_nats: float) -> float:
    return lift_nats / math.log(2)


def normalized_distribution(label_logprobs: dict[str, float]) -> dict[str, float]:
    if not label_logprobs:
        return {}
    max_logprob = max(label_logprobs.values())
    weights = {label: math.exp(logprob - max_logprob) for label, logprob in label_logprobs.items()}
    total = sum(weights.values()) or 1.0
    return {label: value / total for label, value in weights.items()}


def kl_divergence(conditioned: dict[str, float], baseline: dict[str, float]) -> float:
    total = 0.0
    for label, probability in conditioned.items():
        if probability <= 0:
            continue
        baseline_probability = max(EPSILON, baseline.get(label, EPSILON))
        total += probability * math.log(probability / baseline_probability)
    return total


def verdict_for(lift: float, kl_value: float) -> str:
    if lift <= NEGATIVE_LIFT_THRESHOLD:
        return "negative_drift"
    if abs(lift) <= ZERO_LIFT_THRESHOLD:
        if kl_value >= HIGH_KL_THRESHOLD:
            return "policy_displacement"
        return "zero_impact"
    if lift >= POSITIVE_LIFT_THRESHOLD:
        return "positive_lift"
    if kl_value >= HIGH_KL_THRESHOLD and lift <= ZERO_LIFT_THRESHOLD:
        return "policy_displacement"
    return "mixed"


def _execute_harness_run(db: Session, run: TwinHarnessRun, scorer: LogprobScorer | None = None) -> TwinHarnessRun:
    participant = db.get(ParticipantToken, run.token_id)
    if participant is None:
        run.status = HarnessStatus.failed
        run.error_summary = "Participant token was not found."
        run.completed_at = now_utc()
        db.commit()
        return run

    run.status = HarnessStatus.running
    run.started_at = now_utc()
    run.model_name = scorer.model_name if scorer is not None else get_settings().openrouter_model
    db.commit()

    try:
        if not _participant_completed(participant):
            run.status = HarnessStatus.skipped
            run.output_summary = "Harness skipped: participant token is not completed yet."
            run.aggregate_metrics = {"case_count": 0, "skipped_reason": "token_not_completed"}
            run.completed_at = now_utc()
            db.commit()
            return run

        case_candidates, skipped_targets = _build_case_candidates(db, participant)
        if not case_candidates:
            run.status = HarnessStatus.skipped
            run.output_summary = "Harness skipped: no held-out discrete action targets were available."
            run.aggregate_metrics = {
                "case_count": 0,
                "skipped_target_count": skipped_targets,
                "skipped_reason": "no_discrete_targets",
            }
            run.completed_at = now_utc()
            db.commit()
            return run

        memory_sources = _memory_sources(db, participant)
        questionnaire_sources = _questionnaire_sources(db, participant)
        run.input_summary = (
            f"{len(case_candidates)} held-out cases, {len(memory_sources)} reviewed memory cards, "
            f"{len(questionnaire_sources)} questionnaire signals."
        )
        db.commit()

        active_scorer = scorer or OpenRouterLogprobScorer()
        score_count = 0
        case_rows: list[TwinHarnessCase] = []
        for case_candidate in case_candidates:
            baseline_prompt = _build_prompt(participant, case_candidate, [])
            case_row = TwinHarnessCase(
                harness_run_id=run.id,
                token_id=participant.id,
                target_event_id=case_candidate.target_event_id,
                target_step_id=case_candidate.target_step_id,
                target_step_type=case_candidate.target_step_type,
                replay_scenario_id=case_candidate.replay_scenario_id,
                human_target_label=case_candidate.human_target_label,
                human_target_text=case_candidate.human_target_text,
                candidate_actions=case_candidate.candidate_actions,
                baseline_prompt=baseline_prompt,
                metadata_json=case_candidate.metadata,
            )
            db.add(case_row)
            db.flush()
            case_rows.append(case_row)

            labels = [action["label"] for action in case_candidate.candidate_actions]
            baseline_logprobs = active_scorer.score(baseline_prompt, labels)
            score_count += _score_isolated_sources(
                db=db,
                run=run,
                case=case_row,
                participant=participant,
                case_candidate=case_candidate,
                sources=memory_sources,
                source_type="memory_card",
                baseline_logprobs=baseline_logprobs,
                scorer=active_scorer,
            )
            score_count += _score_isolated_sources(
                db=db,
                run=run,
                case=case_row,
                participant=participant,
                case_candidate=case_candidate,
                sources=questionnaire_sources,
                source_type="question_event",
                baseline_logprobs=baseline_logprobs,
                scorer=active_scorer,
            )
            score_count += _score_marginal_sources(
                db=db,
                run=run,
                case=case_row,
                participant=participant,
                case_candidate=case_candidate,
                sources=memory_sources,
                source_type="memory_card",
                scorer=active_scorer,
            )
            score_count += _score_marginal_sources(
                db=db,
                run=run,
                case=case_row,
                participant=participant,
                case_candidate=case_candidate,
                sources=questionnaire_sources,
                source_type="question_event",
                scorer=active_scorer,
            )
            db.commit()

        run.status = HarnessStatus.completed
        run.output_summary = f"Scored {len(case_rows)} held-out cases and stored {score_count} source-effect scores."
        run.aggregate_metrics = _aggregate_scores(db, run.id, skipped_targets, len(memory_sources), len(questionnaire_sources))
        run.completed_at = now_utc()
        db.commit()
        db.refresh(run)
        return run
    except UnsupportedLogprobsError as exc:
        run.status = HarnessStatus.unsupported_model
        run.error_summary = str(exc)
        run.output_summary = "Harness could not score this model because label logprobs were unavailable."
        run.aggregate_metrics = {
            **(run.aggregate_metrics or {}),
            "case_count": db.query(TwinHarnessCase).filter(TwinHarnessCase.harness_run_id == run.id).count(),
            "score_count": 0,
            "unsupported_reason": str(exc),
        }
        run.completed_at = now_utc()
        db.commit()
        return run
    except Exception as exc:  # pragma: no cover - defensive background logging
        run.status = HarnessStatus.failed
        run.error_summary = str(exc)
        run.completed_at = now_utc()
        db.commit()
        return run


def _score_isolated_sources(
    db: Session,
    run: TwinHarnessRun,
    case: TwinHarnessCase,
    participant: ParticipantToken,
    case_candidate: HarnessCaseCandidate,
    sources: list[HarnessSource],
    source_type: str,
    baseline_logprobs: dict[str, float],
    scorer: LogprobScorer,
) -> int:
    count = 0
    labels = [action["label"] for action in case_candidate.candidate_actions]
    active_sources = _sources_without_target(sources, case_candidate)
    for source in active_sources:
        conditioned_prompt = _build_prompt(participant, case_candidate, [source])
        conditioned_logprobs = scorer.score(conditioned_prompt, labels)
        db.add(
            _score_row(
                run=run,
                case=case,
                source=source,
                source_type=source_type,
                metric_type="isolated_lift",
                base_logprobs=baseline_logprobs,
                conditioned_logprobs=conditioned_logprobs,
                target_label=case_candidate.human_target_label,
            )
        )
        count += 1
    return count


def _score_marginal_sources(
    db: Session,
    run: TwinHarnessRun,
    case: TwinHarnessCase,
    participant: ParticipantToken,
    case_candidate: HarnessCaseCandidate,
    sources: list[HarnessSource],
    source_type: str,
    scorer: LogprobScorer,
) -> int:
    active_sources = _sources_without_target(sources, case_candidate)
    if len(active_sources) < 2:
        return 0
    count = 0
    labels = [action["label"] for action in case_candidate.candidate_actions]
    all_prompt = _build_prompt(participant, case_candidate, active_sources)
    all_logprobs = scorer.score(all_prompt, labels)
    for source in active_sources:
        minus_sources = [item for item in active_sources if item.source_id != source.source_id]
        minus_prompt = _build_prompt(participant, case_candidate, minus_sources)
        minus_logprobs = scorer.score(minus_prompt, labels)
        db.add(
            _score_row(
                run=run,
                case=case,
                source=source,
                source_type=source_type,
                metric_type="marginal_ablation",
                base_logprobs=minus_logprobs,
                conditioned_logprobs=all_logprobs,
                target_label=case_candidate.human_target_label,
            )
        )
        count += 1
    return count


def _sources_without_target(sources: list[HarnessSource], case_candidate: HarnessCaseCandidate) -> list[HarnessSource]:
    return [source for source in sources if source.source_id != case_candidate.target_event_id]


def _score_row(
    run: TwinHarnessRun,
    case: TwinHarnessCase,
    source: HarnessSource,
    source_type: str,
    metric_type: str,
    base_logprobs: dict[str, float],
    conditioned_logprobs: dict[str, float],
    target_label: str,
) -> TwinHarnessScore:
    base_target = float(base_logprobs[target_label])
    conditioned_target = float(conditioned_logprobs[target_label])
    lift = conditioned_target - base_target
    base_distribution = normalized_distribution(base_logprobs)
    conditioned_distribution = normalized_distribution(conditioned_logprobs)
    kl_value = kl_divergence(conditioned_distribution, base_distribution)
    return TwinHarnessScore(
        harness_run_id=run.id,
        case_id=case.id,
        token_id=run.token_id,
        source_type=source_type,
        source_id=source.source_id,
        source_label=source.source_label[:220],
        metric_type=metric_type,
        base_logprob=base_target,
        conditioned_logprob=conditioned_target,
        lift=lift,
        information_gain_bits=information_gain_bits(lift),
        kl_divergence=kl_value,
        verdict=verdict_for(lift, kl_value),
        distribution_base=base_distribution,
        distribution_conditioned=conditioned_distribution,
        metadata_json={"target_label": target_label},
    )


def _build_case_candidates(db: Session, participant: ParticipantToken) -> tuple[list[HarnessCaseCandidate], int]:
    rows = (
        db.query(RawEvent)
        .filter(RawEvent.token_id == participant.id)
        .order_by(RawEvent.created_at.desc())
        .limit(60)
        .all()
    )
    cases: list[HarnessCaseCandidate] = []
    skipped = 0
    for event in rows:
        candidate = _case_from_event(event)
        if candidate is None:
            payload = event.payload if isinstance(event.payload, dict) else {}
            if payload.get("step_type") in {"triad", "duel", "twin_rank"}:
                skipped += 1
            continue
        cases.append(candidate)
        if len(cases) >= MAX_CASES:
            break
    return list(reversed(cases)), skipped


def _case_from_event(event: RawEvent) -> HarnessCaseCandidate | None:
    payload = event.payload if isinstance(event.payload, dict) else {}
    step = payload.get("step_snapshot") if isinstance(payload.get("step_snapshot"), dict) else {}
    answer = payload.get("answer") if isinstance(payload.get("answer"), dict) else {}
    step_type = str(payload.get("step_type") or step.get("type") or "")
    if step_type not in {"triad", "duel", "twin_rank"}:
        return None
    raw_options = step.get("options")
    if not isinstance(raw_options, list):
        return None
    options = [str(option).strip() for option in raw_options if isinstance(option, str) and option.strip()]
    if len(options) < 2:
        return None

    selected_text: str | None = None
    if step_type in {"triad", "duel"}:
        selected_index = answer.get("selected_index")
        if isinstance(selected_index, int) and 0 <= selected_index < len(options):
            selected_text = options[selected_index]
        elif isinstance(answer.get("selected_option"), str):
            selected_text = str(answer["selected_option"]).strip()
    elif step_type == "twin_rank":
        ranked_options = answer.get("ranked_options")
        if isinstance(ranked_options, list) and ranked_options:
            selected_text = str(ranked_options[0]).strip()

    if not selected_text or selected_text not in options:
        return None
    labels = ["A", "B", "C", "D", "E"]
    candidate_actions = [
        {"label": labels[index], "text": option}
        for index, option in enumerate(options[: len(labels)])
    ]
    target_index = options.index(selected_text)
    if target_index >= len(candidate_actions):
        return None
    replay_id = _replay_id_from_payload(payload, answer, step)
    return HarnessCaseCandidate(
        target_event_id=event.id,
        target_step_id=str(payload.get("step_id") or step.get("id") or "") or None,
        target_step_type=step_type,
        replay_scenario_id=replay_id,
        human_target_label=candidate_actions[target_index]["label"],
        human_target_text=selected_text,
        candidate_actions=candidate_actions,
        situation=_situation_text(step, payload),
        metadata={
            "event_type": event.event_type,
            "created_at": event.created_at.isoformat(),
            "candidate_count": len(candidate_actions),
            "replay_scenario_id": replay_id,
        },
    )


def _memory_sources(db: Session, participant: ParticipantToken) -> list[HarnessSource]:
    cards = (
        db.query(MemoryCard)
        .filter(MemoryCard.token_id == participant.id, MemoryCard.status == "reviewed")
        .order_by(MemoryCard.priority.asc(), MemoryCard.updated_at.desc())
        .limit(MAX_SOURCES_PER_TYPE)
        .all()
    )
    return [
        HarnessSource(
            source_type="memory_card",
            source_id=card.id,
            source_label=card.title,
            text=_truncate(
                "\n".join(
                    [
                        f"Memory card: {card.title}",
                        f"Priority: {card.priority}",
                        f"Body: {card.body}",
                        f"Source quote: {card.source_quote or 'None'}",
                    ]
                ),
                1000,
            ),
        )
        for card in cards
    ]


def _questionnaire_sources(db: Session, participant: ParticipantToken) -> list[HarnessSource]:
    events = (
        db.query(RawEvent)
        .filter(RawEvent.token_id == participant.id)
        .order_by(RawEvent.created_at.desc())
        .limit(80)
        .all()
    )
    sources: list[HarnessSource] = []
    for event in events:
        payload = event.payload if isinstance(event.payload, dict) else {}
        step_type = str(payload.get("step_type") or "")
        if step_type not in {"onboarding", "triad", "duel", "context_flip", "twin_rank"}:
            continue
        source = _questionnaire_source_from_event(event, payload)
        if source is not None:
            sources.append(source)
        if len(sources) >= MAX_SOURCES_PER_TYPE:
            break
    return list(reversed(sources))


def _questionnaire_source_from_event(event: RawEvent, payload: dict[str, Any]) -> HarnessSource | None:
    step = payload.get("step_snapshot") if isinstance(payload.get("step_snapshot"), dict) else {}
    answer = payload.get("answer") if isinstance(payload.get("answer"), dict) else {}
    step_type = str(payload.get("step_type") or step.get("type") or event.event_type)
    step_id = str(payload.get("step_id") or step.get("id") or event.id)
    title = str(step.get("title") or step_type)
    answer_text = _answer_summary(answer)
    prompt = str(step.get("prompt") or "").strip()
    if not answer_text and not prompt:
        return None
    return HarnessSource(
        source_type="question_event",
        source_id=event.id,
        source_label=f"{step_type}: {title}",
        text=_truncate(
            "\n".join(
                [
                    f"Questionnaire event: {step_type}",
                    f"Step: {step_id}",
                    f"Prompt: {prompt or 'None'}",
                    f"Answer: {answer_text or 'None'}",
                ]
            ),
            1000,
        ),
    )


def _build_prompt(participant: ParticipantToken, case: HarnessCaseCandidate, sources: list[HarnessSource]) -> str:
    source_context = "\n\n".join(f"[{source.source_type}:{source.source_id}]\n{source.text}" for source in sources)
    if not source_context:
        source_context = "No additional memory cards or questionnaire events are injected for this score."
    candidate_lines = "\n".join(f"{action['label']}. {action['text']}" for action in case.candidate_actions)
    labels = ", ".join(action["label"] for action in case.candidate_actions)
    profile_context = build_model_profile_context(participant) or "No participant profile was provided."
    prompt = f"""
You are evaluating a held-out decision for a digital twin diagnostics harness.
This is not a participant-facing prompt. Use the participant context and injected source context to predict the human-selected action.
Return exactly one uppercase label and no explanation.

Participant baseline context:
{profile_context}

Injected source context:
{source_context}

Held-out situation:
{case.situation}

Candidate actions:
{candidate_lines}

Valid labels: {labels}
""".strip()
    return _truncate(prompt, MAX_CONTEXT_CHARS)


def _situation_text(step: dict[str, Any], payload: dict[str, Any]) -> str:
    pieces = []
    for key in ("title", "prompt", "context_title"):
        value = step.get(key)
        if isinstance(value, str) and value.strip():
            pieces.append(value.strip())
    context_items = step.get("context_items")
    if isinstance(context_items, list):
        pieces.extend(str(item).strip() for item in context_items if isinstance(item, str) and item.strip())
    replay_id = payload.get("replay_scenario_id") or step.get("replay_scenario_id")
    if replay_id:
        pieces.append(f"Replay scenario id: {replay_id}")
    return "\n".join(pieces) or "No situation text was captured."


def _answer_summary(answer: dict[str, Any]) -> str:
    if isinstance(answer.get("selected_option"), str):
        return str(answer["selected_option"]).strip()
    if isinstance(answer.get("text"), str):
        return str(answer["text"]).strip()
    ranked = answer.get("ranked_options")
    if isinstance(ranked, list):
        pieces = [str(item).strip() for item in ranked if isinstance(item, str) and item.strip()]
        result = "Ranked: " + " > ".join(pieces)
        rejected = answer.get("rejected_options")
        if isinstance(rejected, list) and rejected:
            result += "\nRejected: " + "; ".join(str(item).strip() for item in rejected if isinstance(item, str))
        correction = answer.get("correction_text")
        if isinstance(correction, str) and correction.strip():
            result += f"\nCorrection: {correction.strip()}"
        return result
    if isinstance(answer.get("user_profile"), str):
        return str(answer["user_profile"]).strip()
    return ""


def _aggregate_scores(
    db: Session,
    run_id: str,
    skipped_targets: int,
    memory_source_count: int,
    questionnaire_source_count: int,
) -> dict[str, Any]:
    scores = db.query(TwinHarnessScore).filter(TwinHarnessScore.harness_run_id == run_id).all()
    verdict_counts: dict[str, int] = {}
    source_type_counts: dict[str, int] = {}
    metric_type_counts: dict[str, int] = {}
    lift_total = 0.0
    kl_total = 0.0
    for score in scores:
        verdict_counts[score.verdict] = verdict_counts.get(score.verdict, 0) + 1
        source_type_counts[score.source_type] = source_type_counts.get(score.source_type, 0) + 1
        metric_type_counts[score.metric_type] = metric_type_counts.get(score.metric_type, 0) + 1
        lift_total += score.lift
        kl_total += score.kl_divergence
    case_count = db.query(TwinHarnessCase).filter(TwinHarnessCase.harness_run_id == run_id).count()
    score_count = len(scores)
    return {
        "case_count": case_count,
        "score_count": score_count,
        "skipped_target_count": skipped_targets,
        "memory_source_count": memory_source_count,
        "questionnaire_source_count": questionnaire_source_count,
        "average_lift": round(lift_total / score_count, 5) if score_count else 0.0,
        "average_kl_divergence": round(kl_total / score_count, 5) if score_count else 0.0,
        "verdict_counts": verdict_counts,
        "source_type_counts": source_type_counts,
        "metric_type_counts": metric_type_counts,
        "caps": {"max_cases": MAX_CASES, "max_sources_per_type": MAX_SOURCES_PER_TYPE},
    }


def _extract_label_logprobs(data: dict[str, Any], labels: list[str]) -> dict[str, float]:
    try:
        choice = data["choices"][0]
    except (KeyError, IndexError, TypeError) as exc:
        raise UnsupportedLogprobsError(_unsupported_guidance("Provider response did not include choices.")) from exc
    logprobs = choice.get("logprobs") if isinstance(choice, dict) else None
    if not isinstance(logprobs, dict):
        raise UnsupportedLogprobsError(_unsupported_guidance("Provider response omitted logprobs."))
    content = logprobs.get("content")
    if not isinstance(content, list) or not content:
        raise UnsupportedLogprobsError(_unsupported_guidance("Provider response omitted token logprob content."))
    top_logprobs = content[0].get("top_logprobs") if isinstance(content[0], dict) else None
    if not top_logprobs:
        raise UnsupportedLogprobsError(_unsupported_guidance("Provider response omitted top_logprobs."))

    observed: dict[str, float] = {}
    if isinstance(top_logprobs, dict):
        iterable = [
            {"token": token, "logprob": value.get("logprob") if isinstance(value, dict) else value}
            for token, value in top_logprobs.items()
        ]
    elif isinstance(top_logprobs, list):
        iterable = top_logprobs
    else:
        raise UnsupportedLogprobsError(_unsupported_guidance("Provider top_logprobs shape was not usable."))

    for item in iterable:
        if not isinstance(item, dict):
            continue
        label = _label_from_token(str(item.get("token", "")), labels)
        if label is None:
            continue
        try:
            logprob = float(item.get("logprob"))
        except (TypeError, ValueError):
            continue
        observed[label] = max(observed.get(label, -math.inf), logprob)
    if not observed:
        raise UnsupportedLogprobsError(_unsupported_guidance("No candidate action labels appeared in top_logprobs."))
    floor = min(observed.values()) - LOGPROB_FLOOR_DELTA
    return {label: observed.get(label, floor) for label in labels}


def _label_from_token(token: str, labels: list[str]) -> str | None:
    cleaned = token.strip().upper()
    if cleaned in labels:
        return cleaned
    if len(cleaned) >= 2 and cleaned[0] in labels and cleaned[1] in {".", ")", ":", "\n", " "}:
        return cleaned[0]
    return None


def _replay_id_from_payload(payload: dict[str, Any], answer: dict[str, Any], step: dict[str, Any]) -> str | None:
    for container in (payload, answer, step):
        value = container.get("replay_scenario_id")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _participant_completed(participant: ParticipantToken) -> bool:
    return participant.completed_at is not None or participant.status == TokenStatus.completed


def _truncate(value: str, limit: int) -> str:
    cleaned = value.strip()
    if len(cleaned) <= limit:
        return cleaned
    return f"{cleaned[: limit - 18].rstrip()}\n[truncated]"


def _unsupported_guidance(reason: str) -> str:
    return (
        f"{reason} Switch OPENROUTER_MODEL to a model/provider that supports chat-completion "
        "logprobs and top_logprobs, then run the harness again."
    )
