# Digital Twin Prototype

Local-first, Zeabur-friendly implementation scaffold for the Digital Twin direction captured in [`digital-twin-direction.md`](./digital-twin-direction.md).

## Current Phase

**Phase 3: Questionnaire/game scenario flow**

This repository currently includes:

- `apps/api` — FastAPI backend foundation.
- `apps/web` — Next.js frontend foundation.
- PostgreSQL-ready configuration.
- Dockerfiles for web and API services.
- `docker-compose.yml` for local deployment-style development.
- Token/session/event/error database models.
- Health endpoints for service monitoring.
- Admin token-management API and UI shell.
- Token invite entry flow shell.
- Token-based scenario start/resume flow.
- Triads, trade-off duels, context flips, twin-response ranking placeholder, and correction capture.
- Raw event capture for every scenario answer.
- Admin progress summary for participant tokens.
- Reliability-first analysis storage and mock extraction pipeline.

## Architecture

```text
DigitalTwin/
  apps/
    api/   # FastAPI: tokens, sessions, events, LangChain-ready backend hooks
    web/   # Next.js: admin command center + participant scenario shell
  docker-compose.yml
  digital-twin-direction.md
```

## Local Development

### 1. Configure environment

Copy the example env files:

```bash
cp .env.example .env
cp apps/api/.env.example apps/api/.env
cp apps/web/.env.example apps/web/.env.local
```

### 2. Run with Docker Compose

```bash
docker compose up --build
```

Services:

- Web: <http://localhost:3000>
- API: <http://localhost:8000>
- API docs: <http://localhost:8000/docs>
- Postgres: `localhost:5432`

## Key Routes

### Backend

- `GET /health` — API health.
- `GET /health/db` — database health.
- `GET /health/langchain` — LangChain integration placeholder health.
- `POST /api/admin/tokens` — create participant token.
- `GET /api/admin/tokens` — list participant tokens.
- `POST /api/admin/tokens/{token_id}/revoke` — revoke token.
- `POST /api/admin/tokens/{token_id}/reset` — reset token/session state.
- `POST /api/tokens/validate` — validate raw invite token.
- `POST /api/sessions/events` — record participant scenario event.
- `POST /api/sessions/start` — start or resume a token-based scenario session.
- `GET /api/sessions/{session_id}/state` — get current scenario/session state.
- `POST /api/sessions/{session_id}/answer` — save a scenario step answer and advance progress.
- `POST /api/sessions/{session_id}/complete` — mark scenario and token completed.
- `GET /api/admin/tokens/summary` — list participant tokens with progress summary.
- `POST /api/admin/tokens/{token_id}/analyze` — run reliability-first behavioral analysis for a participant token.
- `GET /api/admin/tokens/{token_id}/analysis-runs` — list analysis runs for a participant token.
- `GET /api/admin/analysis-runs/{analysis_run_id}` — inspect analysis artifacts and evidence for one run.
- `GET /api/admin/tokens/{token_id}/evidence` — list accepted behavioral evidence for a participant token.

### Frontend

- `/admin` — command-center dashboard shell.
- `/admin/tokens` — token management UI shell.
- `/play/[token]` — participant invite entry route.

## Phase 3 Scenario Flow

The participant flow currently includes:

1. Intro / behavioral mirror framing.
2. Three triad prompts.
3. Three trade-off duels.
4. Two context-flip prompts.
5. One preliminary twin-response ranking step.
6. One correction/reflection step.
7. Completion screen.

Every submitted step is stored as a raw event tied to the participant token and session. These events are the evidence source for the future LangChain evidence extractor in Phase 4.

## Reliability-First Analysis Direction

LangChain analysis should optimize for reliability, traceability, and correction quality over token savings.

The analysis design favors:

- multi-pass extraction instead of one compressed prompt,
- structured outputs,
- source event IDs for every claim,
- supporting quotes where available,
- prompt/model version tracking,
- stored intermediate artifacts,
- validation status and confidence per artifact/evidence item,
- mock/local fallback when no LLM provider is configured.

Current Phase 4 foundation includes:

- `analysis_runs` for tracking analysis jobs,
- `analysis_artifacts` for intermediate outputs,
- `behavioral_evidence` for accepted evidence claims,
- deterministic extraction for structured triads, duels, and rankings,
- mock reliability-first extraction for open-ended context flips and corrections.

Open-ended answers are intentionally flagged with `requires_llm_review` so a later real LangChain pass can apply deeper context-flip and correction analysis.

## Zeabur / Wonder Mesh Notes

The project is structured to deploy as separate services:

1. **API service** from `apps/api/Dockerfile`.
2. **Web service** from `apps/web/Dockerfile`.
3. **PostgreSQL service** managed by Zeabur or deployed in the same project.

Suggested production environment variables:

- API: `DATABASE_URL`, `APP_SECRET_KEY`, `CORS_ORIGINS`, `PUBLIC_WEB_URL`
- Web: `NEXT_PUBLIC_API_BASE_URL`

For Wonder Mesh, deploy services to a Zeabur-managed server once the device has joined the mesh and K3s is installed from the Zeabur console.

## Implementation Phases

1. **Foundation** — app scaffolding, Docker, health checks, token/session models.
2. **Token handling** — admin-generated invite tokens and participant progress tracking.
3. **Questionnaire/game flow** — triads, trade-off duels, context flips, rankings, corrections.
4. **LangChain workflow layer** — evidence extraction, workflow run tracking, errors.
5. **Twin Command Center** — OpenClaw-style monitoring dashboard.
6. **Deployment hardening** — Zeabur deploy docs, logs, reporting, persistence, auth hardening.