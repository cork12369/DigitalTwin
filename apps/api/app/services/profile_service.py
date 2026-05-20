from __future__ import annotations

import json
import re
from dataclasses import dataclass
from io import BytesIO
from typing import Any

import httpx
from pydantic import BaseModel, Field, ValidationError
from pypdf import PdfReader

from app.config import get_settings
from app.models import ParticipantToken, now_utc


MAX_CV_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_PROFILE_CONTEXT_CHARS = 12000


class ProfileLLMSummary(BaseModel):
    summary_text: str = Field(min_length=1, max_length=3000)
    domains: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    roles: list[str] = Field(default_factory=list)
    projects: list[str] = Field(default_factory=list)
    decision_context_hooks: list[str] = Field(default_factory=list)
    personalization_notes: list[str] = Field(default_factory=list)


@dataclass
class ProfileIngestionResult:
    source_type: str
    source_filename: str | None
    user_profile: str
    structured_context: dict[str, Any]
    llm_summary: dict[str, Any] | None
    metadata: dict[str, Any]


def build_manual_profile(profile_text: str) -> ProfileIngestionResult:
    cleaned = _clean_text(profile_text)
    structured_context = {
        "summary": cleaned,
        "skills": [],
        "experience": [],
        "projects": [],
        "education": [],
        "raw_text_excerpt": cleaned[:2000],
    }
    return ProfileIngestionResult(
        source_type="manual",
        source_filename=None,
        user_profile=cleaned,
        structured_context=structured_context,
        llm_summary=None,
        metadata={
            "status": "manual_profile_captured",
            "text_char_count": len(cleaned),
            "updated_at": now_utc().isoformat(),
        },
    )


def ingest_cv_pdf(filename: str | None, content_type: str | None, file_bytes: bytes) -> ProfileIngestionResult:
    _validate_pdf_upload(filename, content_type, file_bytes)
    extracted_text, page_count = _extract_pdf_text(file_bytes)
    structured_context = parse_cv_text(extracted_text)
    user_profile = profile_text_from_structured_context(structured_context)
    llm_summary, summary_metadata = summarize_profile_with_llm(structured_context)

    metadata = {
        "status": "cv_processed",
        "pdf_stored": False,
        "source_filename": filename,
        "content_type": content_type,
        "upload_size_bytes": len(file_bytes),
        "page_count": page_count,
        "extracted_char_count": len(extracted_text),
        "structured_char_count": len(json.dumps(structured_context, ensure_ascii=True)),
        "llm_summary_status": summary_metadata["status"],
        "llm_summary_reason": summary_metadata.get("reason"),
        "llm_summary_attempts": summary_metadata.get("attempts", 0),
        "updated_at": now_utc().isoformat(),
    }

    return ProfileIngestionResult(
        source_type="cv_pdf",
        source_filename=filename,
        user_profile=user_profile,
        structured_context=structured_context,
        llm_summary=llm_summary,
        metadata=metadata,
    )


def build_model_profile_context(participant: ParticipantToken) -> str:
    summary = participant.profile_llm_summary
    if isinstance(summary, dict):
        summary_text = summary.get("summary_text")
        if isinstance(summary_text, str) and summary_text.strip():
            return summary_text.strip()

    structured_context = participant.profile_structured_context
    if isinstance(structured_context, dict) and structured_context:
        structured_text = profile_text_from_structured_context(structured_context)
        if structured_text.strip():
            return structured_text

    return (participant.user_profile or "").strip()


def parse_cv_text(text: str) -> dict[str, Any]:
    cleaned = _clean_text(text)[:MAX_PROFILE_CONTEXT_CHARS]
    lines = _meaningful_lines(cleaned)
    sections = _section_map(lines)

    skills = _split_list_items(sections.get("skills", []))[:30]
    experience = _compact_items(sections.get("experience", []), max_items=8)
    projects = _compact_items(sections.get("projects", []), max_items=8)
    education = _compact_items(sections.get("education", []), max_items=5)
    summary_lines = sections.get("summary") or lines[:8]

    structured = {
        "headline": _first_role_like_line(lines),
        "summary": _join_limited(summary_lines, 1000),
        "domains": _infer_domains(cleaned),
        "skills": skills,
        "roles": _infer_roles(lines),
        "experience": experience,
        "projects": projects,
        "education": education,
        "raw_text_excerpt": cleaned[:4000],
    }
    return structured


def profile_text_from_structured_context(context: dict[str, Any]) -> str:
    parts: list[str] = []
    _append_text(parts, "Headline", context.get("headline"))
    _append_text(parts, "Summary", context.get("summary"))
    _append_list(parts, "Domains", context.get("domains"))
    _append_list(parts, "Skills", context.get("skills"))
    _append_list(parts, "Roles", context.get("roles"))
    _append_list(parts, "Experience", context.get("experience"))
    _append_list(parts, "Projects", context.get("projects"))
    _append_list(parts, "Education", context.get("education"))
    if not parts:
        _append_text(parts, "Profile", context.get("raw_text_excerpt"))
    return "\n".join(parts)[:MAX_PROFILE_CONTEXT_CHARS]


def summarize_profile_with_llm(structured_context: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    settings = get_settings()
    if not settings.has_openrouter_key:
        return None, _summary_metadata("skipped", "openrouter_not_configured")

    first_error: str | None = None
    for attempt in (1, 2):
        try:
            payload = _call_summary_model(structured_context, first_error if attempt == 2 else None)
            summary = ProfileLLMSummary.model_validate(payload)
            return summary.model_dump(), _summary_metadata("generated", None, attempts=attempt)
        except (httpx.HTTPError, KeyError, TypeError, ValueError, ValidationError, json.JSONDecodeError) as exc:
            first_error = str(exc)

    return None, _summary_metadata("fallback", first_error or "summary_generation_failed", attempts=2)


def _validate_pdf_upload(filename: str | None, content_type: str | None, file_bytes: bytes) -> None:
    lower_name = (filename or "").lower()
    is_pdf_name = lower_name.endswith(".pdf")
    is_pdf_type = content_type in {"application/pdf", "application/x-pdf", "application/octet-stream", None}
    if not is_pdf_name or not is_pdf_type:
        raise ValueError("Upload must be a PDF file.")
    if not file_bytes:
        raise ValueError("Uploaded PDF is empty.")
    if len(file_bytes) > MAX_CV_UPLOAD_BYTES:
        raise ValueError("Uploaded PDF must be 5 MB or smaller.")


def _extract_pdf_text(file_bytes: bytes) -> tuple[str, int]:
    try:
        reader = PdfReader(BytesIO(file_bytes))
        page_text = [page.extract_text() or "" for page in reader.pages]
    except Exception as exc:  # pypdf can raise several parser-specific exceptions
        raise ValueError("Could not read this PDF. Try another file or paste profile text instead.") from exc

    text = _clean_text("\n".join(page_text))
    if len(text) < 40:
        raise ValueError("This PDF does not contain enough extractable text. Paste your profile text instead.")
    return text, len(reader.pages)


def _call_summary_model(structured_context: dict[str, Any], repair_error: str | None) -> dict[str, Any]:
    settings = get_settings()
    url = f"{settings.openrouter_base_url.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.openrouter_api_key}",
        "HTTP-Referer": settings.openrouter_site_url,
        "X-Title": settings.openrouter_app_name,
        "Content-Type": "application/json",
    }
    messages = [
        {"role": "system", "content": _summary_system_prompt()},
        {
            "role": "user",
            "content": json.dumps(
                {
                    "structured_cv_context": structured_context,
                    "repair_previous_error": repair_error,
                },
                ensure_ascii=True,
            ),
        },
    ]
    request_body = {
        "model": settings.openrouter_model,
        "messages": messages,
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }
    with httpx.Client(timeout=30.0) as client:
        response = client.post(url, headers=headers, json=request_body)
        response.raise_for_status()
        data = response.json()

    return json.loads(_strip_json_wrapper(data["choices"][0]["message"]["content"]))


def _summary_system_prompt() -> str:
    return """
Summarize a CV for a behavioral digital twin personalization engine.
Return one JSON object only. Do not use markdown.

The JSON object must have:
{
  "summary_text": "A compact first-person-neutral profile summary for scenario personalization.",
  "domains": [],
  "skills": [],
  "roles": [],
  "projects": [],
  "decision_context_hooks": [],
  "personalization_notes": []
}

Focus on professional context, likely decision environments, projects, skills, and concrete hooks for situational questions. Do not infer protected traits or sensitive personal attributes.
""".strip()


def _section_map(lines: list[str]) -> dict[str, list[str]]:
    aliases = {
        "summary": {"summary", "profile", "about", "objective", "professional summary"},
        "skills": {"skills", "technical skills", "core skills", "tools", "technologies"},
        "experience": {"experience", "work experience", "employment", "professional experience", "career history"},
        "projects": {"projects", "selected projects", "portfolio"},
        "education": {"education", "qualifications", "certifications", "training"},
    }
    heading_lookup = {
        alias: section
        for section, section_aliases in aliases.items()
        for alias in section_aliases
    }

    sections: dict[str, list[str]] = {"summary": []}
    current = "summary"
    for line in lines:
        normalized = re.sub(r"[^a-z ]", "", line.lower()).strip()
        if normalized in heading_lookup and len(line) <= 40:
            current = heading_lookup[normalized]
            sections.setdefault(current, [])
            continue
        sections.setdefault(current, []).append(line)
    return sections


def _infer_domains(text: str) -> list[str]:
    lower = text.lower()
    domain_terms = {
        "software engineering": ["software", "backend", "frontend", "api", "cloud", "devops"],
        "data and analytics": ["data", "analytics", "machine learning", "ai", "model", "dashboard"],
        "product and design": ["product", "design", "user research", "roadmap", "ux"],
        "operations": ["operations", "process", "supply chain", "logistics"],
        "healthcare": ["health", "clinical", "patient", "medical"],
        "finance": ["finance", "banking", "trading", "investment", "risk"],
        "education": ["education", "teaching", "curriculum", "student"],
    }
    return [
        domain
        for domain, terms in domain_terms.items()
        if any(term in lower for term in terms)
    ][:8]


def _infer_roles(lines: list[str]) -> list[str]:
    role_words = ["engineer", "developer", "designer", "manager", "analyst", "consultant", "researcher", "lead", "founder", "intern"]
    roles = [
        line
        for line in lines
        if len(line) <= 120 and any(word in line.lower() for word in role_words)
    ]
    return _dedupe(roles)[:10]


def _first_role_like_line(lines: list[str]) -> str | None:
    roles = _infer_roles(lines)
    return roles[0] if roles else (lines[0] if lines else None)


def _split_list_items(lines: list[str]) -> list[str]:
    text = " ".join(lines)
    pieces = re.split(r"[,;|\u2022\n]", text)
    return _dedupe(piece.strip(" -\t") for piece in pieces if 2 <= len(piece.strip()) <= 60)


def _compact_items(lines: list[str], max_items: int) -> list[str]:
    items: list[str] = []
    buffer: list[str] = []
    for line in lines:
        starts_new_item = bool(re.match(r"^[-\u2022]?\s*(20\d{2}|19\d{2}|[A-Z][A-Za-z]+ .*?)(\s[-|,]|$)", line))
        if starts_new_item and buffer:
            items.append(_join_limited(buffer, 360))
            buffer = []
        buffer.append(line)
        if len(" ".join(buffer)) > 320:
            items.append(_join_limited(buffer, 360))
            buffer = []
        if len(items) >= max_items:
            break
    if buffer and len(items) < max_items:
        items.append(_join_limited(buffer, 360))
    return _dedupe(items)[:max_items]


def _meaningful_lines(text: str) -> list[str]:
    return [
        line.strip(" -\t")
        for line in text.splitlines()
        if len(line.strip(" -\t")) >= 2
    ]


def _clean_text(value: str) -> str:
    value = value.replace("\x00", " ")
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def _join_limited(values: list[str], limit: int) -> str:
    return " ".join(value.strip() for value in values if value.strip())[:limit].strip()


def _append_text(parts: list[str], label: str, value: Any) -> None:
    if isinstance(value, str) and value.strip():
        parts.append(f"{label}: {value.strip()}")


def _append_list(parts: list[str], label: str, value: Any) -> None:
    if isinstance(value, list):
        items = [str(item).strip() for item in value if str(item).strip()]
        if items:
            parts.append(f"{label}: {', '.join(items[:12])}")


def _dedupe(values: Any) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        item = str(value).strip()
        key = item.lower()
        if item and key not in seen:
            seen.add(key)
            result.append(item)
    return result


def _strip_json_wrapper(content: str) -> str:
    stripped = content.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`").strip()
        if stripped.startswith("json"):
            stripped = stripped[4:].strip()
    return stripped


def _summary_metadata(status: str, reason: str | None, attempts: int = 0) -> dict[str, Any]:
    return {
        "status": status,
        "reason": reason,
        "attempts": attempts,
        "updated_at": now_utc().isoformat(),
    }
