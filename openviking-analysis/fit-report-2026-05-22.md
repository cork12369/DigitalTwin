# OpenViking Fit Report For DigitalTwin

Run date: 2026-05-22

## Executive Read

OpenViking is worth using, but only as an optional context sidecar and diagnostics layer first. It should not replace DigitalTwin's current Postgres-backed participant events, reviewed memory cards, or harness tables.

The best near-term use is retrieval comparison: mirror reviewed cards and questionnaire evidence into OpenViking, retrieve candidate context for held-out decisions, then score those retrieved sources with the existing harness. That gives us a measurable answer to the real question: does OpenViking select better twin context than our current hand-rolled source selection?

## Local DigitalTwin Fit

DigitalTwin already has the right primitives for a controlled OpenViking spike:

- `RawEvent` stores questionnaire, replay, and ranking answers with step snapshots.
- `MemoryCard` stores reviewed/draft card bodies, source quotes, priority, and pillar links.
- `TrainingChatMessage` and `MemoryCompactionRun` already model the initialization-chat-to-memory-card pipeline.
- `TwinHarnessRun`, `TwinHarnessCase`, and `TwinHarnessScore` can evaluate source impact through policy-likelihood lift, information gain bits, and KL divergence.
- `harness_service.py` already has `_memory_sources()` and `_questionnaire_sources()` as clean insertion points for an alternate source provider.

This means OpenViking does not need to sit in the participant-facing path. It can be tested behind admin diagnostics without changing the live quiz or training UX.

## Capability Match Matrix

| OpenViking Capability | DigitalTwin Use | Fit | Why |
| --- | --- | --- | --- |
| `viking://` filesystem hierarchy | Stable URIs for cards/events | High | Our admin harness needs source traceability, and URI paths can encode token/source identity. |
| L0/L1/L2 layered context | Card/event summaries and full evidence reads | High | We need quick source selection plus deep readback for debugging. |
| Semantic and session-aware search | Candidate context retrieval | High | Directly testable against current Postgres source selection. |
| `grep`, `glob`, `list`, `read` | Admin context inspection | High | Helps explain why a source was selected or missed. |
| Resource ingestion | CVs, docs, imported transcripts, repo context | Medium | Useful later; less urgent than memory/event retrieval. |
| Session commit/extract | Initialization-chat memory extraction | Medium | Conceptually aligned, but current reviewed-card workflow should remain authoritative. |
| MCP endpoint | Admin/debug agents | Medium | Good for internal tools, risky for participant-facing agents unless scoped read-only. |
| LangChain/LangGraph adapters | Future agent workflow backend | Low now, higher later | DigitalTwin is not currently built around LangGraph. |

## Recommended V1 Experiment

Build a docs-only or admin-only OpenViking spike with no participant-facing dependency:

1. Run OpenViking as a sidecar on port `1933`.
2. Configure it with a separate workspace volume and API key.
3. Add a small backend client that supports health, write/update, search/find, and read.
4. Mirror one completed token's reviewed cards and questionnaire events into OpenViking.
5. Add a harness mode that compares:
   - current Postgres source selection;
   - OpenViking retrieved sources;
   - overlap between both sets;
   - lift/KL/verdict deltas by source.

The success metric should be behavioral, not architectural. OpenViking is useful if retrieved sources improve held-out discrete-choice prediction or reduce inert/negative-drift context.

## Proposed URI Layout

Use stable paths that preserve local source identity:

```text
viking://user/memories/digitaltwin/{token_id}/profile
viking://user/memories/digitaltwin/{token_id}/questionnaire/{event_id}
viking://user/memories/digitaltwin/{token_id}/replay/{replay_scenario_id}/{event_id}
viking://user/memories/digitaltwin/{token_id}/cards/{card_id}
viking://resources/digitaltwin/imports/{token_id}/{resource_id}
```

Each mirrored entry should include local metadata:

- `token_id`
- `source_type`
- `source_id`
- `step_type` or card status
- `replay_scenario_id` when present
- `created_at` or `updated_at`
- current DigitalTwin URL/path for admin drillback when available

## Harness Extension Shape

Do not replace existing harness scoring. Add a second source provider and compare outputs.

Current provider:

- reviewed `MemoryCard` rows;
- relevant `RawEvent` rows;
- deterministic prompt;
- model logprobs required.

OpenViking provider:

- query OpenViking with the held-out situation and candidate actions;
- target only the token-scoped `viking://user/memories/digitaltwin/{token_id}` namespace;
- retrieve top sources with URI, layer, score, and content excerpt;
- map retrieved URIs back to local `card_id` or `event_id`;
- score retrieved sources through the same lift/KL machinery.

New aggregate metrics should include:

- retrieval overlap with Postgres provider;
- average lift by provider;
- negative-drift count by provider;
- inert-source count by provider;
- missing-source cases where OpenViking retrieves no usable local source;
- source trace coverage percentage.

## Adoption Decision

Use OpenViking if the spike shows at least one of these:

- higher average lift than current source selection;
- fewer negative-drift sources;
- fewer inert sources for the same case set;
- better admin explainability through retrieved URI traces;
- useful ingestion of external/profile resources that would be expensive to parse ourselves.

Do not adopt it into live prompts if:

- retrieval quality is not measurably better;
- source IDs cannot be reliably mapped back to local events/cards;
- OpenViking unavailability creates participant-facing failures;
- licensing review blocks hosted/modified use.

## Risks And Constraints

### License ambiguity

The repository `LICENSE` and `pyproject.toml` identify OpenViking as AGPL-3.0, while some docs pages currently display an Apache-2.0 footer. Treat this as unresolved until verified with the project maintainers or legal review. For now, prefer sidecar/runtime integration and avoid vendoring or modifying OpenViking code.

### Operational dependency

OpenViking adds another model/embedding/storage service. DigitalTwin should continue to work when it is unconfigured or down.

### Retrieval contamination

If we mirror generated context back into OpenViking without source labels, future retrieval may amplify the model's own interpretations instead of the user's evidence. Mirrored entries need source type and local source ID.

### Participant privacy

OpenViking would store participant-derived memory. Keep token namespaces separated, avoid cross-token retrieval, and do not expose MCP write/delete tools to untrusted agents.

## Implementation Priority

1. Admin-only sidecar health and config.
2. Mirror reviewed cards and questionnaire events.
3. Run retrieval comparison in the harness.
4. Add admin UI source traces.
5. Only then consider live prompt retrieval.

## Sources Checked

- OpenViking repository: https://github.com/volcengine/OpenViking
- API overview: https://docs.openviking.ai/en/api/01-overview
- Resource management: https://docs.openviking.ai/en/api/02-resources
- Sessions API: https://docs.openviking.ai/en/api/05-sessions
- Retrieval API: https://docs.openviking.ai/en/api/06-retrieval
- MCP integration: https://docs.openviking.ai/en/guides/06-mcp-integration
- LangChain/LangGraph integration: https://docs.openviking.ai/en/agent-integrations/06-langchain-langgraph
- Repository license: https://raw.githubusercontent.com/volcengine/OpenViking/main/LICENSE
- Package metadata: https://raw.githubusercontent.com/volcengine/OpenViking/main/pyproject.toml
