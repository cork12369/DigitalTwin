# OpenViking Analysis Sources

## Primary Repository

- OpenViking GitHub repository: https://github.com/volcengine/OpenViking
- Repository README: https://github.com/volcengine/OpenViking/blob/main/README.md
- PyPI/build metadata: https://raw.githubusercontent.com/volcengine/OpenViking/main/pyproject.toml
- License: https://raw.githubusercontent.com/volcengine/OpenViking/main/LICENSE
- Docker Compose example: https://raw.githubusercontent.com/volcengine/OpenViking/main/docker-compose.yml
- Latest DigitalTwin fit report: ./fit-report-2026-05-22.md

## Documentation

- Docs home: https://docs.openviking.ai/
- API overview: https://docs.openviking.ai/en/api/01-overview
- Resource management: https://docs.openviking.ai/en/api/02-resources
- File system API: https://docs.openviking.ai/en/api/03-filesystem
- Skills API: https://docs.openviking.ai/en/api/04-skills
- Sessions API: https://docs.openviking.ai/en/api/05-sessions
- Retrieval API: https://docs.openviking.ai/en/api/06-retrieval
- System and monitoring: https://docs.openviking.ai/en/api/07-system
- Metrics: https://docs.openviking.ai/en/api/09-metrics

## Integrations

- MCP integration guide: https://docs.openviking.ai/en/guides/06-mcp-integration
- Agent integrations overview: https://docs.openviking.ai/en/agent-integrations/01-overview
- Codex memory plugin: https://docs.openviking.ai/en/agent-integrations/04-codex
- LangChain and LangGraph integration: https://docs.openviking.ai/en/agent-integrations/06-langchain-langgraph

## Notes For DigitalTwin

- Treat OpenViking as an optional context sidecar first.
- Keep DigitalTwin Postgres tables authoritative for participant tokens, raw events, reviewed memory cards, and harness results.
- Use OpenViking retrieval output as measurable evidence in the admin harness before changing live twin prompts.
- Review AGPL-3.0 implications before vendoring code or modifying OpenViking for hosted product use.
- As of this analysis pass, repo metadata and `LICENSE` say AGPL-3.0, while some docs pages display an Apache-2.0 footer; treat this as a license ambiguity until confirmed.

## TimesFM Analysis

- Latest DigitalTwin fit report: ./timesfm-fit-report-2026-05-22.md
- TimesFM GitHub repository: https://github.com/google-research/timesfm
- Repository README: https://github.com/google-research/timesfm/blob/master/README.md
- Paper: https://arxiv.org/abs/2310.10688
- Google Research blog: https://research.google/blog/a-decoder-only-foundation-model-for-time-series-forecasting/
- Hugging Face collection: https://huggingface.co/collections/google/timesfm-release
- BigQuery TimesFM documentation: https://cloud.google.com/bigquery/docs/timesfm-model
- Agent skill: https://github.com/google-research/timesfm/blob/master/timesfm-forecasting/SKILL.md
- Forecast config source: https://github.com/google-research/timesfm/blob/master/src/timesfm/configs.py
- Package metadata: https://github.com/google-research/timesfm/blob/master/pyproject.toml
- License: https://github.com/google-research/timesfm/blob/master/LICENSE

## TimesFM Notes For DigitalTwin

- Treat TimesFM as optional admin forecasting and anomaly-detection infrastructure, not as memory retrieval or policy scoring.
- Start with operational metrics and harness trends already present in Postgres timestamps and aggregate metrics.
- Keep any PyTorch/JAX dependency out of the participant-facing API path until a backtest beats simple baselines.
- Repo metadata and `LICENSE` identify Apache-2.0.
