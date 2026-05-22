# TimesFM Fit Report For DigitalTwin

Run date: 2026-05-22

## Executive Read

TimesFM is useful for DigitalTwin, but not as a memory or questionnaire engine. It is a time-series forecasting model. The right fit is an admin-only forecasting and anomaly layer for operational metrics, harness trends, completion funnels, and longitudinal participant signals if DigitalTwin later starts collecting them.

Do not put TimesFM in the participant-facing decision path for v1. It does not replace policy-logprob scoring, memory-card ablation, questionnaire lift tests, or the final twin prompt. The immediate value is monitoring: forecast what should happen next, then flag when actual system behavior drifts outside the expected interval.

## Local DigitalTwin Fit

DigitalTwin already records timestamped entities that can become time series:

- `ParticipantToken` has `created_at`, `first_used_at`, `last_seen_at`, and `completed_at`.
- `RawEvent` provides per-step event volume and step-type mix over time.
- `TwinHarnessRun` stores run status, trigger reason, timestamps, and aggregate metrics.
- `TwinHarnessScore` stores lift, information gain bits, KL divergence, verdicts, and score timestamps.
- `CoverageGraphSnapshot` captures readiness snapshots as memory coverage changes.
- `WorkflowRun`, `AnalysisRun`, and `ErrorReport` provide queue, latency, failure, and recovery signals.

Those are enough for admin forecasts such as daily completion count, average harness lift, negative-drift count, readiness growth, error spikes, and analysis backlog. They are not enough for personal-behavior forecasting unless we deliberately collect repeated numeric user signals.

## Capability Match Matrix

| TimesFM Capability | DigitalTwin Use | Fit | Why |
| --- | --- | --- | --- |
| Zero-shot univariate forecasting | Forecast admin metrics without training a bespoke model | High | DigitalTwin has small evolving metrics where classical baselines plus a zero-shot forecaster can be compared quickly. |
| Quantile forecasts | Alert when metrics leave expected bands | High | Harness drift, completion drops, and error spikes are more useful with uncertainty bands than a single point prediction. |
| Batch forecasting | Forecast many token or metric series in one job | Medium | Useful once metrics are materialized, but current repo does not yet have an analytics table. |
| XReg covariates | Include deploys, prompt versions, model names, day-of-week, campaign/source labels | Medium | Good for explaining operational changes, but requires clean covariate logging first. |
| Long context support | Use longer historical windows for mature deployments | Low now, higher later | Current app likely has little historical metric depth. |
| Fine-tuning examples | Domain adaptation for recurrent product metrics | Low now | Premature until we know zero-shot and classical baselines are insufficient. |
| Agent skill and scripts | Reference for safe preflight checks and usage patterns | Medium | The system-check idea is valuable if TimesFM runs locally in Docker. |
| BigQuery ML TimesFM | Cloud-hosted operational forecasting | Medium | Attractive if metrics already move to BigQuery; unnecessary for local-only development. |

## What We Can Use And Why

### Admin Forecasting

Use TimesFM to forecast metrics that change over time:

- token creation and completion volume;
- completion rate by day or cohort;
- median time from token creation to first use;
- median time from first use to completion;
- per-day raw event count by step type;
- analysis and harness queue volume;
- average harness lift and average KL divergence;
- count of `negative_drift`, `zero_impact`, and `policy_displacement` verdicts;
- reviewed-card count and readiness percent over training sessions;
- unresolved error count by category and severity.

This gives the admin dashboard a baseline expectation. If actual data falls outside the forecast interval, the system can say "this is unusual" instead of only showing raw counts.

### Harness Trend Monitoring

The current harness answers whether a card or questionnaire signal helped a held-out decision. TimesFM can answer a different question: is the harness itself trending worse?

Good metrics to forecast:

- average lift per run;
- average information gain bits per run;
- average KL divergence per run;
- negative-drift source count per run;
- unsupported-model run count;
- skipped-target count;
- score count per completed token.

This is especially useful after prompt changes, model changes, questionnaire changes, and memory-card review changes. A sudden drop in average lift or spike in negative drift is a release-quality signal.

### Readiness And Memory Coverage

`CoverageGraphSnapshot` and `memory_readiness_snapshot` can become time series:

- overall readiness percent;
- per-pillar score;
- reviewed-card count;
- draft-card count;
- open duplicate suggestion count.

TimesFM can forecast whether a token's initialization is likely to stall, but only after we have enough repeated snapshots. For now, use it as cohort-level admin monitoring before making per-user claims.

### Operational Anomaly Detection

TimesFM does not have a dedicated anomaly-detection API, but its quantile forecasts can provide prediction intervals. For admin operations, that is enough for a first anomaly layer:

- actual completion count below lower interval;
- unresolved errors above upper interval;
- harness negative drift above upper interval;
- average lift below lower interval;
- queue latency above upper interval.

The anomaly label should stay internal. It should not be shown to participants.

## What Not To Adopt Yet

- Do not use TimesFM to score MCQ, replay, or twin-rank choices. The current logprob harness is the right instrument for discrete decisions.
- Do not use TimesFM as a memory-card quality judge. Card quality is contextual and text-policy-based, not a numeric forecast.
- Do not install PyTorch/JAX into the main FastAPI container until a spike proves value. Keep it in a sidecar worker or offline job first.
- Do not fine-tune TimesFM before zero-shot forecasts and simple classical baselines have been compared.
- Do not forecast individual participant traits from sparse questionnaire data. That is a tiny-data trap wearing a lab coat.

## Recommended V1 Experiment

Build an admin-only forecasting spike with no participant-facing dependency:

1. Add a SQL export or view that materializes daily admin metrics from existing tables.
2. Include at least:
   - date bucket;
   - metric name;
   - metric value;
   - optional dimensions such as model name, prompt version, trigger reason, event type, and token cohort.
3. Run TimesFM outside the main API container using the PyTorch checkpoint.
4. Forecast the next 7 to 14 days for a small set of metrics.
5. Store outputs as an admin diagnostics artifact, not as core product state.
6. Compare against simple baselines:
   - last value;
   - 7-day moving average;
   - seasonal naive if enough weekly history exists.
7. Add an admin panel only if TimesFM beats or usefully complements those baselines.

## Proposed Metric Series

Use stable metric keys so forecast output can be compared across runs:

```text
admin.tokens.created.daily
admin.tokens.completed.daily
admin.tokens.completion_rate.daily
admin.sessions.started.daily
admin.raw_events.count.daily
admin.raw_events.triad.count.daily
admin.raw_events.duel.count.daily
admin.raw_events.context_flip.count.daily
admin.raw_events.twin_rank.count.daily
admin.harness.runs.completed.daily
admin.harness.average_lift.daily
admin.harness.average_kl.daily
admin.harness.negative_drift.count.daily
admin.harness.unsupported_model.count.daily
admin.training.readiness.average.daily
admin.training.reviewed_cards.count.daily
admin.errors.unresolved.count.daily
```

For token-level readiness, use this only when there are enough snapshots:

```text
token.{token_id}.readiness.overall_percent
token.{token_id}.readiness.{pillar_key}.score
token.{token_id}.memory.reviewed_card_count
token.{token_id}.memory.draft_card_count
```

## Integration Shape

Keep TimesFM optional and asynchronous:

- Add a small metrics-export service in the API layer.
- Run forecasting as a background job, scheduled task, or separate worker.
- Store forecast results in a dedicated diagnostics table or JSON artifact.
- Render only admin-facing summaries.
- Fall back cleanly when TimesFM is not installed, model weights are unavailable, or the host lacks memory.

Recommended deployment shape:

```text
Postgres -> metrics export -> TimesFM worker -> forecast diagnostics -> admin dashboard
```

Avoid this shape for v1:

```text
participant answer -> TimesFM -> live twin decision
```

That second version confuses forecasting with decision modeling. We do not need that headache, beloved.

## Data Requirements

TimesFM wants numeric sequences. For DigitalTwin this means we need to create clean, evenly bucketed series:

- one row per metric per time bucket;
- no raw text in the model input;
- explicit missing-bucket handling;
- enough history to beat naive baselines;
- dimensions kept stable over time;
- separate train/evaluation windows for backtests.

For sparse local development data, synthetic smoke tests are fine, but they should not be mistaken for product value.

## Evaluation Plan

Backtest before adoption:

1. Pick metrics with at least a few dozen time buckets.
2. Hold out the most recent buckets.
3. Forecast the holdout window.
4. Compare TimesFM against naive baselines using MAE and RMSE.
5. Check interval coverage for quantile bands.
6. Record whether alerts would have fired correctly.

Success looks like:

- lower error than simple baselines on at least one important metric;
- useful uncertainty intervals for anomaly detection;
- no operational burden on the main app path;
- clear admin action when a metric is anomalous.

Failure looks like:

- noisy forecasts that do not beat moving averages;
- setup complexity larger than the monitoring value;
- local resource pressure from model weights or Torch/JAX;
- forecast results that admins cannot act on.

## Hardware And Packaging Notes

TimesFM 2.5 is the relevant version to inspect first. The current README describes it as a 200M-parameter model with much longer context than earlier versions, continuous quantile forecasting up to long horizons, PyTorch and Flax options, covariate support through XReg, and LoRA fine-tuning examples.

The repo's first-party skill recommends preflight checks for RAM, GPU/VRAM, disk space, Python version, and package installation before loading the model. That is worth copying as a practice even if we do not copy the skill itself.

The package metadata and repo license identify Apache-2.0, which is much cleaner for adoption than the OpenViking license ambiguity found in the earlier report.

## Adoption Decision

Use TimesFM if we want:

- admin forecasting;
- anomaly detection over product and harness metrics;
- forecast bands for release monitoring;
- longitudinal user-signal forecasting after new numeric telemetry exists.

Do not use TimesFM if the goal is:

- memory retrieval;
- questionnaire generation;
- policy logprob scoring;
- card ablation;
- text rationale evaluation;
- deciding which twin response is most human-like.

## Implementation Priority

1. Define a metrics export table or materialized query.
2. Add a local fake forecast adapter for UI/backend plumbing.
3. Run an offline TimesFM notebook or worker against exported metrics.
4. Backtest against naive baselines.
5. Store forecast diagnostics only after the backtest shows value.
6. Add admin dashboard bands and anomaly markers.
7. Revisit cloud BigQuery ML only if metrics move to BigQuery.

## Sources Checked

- TimesFM repository: https://github.com/google-research/timesfm
- Repository README: https://github.com/google-research/timesfm/blob/master/README.md
- Paper: https://arxiv.org/abs/2310.10688
- Google Research blog: https://research.google/blog/a-decoder-only-foundation-model-for-time-series-forecasting/
- Hugging Face collection: https://huggingface.co/collections/google/timesfm-release
- BigQuery TimesFM documentation: https://cloud.google.com/bigquery/docs/timesfm-model
- Agent skill: https://github.com/google-research/timesfm/blob/master/timesfm-forecasting/SKILL.md
- API/config source: https://github.com/google-research/timesfm/blob/master/src/timesfm/configs.py
- Package metadata: https://github.com/google-research/timesfm/blob/master/pyproject.toml
- Repository license: https://github.com/google-research/timesfm/blob/master/LICENSE
