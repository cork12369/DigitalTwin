# OpenViking Analysis For DigitalTwin

## Summary

OpenViking is an open-source context database for AI agents. Its core idea is to manage context as a navigable filesystem instead of a flat vector pile: memories, resources, and skills live under stable `viking://` paths, with lightweight abstracts, overviews, and full-detail reads.

For DigitalTwin, OpenViking is most useful as an optional sidecar context backend. It should not replace the questionnaire, replay flow, memory-card review loop, or harness. The best v1 use is to make memory and questionnaire context easier to retrieve, inspect, and compare against the existing Postgres-backed behavior.

Latest concrete fit report: [fit-report-2026-05-22.md](./fit-report-2026-05-22.md)

Related report in this folder: [timesfm-fit-report-2026-05-22.md](./timesfm-fit-report-2026-05-22.md)

## What We Can Use And Why

### Hierarchical Context Storage

OpenViking stores context under filesystem-like `viking://` URIs and produces layered context:

- L0 abstract for quick relevance checks.
- L1 overview for planning and source selection.
- L2 full content for deep reads.

This maps cleanly to DigitalTwin memory cards and questionnaire evidence because we need inspectable context, not a hidden blob stuffed into the final prompt.

### Retrieval And Debugging

OpenViking exposes semantic search, session-aware search, exact grep, glob, directory listing, and content reads. That is directly useful for the admin harness because we can compare:

- which Postgres memory cards we would inject;
- which OpenViking sources it retrieves;
- whether retrieved sources improve or damage policy-likelihood lift.

This gives us a practical way to debug context selection before changing participant-facing flows.

### Resource Ingestion

OpenViking can ingest docs, URLs, repos, code, markdown, PDFs, Office files, and other resource formats. That could help with:

- participant-uploaded CV/profile material;
- imported chat transcripts;
- external docs the twin should understand;
- future repo/resource context for agentic workflows.

This is more attractive than writing parsers for every format inside the DigitalTwin API.

### Session Memory Extraction

OpenViking has a session model that can capture turns, commit sessions, and extract memories asynchronously. This is close to DigitalTwin's initialization chat and memory-card compaction flow.

The immediate value is as a reference design or optional mirror. The current reviewed-card workflow should remain authoritative until OpenViking retrieval and extraction prove measurable lift in the harness.

### MCP And Agent Integrations

OpenViking exposes an MCP endpoint and has integrations for Codex, Claude Code, LangChain, and LangGraph. This is useful later if we want admin/debug agents to search or read DigitalTwin context without custom one-off tools.

For the product app itself, the safer starting point is the HTTP API or Python SDK from the FastAPI backend, not exposing write/delete MCP tools to user-facing agents.

## Recommended DigitalTwin Integration Shape

Add OpenViking as an optional local sidecar, not a hard dependency:

- Run OpenViking separately on port `1933`, with its own workspace volume and API key.
- Add an API-side `OpenVikingContextClient` behind feature flags or empty-config fallback.
- Mirror reviewed memory cards to paths like `viking://user/memories/{token_id}/cards/{card_id}`.
- Mirror questionnaire and replay evidence to paths like `viking://user/memories/{token_id}/questionnaire/{event_id}`.
- Store stable source metadata so every retrieved OpenViking URI links back to a local `MemoryCard` or `RawEvent`.
- Keep Postgres as the source of truth for participants, events, cards, reviews, and harness results.

The first feature should be admin-only retrieval comparison:

- current Postgres-selected context;
- OpenViking-retrieved context;
- retrieved URIs, match scores, context layer used, and source type;
- harness lift/KL comparison for both source-selection paths.

## What Not To Adopt Yet

- Do not vendor OpenViking code into DigitalTwin.
- Do not replace reviewed memory cards with OpenViking memories in v1.
- Do not make participant completion, training chat, or twin prompt generation depend on OpenViking availability.
- Do not expose destructive OpenViking operations like `forget` to untrusted or participant-facing agents.
- Do not treat OpenViking extraction as ground truth until harness scores show it improves discrete-choice prediction.

One practical reason to be careful: the OpenViking GitHub repo and package metadata currently identify the project as AGPL-3.0, while some docs pages display an Apache-2.0 footer. Treat the license posture as unresolved until verified. Sidecar use is much lower-risk than copying or modifying its code inside this repo.

## Spike Plan

1. Stand up OpenViking locally with Docker.
2. Configure an API key and verify `/health`.
3. Add a small admin-only backend client for `add_resource`, `search/find`, `content/read`, and health checks.
4. Mirror one completed participant token's reviewed cards and questionnaire events into OpenViking.
5. Add an admin diagnostics view comparing Postgres source selection with OpenViking retrieval.
6. Run the harness with both source sets and compare lift, information gain bits, KL divergence, inert-source count, and negative-drift count.

## Acceptance Criteria For A Real Integration

- DigitalTwin works normally when OpenViking is absent or unhealthy.
- Mirrored OpenViking entries link back to local card/event IDs.
- Admins can see what was retrieved and why it was used.
- Harness results show whether OpenViking retrieval improves prediction quality.
- No participant-facing prompt changes happen until the admin harness supports the change.

## Assumptions And Risks

- The intended use is product diagnostics and future retrieval, not replacing the app's current data model.
- The first useful win is observability: showing what context is retrieved and whether it helps.
- The AGPL license should be reviewed before any code vendoring, modification, or hosted derivative work.
- OpenViking's model/provider setup adds another operational dependency, so it should start as optional.
