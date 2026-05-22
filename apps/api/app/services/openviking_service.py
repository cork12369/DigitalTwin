from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import SessionLocal
from app.models import (
    MemoryCard,
    ParticipantToken,
    RawEvent,
    WorkflowRun,
    WorkflowStatus,
    now_utc,
)


SYNC_WORKFLOW_NAME = "openviking_context_sync"
OPENVIKING_TEST_TRIGGER = "openviking_admin_test"
SYNCABLE_STEP_TYPES = {"onboarding", "triad", "duel", "context_flip", "twin_rank"}


class OpenVikingClientError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        code: str = "OPENVIKING_ERROR",
        status_code: int | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.detail = detail or {}


@dataclass(frozen=True)
class OpenVikingDocument:
    uri: str
    source_type: str
    source_id: str
    source_label: str
    content: str
    metadata: dict[str, Any]


@dataclass(frozen=True)
class OpenVikingRetrievedSource:
    source_type: str
    source_id: str
    source_label: str
    text: str
    metadata: dict[str, Any]


@dataclass(frozen=True)
class OpenVikingRetrievalResult:
    status: str
    sources: list[OpenVikingRetrievedSource]
    metadata: dict[str, Any]


class OpenVikingClient:
    def __init__(self) -> None:
        settings = get_settings()
        self.base_url = settings.openviking_base_url.strip().rstrip("/")
        self.api_key = settings.openviking_api_key.strip()
        self.timeout = float(settings.openviking_timeout_seconds or 20.0)

    @property
    def configured(self) -> bool:
        return bool(self.base_url)

    def health(self) -> dict[str, Any]:
        if not self.configured:
            return {
                "configured": False,
                "status": "disabled",
                "base_url": None,
                "message": "OpenViking is not configured.",
                "detail": {},
            }
        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.get(f"{self.base_url}/health")
            detail = _safe_json(response)
            if response.is_success:
                return {
                    "configured": True,
                    "status": "ok",
                    "base_url": self.base_url,
                    "message": "OpenViking is reachable.",
                    "detail": detail,
                }
            return {
                "configured": True,
                "status": "unavailable",
                "base_url": self.base_url,
                "message": f"OpenViking health check returned HTTP {response.status_code}.",
                "detail": detail,
            }
        except httpx.TimeoutException as exc:
            return {
                "configured": True,
                "status": "timeout",
                "base_url": self.base_url,
                "message": f"OpenViking health check timed out: {exc}",
                "detail": {},
            }
        except httpx.RequestError as exc:
            return {
                "configured": True,
                "status": "unavailable",
                "base_url": self.base_url,
                "message": f"OpenViking is unreachable: {exc}",
                "detail": {},
            }

    def mkdir(self, uri: str, description: str = "") -> dict[str, Any]:
        try:
            return self._request("POST", "/api/v1/fs/mkdir", json_body={"uri": uri, "description": description})
        except OpenVikingClientError as exc:
            if exc.code == "ALREADY_EXISTS":
                return {"uri": uri, "already_exists": True}
            raise

    def delete_uri(self, uri: str, *, recursive: bool = False) -> dict[str, Any]:
        return self._request("DELETE", "/api/v1/fs", params={"uri": uri, "recursive": str(recursive).lower()})

    def write_content(self, uri: str, content: str) -> dict[str, Any]:
        return self._request(
            "POST",
            "/api/v1/content/write",
            json_body={"uri": uri, "content": content, "mode": "replace", "wait": True},
        )

    def read_content(self, uri: str) -> str:
        result = self._request("GET", "/api/v1/content/read", params={"uri": uri})
        return result if isinstance(result, str) else json.dumps(result, ensure_ascii=True)

    def find(self, query: str, *, target_uri: str, node_limit: int = 6) -> dict[str, Any]:
        return self._request(
            "POST",
            "/api/v1/search/find",
            json_body={
                "query": query,
                "target_uri": target_uri,
                "node_limit": node_limit,
                "level": "0,1,2",
            },
        )

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> Any:
        if not self.configured:
            raise OpenVikingClientError("OpenViking is not configured.", code="UNCONFIGURED")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
            headers["X-API-Key"] = self.api_key
        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.request(
                    method,
                    f"{self.base_url}{path}",
                    headers=headers,
                    params=params,
                    json=json_body,
                )
        except httpx.TimeoutException as exc:
            raise OpenVikingClientError(f"OpenViking request timed out: {exc}", code="TIMEOUT") from exc
        except httpx.RequestError as exc:
            raise OpenVikingClientError(f"OpenViking request failed: {exc}", code="UNAVAILABLE") from exc

        data = _safe_json(response)
        if not response.is_success:
            code, message = _error_from_envelope(data, fallback=f"OpenViking returned HTTP {response.status_code}.")
            raise OpenVikingClientError(message, code=code, status_code=response.status_code, detail=data)
        if isinstance(data, dict) and data.get("status") == "error":
            code, message = _error_from_envelope(data, fallback="OpenViking returned an error response.")
            raise OpenVikingClientError(message, code=code, status_code=response.status_code, detail=data)
        if isinstance(data, dict) and "result" in data:
            return data["result"]
        return data


def openviking_status() -> dict[str, Any]:
    return OpenVikingClient().health()


def token_root_uri(token_id: str) -> str:
    return f"viking://resources/digitaltwin/tokens/{_path_segment(token_id)}"


def queue_openviking_sync(db: Session, participant: ParticipantToken, trigger_reason: str) -> WorkflowRun | None:
    if not get_settings().has_openviking_config:
        return None
    existing = (
        db.query(WorkflowRun)
        .filter(
            WorkflowRun.token_id == participant.id,
            WorkflowRun.name == SYNC_WORKFLOW_NAME,
            WorkflowRun.status.in_([WorkflowStatus.queued, WorkflowStatus.running]),
        )
        .order_by(WorkflowRun.created_at.desc())
        .first()
    )
    if existing is not None:
        return existing
    run = WorkflowRun(
        token_id=participant.id,
        name=SYNC_WORKFLOW_NAME,
        status=WorkflowStatus.queued,
        input_summary=f"Queued OpenViking context sync after {trigger_reason}.",
        metadata_json={"trigger_reason": trigger_reason, "root_uri": token_root_uri(participant.id)},
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def run_openviking_sync_job(run_id: str) -> None:
    db = SessionLocal()
    try:
        run = db.get(WorkflowRun, run_id)
        if run is None or run.name != SYNC_WORKFLOW_NAME or run.status not in {WorkflowStatus.queued, WorkflowStatus.failed}:
            return
        participant = db.get(ParticipantToken, run.token_id) if run.token_id else None
        if participant is None:
            run.status = WorkflowStatus.failed
            run.error_summary = "Participant token was not found."
            run.completed_at = now_utc()
            db.commit()
            return
        _execute_openviking_sync(db, run, participant)
    finally:
        db.close()


def sync_openviking_for_token(db: Session, participant: ParticipantToken, trigger_reason: str) -> WorkflowRun:
    run = WorkflowRun(
        token_id=participant.id,
        name=SYNC_WORKFLOW_NAME,
        status=WorkflowStatus.queued,
        input_summary=f"Manual OpenViking context sync for {trigger_reason}.",
        metadata_json={"trigger_reason": trigger_reason, "root_uri": token_root_uri(participant.id)},
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return _execute_openviking_sync(db, run, participant)


def openviking_token_state(db: Session, participant: ParticipantToken) -> dict[str, Any]:
    latest_sync = (
        db.query(WorkflowRun)
        .filter(WorkflowRun.token_id == participant.id, WorkflowRun.name == SYNC_WORKFLOW_NAME)
        .order_by(WorkflowRun.created_at.desc())
        .first()
    )
    from app.models import TwinHarnessRun

    latest_test = (
        db.query(TwinHarnessRun)
        .filter(TwinHarnessRun.token_id == participant.id, TwinHarnessRun.trigger_reason == OPENVIKING_TEST_TRIGGER)
        .order_by(TwinHarnessRun.created_at.desc())
        .first()
    )
    metadata = latest_sync.metadata_json if latest_sync and isinstance(latest_sync.metadata_json, dict) else {}
    return {
        "token_id": participant.id,
        "root_uri": token_root_uri(participant.id),
        "status": openviking_status(),
        "latest_sync_run": latest_sync,
        "latest_test_run": latest_test,
        "mirrored_source_count": int(metadata.get("written_uri_count") or metadata.get("document_count") or 0),
        "last_error": latest_sync.error_summary if latest_sync else None,
    }


def retrieve_openviking_sources_for_case(
    participant: ParticipantToken,
    *,
    situation: str,
    candidate_actions: list[dict[str, str]],
    target_event_id: str | None,
    limit: int = 6,
) -> OpenVikingRetrievalResult:
    client = OpenVikingClient()
    if not client.configured:
        return OpenVikingRetrievalResult(
            status="unconfigured",
            sources=[],
            metadata={"status": "unconfigured", "message": "OpenViking is not configured."},
        )
    query = _retrieval_query(situation, candidate_actions)
    target_uri = token_root_uri(participant.id)
    try:
        result = client.find(query, target_uri=target_uri, node_limit=limit)
    except OpenVikingClientError as exc:
        return OpenVikingRetrievalResult(
            status="failed",
            sources=[],
            metadata={"status": "failed", "error": str(exc), "code": exc.code, "target_uri": target_uri},
        )

    contexts = _flatten_find_result(result)
    sources: list[OpenVikingRetrievedSource] = []
    errors: list[dict[str, Any]] = []
    for rank, context in enumerate(contexts, start=1):
        uri = str(context.get("uri") or "")
        mapped = _source_from_uri(uri)
        if mapped["source_id"] and mapped["source_id"] == target_event_id:
            continue
        content = ""
        if uri.endswith(".md"):
            try:
                content = client.read_content(uri)
            except OpenVikingClientError as exc:
                errors.append({"uri": uri, "error": str(exc), "code": exc.code})
        if not content:
            content = "\n".join(
                item
                for item in [
                    str(context.get("abstract") or "").strip(),
                    str(context.get("overview") or "").strip(),
                ]
                if item
            )
        if not content:
            continue
        source_type = _openviking_source_type(mapped["source_type"])
        source_id = mapped["source_id"] or uri
        sources.append(
            OpenVikingRetrievedSource(
                source_type=source_type,
                source_id=source_id,
                source_label=_label_from_content(content, fallback=uri),
                text=content,
                metadata={
                    "provider": "openviking",
                    "viking_uri": uri,
                    "retrieval_rank": rank,
                    "relevance_score": _float_or_none(context.get("score")),
                    "level": context.get("level"),
                    "match_reason": context.get("match_reason") or "",
                    "context_type": context.get("context_type") or "",
                    "mapped_source_type": mapped["source_type"],
                    "mapped_source_id": mapped["source_id"],
                    "target_uri": target_uri,
                },
            )
        )
        if len(sources) >= limit:
            break
    return OpenVikingRetrievalResult(
        status="ok",
        sources=sources,
        metadata={
            "status": "ok",
            "target_uri": target_uri,
            "query": query,
            "returned_context_count": len(contexts),
            "used_source_count": len(sources),
            "errors": errors,
        },
    )


def build_openviking_documents(db: Session, participant: ParticipantToken) -> list[OpenVikingDocument]:
    documents: list[OpenVikingDocument] = []
    cards = (
        db.query(MemoryCard)
        .filter(MemoryCard.token_id == participant.id, MemoryCard.status == "reviewed")
        .order_by(MemoryCard.priority.asc(), MemoryCard.updated_at.desc())
        .all()
    )
    for card in cards:
        documents.append(_card_document(participant, card))

    events = (
        db.query(RawEvent)
        .filter(RawEvent.token_id == participant.id)
        .order_by(RawEvent.created_at.asc())
        .all()
    )
    for event in events:
        document = _event_document(participant, event)
        if document is not None:
            documents.append(document)
    return documents


def _execute_openviking_sync(db: Session, run: WorkflowRun, participant: ParticipantToken) -> WorkflowRun:
    run.status = WorkflowStatus.running
    run.started_at = now_utc()
    db.commit()

    client = OpenVikingClient()
    root_uri = token_root_uri(participant.id)
    try:
        documents = build_openviking_documents(db, participant)
        if not client.configured:
            run.status = WorkflowStatus.completed
            run.output_summary = "OpenViking sync skipped: OpenViking is not configured."
            run.metadata_json = {
                **(run.metadata_json or {}),
                "status": "unconfigured",
                "skipped": True,
                "root_uri": root_uri,
                "document_count": len(documents),
                "written_uri_count": 0,
            }
            run.completed_at = now_utc()
            db.commit()
            db.refresh(run)
            return run

        try:
            client.delete_uri(root_uri, recursive=True)
        except OpenVikingClientError as exc:
            if exc.status_code != 404 and exc.code not in {"NOT_FOUND", "FILE_NOT_FOUND", "PATH_NOT_FOUND"}:
                raise
        _mkdirs_for_documents(client, root_uri, documents)
        written_uris: list[str] = []
        for document in documents:
            client.write_content(document.uri, document.content)
            written_uris.append(document.uri)

        run.status = WorkflowStatus.completed
        run.output_summary = f"Synced {len(written_uris)} DigitalTwin sources into OpenViking."
        run.metadata_json = {
            **(run.metadata_json or {}),
            "status": "completed",
            "root_uri": root_uri,
            "document_count": len(documents),
            "written_uri_count": len(written_uris),
            "written_uris": written_uris[:80],
        }
        run.completed_at = now_utc()
        db.commit()
        db.refresh(run)
        return run
    except OpenVikingClientError as exc:
        run.status = WorkflowStatus.failed
        run.error_summary = str(exc)
        run.output_summary = "OpenViking sync failed; participant flow was not affected."
        run.metadata_json = {
            **(run.metadata_json or {}),
            "status": "failed",
            "root_uri": root_uri,
            "error_code": exc.code,
            "status_code": exc.status_code,
            "detail": exc.detail,
        }
        run.completed_at = now_utc()
        db.commit()
        db.refresh(run)
        return run


def _mkdirs_for_documents(client: OpenVikingClient, root_uri: str, documents: list[OpenVikingDocument]) -> None:
    directories = {
        "viking://resources/digitaltwin/",
        "viking://resources/digitaltwin/tokens/",
        f"{root_uri}/",
    }
    for document in documents:
        parts = document.uri.removeprefix("viking://resources/").split("/")[:-1]
        current = "viking://resources/"
        for part in parts:
            if not part:
                continue
            current = f"{current.rstrip('/')}/{part}/"
            directories.add(current)
    for directory in sorted(directories, key=lambda value: value.count("/")):
        client.mkdir(directory, description="DigitalTwin OpenViking admin test mirror")


def _card_document(participant: ParticipantToken, card: MemoryCard) -> OpenVikingDocument:
    metadata = {
        "token_id": participant.id,
        "source_type": "memory_card",
        "source_id": card.id,
        "title": card.title,
        "priority": card.priority,
        "status": card.status,
        "created_at": card.created_at.isoformat() if card.created_at else None,
        "updated_at": card.updated_at.isoformat() if card.updated_at else None,
    }
    pillar_keys = [link.pillar_key for link in card.pillar_links]
    content = "\n".join(
        [
            _frontmatter({**metadata, "pillar_keys": pillar_keys}),
            f"# Memory Card: {card.title}",
            "",
            f"Priority: {card.priority}",
            f"Pillars: {', '.join(pillar_keys) if pillar_keys else 'None'}",
            "",
            "## Body",
            card.body.strip(),
            "",
            "## Source Quote",
            (card.source_quote or "None").strip(),
        ]
    )
    return OpenVikingDocument(
        uri=f"{token_root_uri(participant.id)}/cards/{_path_segment(card.id)}.md",
        source_type="memory_card",
        source_id=card.id,
        source_label=card.title,
        content=content,
        metadata=metadata,
    )


def _event_document(participant: ParticipantToken, event: RawEvent) -> OpenVikingDocument | None:
    payload = event.payload if isinstance(event.payload, dict) else {}
    step = payload.get("step_snapshot") if isinstance(payload.get("step_snapshot"), dict) else {}
    answer = payload.get("answer") if isinstance(payload.get("answer"), dict) else {}
    step_type = str(payload.get("step_type") or step.get("type") or event.event_type)
    if step_type not in SYNCABLE_STEP_TYPES:
        return None
    replay_id = _replay_id_from_payload(payload, answer, step)
    source_type = "replay_event" if replay_id else "question_event"
    title = str(step.get("title") or step_type)
    metadata = {
        "token_id": participant.id,
        "source_type": source_type,
        "source_id": event.id,
        "event_type": event.event_type,
        "step_type": step_type,
        "step_id": payload.get("step_id") or step.get("id"),
        "replay_scenario_id": replay_id,
        "created_at": event.created_at.isoformat() if event.created_at else None,
        "title": title,
    }
    prompt = str(step.get("prompt") or "").strip()
    content = "\n".join(
        [
            _frontmatter(metadata),
            f"# {step_type}: {title}",
            "",
            f"Event type: {event.event_type}",
            f"Step id: {metadata['step_id'] or 'None'}",
            f"Replay scenario id: {replay_id or 'None'}",
            "",
            "## Prompt",
            prompt or "None",
            "",
            "## Options",
            _options_summary(step.get("options")),
            "",
            "## Answer",
            _answer_summary(answer) or "None",
            "",
            "## Raw Answer",
            "```json",
            json.dumps(answer, indent=2, sort_keys=True, ensure_ascii=True),
            "```",
        ]
    )
    if replay_id:
        uri = f"{token_root_uri(participant.id)}/replay/{_path_segment(replay_id)}/{_path_segment(event.id)}.md"
    else:
        uri = f"{token_root_uri(participant.id)}/questionnaire/{_path_segment(event.id)}.md"
    return OpenVikingDocument(
        uri=uri,
        source_type=source_type,
        source_id=event.id,
        source_label=f"{step_type}: {title}",
        content=content,
        metadata=metadata,
    )


def _retrieval_query(situation: str, candidate_actions: list[dict[str, str]]) -> str:
    actions = "\n".join(f"{action.get('label')}. {action.get('text')}" for action in candidate_actions)
    return f"Held-out situation:\n{situation}\n\nCandidate actions:\n{actions}".strip()


def _flatten_find_result(result: dict[str, Any]) -> list[dict[str, Any]]:
    contexts: list[dict[str, Any]] = []
    for key in ("resources", "memories", "skills"):
        value = result.get(key) if isinstance(result, dict) else None
        if isinstance(value, list):
            contexts.extend(item for item in value if isinstance(item, dict))
    return sorted(contexts, key=lambda item: float(item.get("score") or 0.0), reverse=True)


def _source_from_uri(uri: str) -> dict[str, str | None]:
    match = re.search(r"/cards/([^/]+)\.md$", uri)
    if match:
        return {"source_type": "memory_card", "source_id": match.group(1)}
    match = re.search(r"/questionnaire/([^/]+)\.md$", uri)
    if match:
        return {"source_type": "question_event", "source_id": match.group(1)}
    match = re.search(r"/replay/[^/]+/([^/]+)\.md$", uri)
    if match:
        return {"source_type": "replay_event", "source_id": match.group(1)}
    return {"source_type": "unknown", "source_id": None}


def _openviking_source_type(source_type: str | None) -> str:
    if source_type == "memory_card":
        return "openviking_memory_card"
    if source_type == "replay_event":
        return "openviking_replay_event"
    if source_type == "question_event":
        return "openviking_question_event"
    return "openviking_source"


def _label_from_content(content: str, fallback: str) -> str:
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip()[:220] or fallback
    return fallback


def _frontmatter(metadata: dict[str, Any]) -> str:
    lines = ["---"]
    for key, value in metadata.items():
        if value is None:
            continue
        lines.append(f"{key}: {json.dumps(value, ensure_ascii=True)}")
    lines.append("---")
    return "\n".join(lines)


def _options_summary(options: Any) -> str:
    if not isinstance(options, list) or not options:
        return "None"
    return "\n".join(f"- {str(option).strip()}" for option in options if str(option).strip())


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


def _replay_id_from_payload(payload: dict[str, Any], answer: dict[str, Any], step: dict[str, Any]) -> str | None:
    for container in (payload, answer, step):
        value = container.get("replay_scenario_id")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _path_segment(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip()).strip("-")
    return quote(cleaned or "unknown", safe="A-Za-z0-9_.-")


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_json(response: httpx.Response) -> dict[str, Any]:
    try:
        data = response.json()
    except ValueError:
        return {"raw": response.text[:1000]}
    return data if isinstance(data, dict) else {"result": data}


def _error_from_envelope(data: dict[str, Any], *, fallback: str) -> tuple[str, str]:
    error = data.get("error") if isinstance(data, dict) else None
    if isinstance(error, dict):
        code = str(error.get("code") or "OPENVIKING_ERROR")
        message = str(error.get("message") or fallback)
        return code, message
    return "OPENVIKING_ERROR", fallback
