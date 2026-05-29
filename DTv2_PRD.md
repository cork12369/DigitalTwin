# Product Requirements Document — Digital Twin Platform V2

**Subtitle:** Decision-Driven Policy Fidelity with Auditable Lineage
**Status:** Draft v2.0 · 2026-05-22
**Owner:** [project lead]
**Target cohort:** C-suite participants, ~1-hour calibration sessions
**Cohort size for first iteration:** 1 participant at a time, co-present admin

---

## 0. Document conventions

- **Card** = a single durable claim about the participant (a policy, trait, fact, or pattern).
- **Pillar** = one of 5 decision-process axes used for coverage tracking.
- **Type** = one of 6 categorical labels describing what kind of claim a card asserts.
- **Δw** = the directional weight adjustment applied to a card's pillar link when a subagent evaluation reinforces or contradicts it.
- **Event** = a single `RawEvent` row, typically a participant's answer to a probe or chat message.
- **Subagent** = an independent LLM evaluator that scores participant answers against the current card deck.
- **Variant** = a captured snapshot of session config (Δw matrix, subagent model, prompt template) — used for A/B reproducibility.

---

## 1. Executive Summary

### 1.1 Thesis

V1 modeled the participant as a *text style* via post-hoc chat compaction. V2 models the participant as a *conditional decision policy*:

$$\pi_{\text{twin}}(a \mid s, h, z) \approx \pi_{\text{human}}(a \mid s, h, z)$$

where $s$ is the objective scenario, $h$ is prior context for this participant, and $z$ is the twin's internal state (active card weights, pillar scores). Stylistic mimicry is a downstream byproduct, not the optimization target.

### 1.2 Why this matters

Stated-preference instruments correlate weakly with behavior ($r \le 0.11$ in the behavioral-economics literature). V2 anchors the model to revealed preference via forced-choice trade-offs and open chat, with an independent subagent updating card weights in response to each answer — keeping the choice-policy loop separate from the generation-style loop.

### 1.3 Operational envelope

- **Co-present, localhost-only** for the V2 calibration cohort. No multi-tenant auth, no remote sessions.
- **Single participant per session.** Admin is in the room and has live visibility into model state.
- **Soft 1-hour budget.** Not a hard cap, but a guideline driven by the C-suite cohort's available time.
- **Known participants.** Admin can vet the pre-seeded card deck before activation.
- **No re-do assumption.** Architecture must produce a usable twin from partial session data; session abort produces a *preliminary* calibration, not a failure.

### 1.4 Out of scope for V2

- Multi-tenant auth
- Remote / non-co-present sessions
- Migration from V1 data (no preservation required; V3 will ship with a fresh DB)
- Participant-facing accounts

---

## 2. Objectives & Success Metrics

### 2.1 Primary objectives

1. **Auditable lineage.** Every Δw on every card traces to a specific `RawEvent`. No anonymous updates.
2. **Live experimentation.** Admins can tune Δw config in-session with versioned snapshots.
3. **Revealed-preference fidelity.** Twin's predicted action distribution matches the participant's observed choices on held-out probes within the session.
4. **C-suite-viable experience.** Session must feel valuable to the participant in real time, not just to the researcher post-hoc.

### 2.2 Success metrics

| Metric | Target | Baseline to beat | Holdout construction |
|---|---|---|---|
| Categorical policy accuracy | ≥ 0.70 (stretch 0.80) | Majority-class per domain | 10–15 events tagged as `holdout_slot=true` at session start |
| Pairwise preference (A/B) | ≥ 0.80 agreement | 0.50 (random) | Held-out duels not used in training |
| Brier score | ≤ 0.18 | Brier of always-majority predictor | Same holdout |
| ECE (adaptive equal-mass bins) | See bands below | n/a | Same holdout; bootstrap CI reported when N < 30 |

### 2.3 ECE calibration bands

| Band | Range | Gate action |
|---|---|---|
| Green | ECE < 0.05 | Ship. Admin badge: green. |
| Amber | 0.05 ≤ ECE < 0.10 | Ship with warning. Downstream consumers must use full distribution, not point estimates. Admin badge: amber. |
| Red | ECE ≥ 0.10 | Do not ship. Run temperature recalibration; if still red, revisit Δw matrix. Admin badge: red. |

### 2.4 Anti-goals

- Not optimizing for stylistic similarity to the participant's prose.
- Not building a general-purpose chatbot.
- Not multi-tenant in V2.
- Not preserving V1 data (clean break for V3).

---

## 3. Architecture

### 3.1 Card model — pillars × types

Cards have **two orthogonal labels**:

**Pillars (5)** — track coverage of decision-process aspects:

| Pillar key | Description |
|---|---|
| `situation_framing` | How the user defines situations, notices cues, and identifies what others miss. |
| `option_generation` | Which actions feel available, impossible, or socially off-limits. |
| `valuation_expectancies` | How outcomes are weighed (analogies, risk, emotion, expected consequences). |
| `counterfactual_stress` | What changes the user's decision; lines they will not cross under pressure. |
| `feedback_integration` | How outcomes update self-story, future policy, interpretation of success/failure. |

**Types (6)** — describe what kind of claim the card makes:

| Type | Description | Typical source |
|---|---|---|
| `biographical` | Static facts about the person | CV / profile ingestion |
| `disposition` | Durable trait or default preference | CV inference + early probes |
| `trigger` | Conditional policy — *if X then behavior shifts* | context_flip + duel probes |
| `stylistic` | Communication / presentation patterns | Chat phase + free-text |
| `competence` | Capability or methodology preference | CV + technical probes |
| `relational` | Patterns around specific roles/people | Chat phase + targeted probes |

Pillars and types are independent. A card can have `pillar=counterfactual_stress, type=trigger`. Biographical and stylistic cards typically have no pillar (`pillar_links` is empty).

### 3.2 The Δw matrix

Per variant, store a `step_type × polarity` matrix:

| Step type | Reinforce | Contradict |
|---|---|---|
| `triad` | 0.30 | 0.45 |
| `duel` | 0.50 | 0.65 |
| `context_flip` | 0.20 | 0.30 |
| `correction` | 0.40 | 0.55 |
| `twin_rank` | 0.35 | 0.50 |
| `indifference` | 0.00 | 0.00 |
| `chat_extract` | 0.15 | 0.20 |

**Rationale for asymmetric defaults:**
- `duel > triad > context_flip` — forced binary is the strongest signal; context_flip is the weakest because the participant may be performing for the reframe.
- `contradict > reinforce` within each row — acquiescence bias makes "yes I'd do that" cheaper than "no I wouldn't."

**Confidence scaling.** Subagent emits confidence $c \in [0, 1]$. Actual delta applied:

$$\Delta w_{\text{actual}} = \text{sign}(\text{polarity}) \cdot M[\text{step\_type}][\text{polarity}] \cdot c$$

If $c < 0.4$, abstain ($\Delta w = 0$) and log the abstention.

**Custom-text answers** produce a graded position on the [-1, +1] spectrum (instead of binary polarity), and Δw is scaled by both the position magnitude and the confidence.

### 3.3 Type-relevance filter

Subagent only evaluates cards whose type is relevant to the current step type. Filter is in code, not data:

| Step type | Relevant card types |
|---|---|
| `triad` | disposition, trigger |
| `duel` | disposition, trigger, competence |
| `context_flip` | trigger |
| `correction` | stylistic, disposition |
| `twin_rank` | disposition, trigger, stylistic, competence, relational (all except biographical) |
| `chat_extract` | all except biographical |

**No further pre-filtering** beyond type relevance. At V2 scale (~20-25 cards per deck), embedding-based pre-filtering would cost more in false negatives (filtered-out contradictions) than it would save in latency.

**Biographical cards are never updated.** They have weight 1.0 from creation, used only as grounding context in the subagent's prompt. They do not participate in the Δw loop.

### 3.4 Unbiased Activation Subagent

**Model:** `deepseek/deepseek-v4-pro` via OpenRouter. `reasoning_effort=high`. `temperature=0`.

**Contract:**

```python
class SubagentVerdict(TypedDict):
    card_id: str
    polarity: Literal["reinforce", "contradict", "abstain"]
    confidence: float        # 0.0–1.0
    rationale: str           # for audit log, not for participant
    spectrum_position: float | None  # for custom-text answers, [-1.0, 1.0]

class SubagentResponse(TypedDict):
    verdicts: list[SubagentVerdict]
    unanchored: bool         # true if no card matched above threshold
    unanchored_note: str | None  # structured note describing what the choice revealed
```

**Execution rules:**

- Temperature 0 for determinism.
- Hard timeout: 8 seconds. On timeout → log `subagent_timeout` event, apply `Δw = 0` (treat as abstention).
- On malformed JSON → one retry with stricter schema instruction, then abstain + `ErrorReport` row.
- On provider outage → queue in `pending_subagent_evals` table, process on recovery. Session continues; participant never blocks on subagent latency.
- Runs async after the participant sees the next probe — must not block UI.
- **Max 4 cards moved per event.** If subagent surfaces more than 4 matches above threshold, take the top 4 by confidence and log the overage.

**Internal contradiction preservation.** Cards receiving opposing Δw from the same event both update. Never normalize, never average. This is the structural feature that makes conditional policies visible.

### 3.5 Pre-seeded card deck

Generated before session start from `profile_structured_context` and `profile_llm_summary`. Admin reviews and edits via the pre-seed UI (§7.4) before activating the token.

**Expected composition for first calibration sessions:**
- 4-6 `biographical` cards (immutable context)
- 4-6 `disposition` cards (durable preferences inferred from CV)
- 1-2 `competence` cards
- 0-2 `relational` cards (if profile mentions specific roles/orgs)

`trigger` and `stylistic` cards are expected to emerge mid-session via mini-compaction.

### 3.6 Mini-compaction (mid-session card creation)

Runs every ~8-10 events or whenever ≥3 `unanchored` notes accumulate.

- Reads recent event window + unanchored notes.
- Proposes 0-3 new cards, each tagged with `source_event_ids`.
- Each new card includes `card_type` (required, validated against the 6 types).
- New cards enter as `status='draft'` with weight 0.
- Dedup check inline using existing `MemoryCardDuplicateSuggestion` machinery; if similarity > 0.76 to an existing card, no new card is created — the unanchored signal is routed to the matched card as evidence instead.
- Draft cards become eligible for subagent evaluation on subsequent events.
- Draft cards auto-promote to `reviewed` after N=3 reinforcements with confidence ≥ 0.5.

**Model:** `deepseek/deepseek-v4-pro` with `reasoning_effort=xhigh` (deeper extraction, less latency-sensitive).

### 3.7 Adaptive probe selector

Replaces the static sequential flow in current `adaptive_scenario_service.py`. Selector chooses next probe by expected information gain:

- Prioritizes pillars with score < 60% of target.
- Prioritizes cards with `|cumulative_delta_w| < 0.5` (uncertain).
- Prioritizes card types with zero coverage in recent events.
- Rotates step types every 5-7 probes (variety beats depth for C-suite cohort).
- Admin can override next step type via `dynamic_flow_modifiers.override_next_type`.

### 3.8 Calibration evaluation

Held-out events tagged at session start (`raw_events.holdout_slot=true`). Subagent does NOT update weights from holdout events; instead the twin produces a predicted distribution for each holdout probe.

At session end (or session abort):
1. Compute accuracy, Brier, and ECE (adaptive equal-mass bins) on filled holdout slots.
2. Assign calibration band (green/amber/red).
3. Persist `calibration_band`, `calibration_ece`, `calibration_temperature` on `participant_tokens`.
4. If red, run temperature scaling: fit scalar $T$ on holdout to minimize NLL. Re-evaluate ECE post-fit.
5. If still red after temperature fit, escalate to admin (no chat mode access).

### 3.9 Chat mode (A/C hybrid)

After calibration band is assigned green or amber, the twin enters chat mode.

**Architecture:** Chat surface (Option A) where every twin response is generated by first predicting an action via the card deck (Option C), then producing prose grounded in stylistic cards.

**Generation pipeline per chat turn:**
1. Twin receives chat input.
2. Subagent (same instance as calibration) predicts action distribution via active card weights.
3. Stylistic cards inform tone/voice prompt.
4. Final response generated by main model conditioned on (a) predicted action, (b) stylistic constraints, (c) biographical context.

**Calibration band gating:**
- Green: twin returns point estimates freely.
- Amber: twin must surface distribution (UI shows uncertainty), no confident point estimates.
- Red: chat mode locked.

### 3.10 Downstream consumer contract

Any service consuming `π_twin` predictions must check `calibration_band`:

```python
def use_twin_prediction(token_id: str) -> Prediction:
    band = get_calibration_band(token_id)
    raw = pi_twin.predict(token_id)
    if band == "red":
        raise CalibrationBlockedError(token_id)
    if band == "amber":
        return Prediction(distribution=raw.distribution, point_estimate=None)
    return Prediction(distribution=raw.distribution, point_estimate=raw.argmax)
```

---

## 4. Data Model — Schema Additions

All additions to existing tables defined in `app/models.py`. No migration apparatus required (clean DB rebuild for V3 ship).

### 4.1 New tables

#### `experiment_variants`
Captures session configuration snapshots for reproducibility.

| Column | Type | Notes |
|---|---|---|
| `id` | VARCHAR(36) PK | uuid |
| `label` | VARCHAR(255) | e.g. `v2_default` |
| `delta_w_matrix` | JSON | Full matrix |
| `subagent_model_id` | VARCHAR(255) | e.g. `deepseek/deepseek-v4-pro` |
| `subagent_reasoning_effort` | VARCHAR(20) | `high` or `xhigh` |
| `compaction_model_id` | VARCHAR(255) | |
| `prompt_template_hash` | VARCHAR(64) | |
| `session_time_budget_seconds` | INTEGER | Default 3600 |
| `target_accuracy_band` | JSON | `{"min": 0.70, "max": 0.80}` |
| `created_at` | TIMESTAMP | |

UNIQUE on `(label, prompt_template_hash, subagent_model_id)`.

#### `config_events`
Logs every mid-session variant change (admin slider tweaks).

| Column | Type |
|---|---|
| `id` | VARCHAR(36) PK |
| `token_id` | FK → `participant_tokens.id` |
| `variant_id_before` | FK → `experiment_variants.id` |
| `variant_id_after` | FK → `experiment_variants.id` |
| `changed_by` | VARCHAR(255) — admin identifier |
| `created_at` | TIMESTAMP |

#### `subagent_verdicts`
Per-evaluation lineage. The trace visualizer reads from this.

| Column | Type |
|---|---|
| `id` | VARCHAR(36) PK |
| `raw_event_id` | FK → `raw_events.id` |
| `token_id` | FK → `participant_tokens.id` |
| `variant_id` | FK → `experiment_variants.id` |
| `card_id` | FK → `memory_cards.id` |
| `polarity` | VARCHAR(16) — `reinforce`/`contradict`/`abstain` |
| `confidence` | FLOAT |
| `spectrum_position` | FLOAT NULLABLE |
| `delta_w_applied` | FLOAT |
| `rationale` | TEXT |
| `model_latency_ms` | INTEGER |
| `created_at` | TIMESTAMP |

Indexed on `raw_event_id` and `card_id`.

#### `pending_subagent_evals`
Provider-outage retry queue.

| Column | Type |
|---|---|
| `id` | VARCHAR(36) PK |
| `raw_event_id` | FK |
| `token_id` | FK |
| `variant_id` | FK |
| `attempts` | INTEGER DEFAULT 0 |
| `last_error` | TEXT |
| `created_at` | TIMESTAMP |
| `processed_at` | TIMESTAMP NULLABLE |

Partial index on `(processed_at) WHERE processed_at IS NULL`.

### 4.2 Column additions on existing tables

#### `participant_tokens`
- `active_experiment_variant_id` — FK → `experiment_variants.id`
- `dynamic_flow_modifiers` — JSON DEFAULT `'{}'`
- `calibration_band` — VARCHAR(16) DEFAULT `'unmeasured'`
- `calibration_ece` — FLOAT NULLABLE
- `calibration_temperature` — FLOAT DEFAULT 1.0
- `session_started_at` — TIMESTAMP NULLABLE
- `session_time_budget_seconds` — INTEGER DEFAULT 3600
- `session_abort_reason` — VARCHAR(80) NULLABLE
- `briefing_acknowledged_at` — TIMESTAMP NULLABLE

#### `memory_cards`
- `card_type` — VARCHAR(20) NOT NULL — one of the 6 types
- `seed_source` — VARCHAR(40) — `profile`, `cv`, `compaction`, `manual`
- `promoted_at` — TIMESTAMP NULLABLE — when draft → reviewed
- `reinforcement_count` — INTEGER DEFAULT 0

#### `memory_card_pillar_links`
- `source_event_id` — FK → `raw_events.id` NULLABLE (nullable for seed-deck links with no causal event)
- `cumulative_delta_w` — FLOAT NOT NULL DEFAULT 0.0
- `update_count` — INTEGER NOT NULL DEFAULT 0
- `last_updated_at` — TIMESTAMP NULLABLE

#### `raw_events`
- `holdout_slot` — BOOLEAN NOT NULL DEFAULT FALSE
- `holdout_partition` — VARCHAR(40) NULLABLE
- `answer_mode` — VARCHAR(20) — `binary`, `indifferent`, `custom_text`, `chat`

### 4.3 Indexes

- `idx_subagent_verdicts_event` on `subagent_verdicts(raw_event_id)`
- `idx_subagent_verdicts_card` on `subagent_verdicts(card_id)`
- `idx_pending_subagent_unprocessed` on `pending_subagent_evals(processed_at) WHERE processed_at IS NULL`
- `idx_raw_events_holdout` on `raw_events(token_id, holdout_slot)`

---

## 5. Session Lifecycle

### 5.1 Pre-session (T−1 week to T−30 min, async, admin-driven)

1. Admin uploads CV / profile content via existing ingestion.
2. System runs profile structuring → produces `profile_structured_context` + `profile_llm_summary`.
3. System generates pre-seeded card deck (10-15 cards).
4. System generates probe pool (~80 candidate questions across all 5 pillars and relevant step types).
5. System reserves 10-15 of the probe pool as holdout slots (tagged but not shown until §5.5).
6. **Admin reviews & edits the deck** (§7.4). Adds/removes/edits cards. Clicks "Ready to activate" when satisfied.
7. Token activates. Participant link (`/play/[token]`) becomes usable.

### 5.2 Warmup (T+0 → T+5 min)

- Participant arrives. Admin pairs them with token.
- Brief framing (90 seconds max) — see §6.1 for content principles.
- 3-5 obvious questions to settle in. These produce `RawEvent`s but Δw is held at 0 (warmup events flagged).
- Participant gets first glimpse of the "live learning" panel (§6.2).

### 5.3 Main probe phase (T+5 → T+30 min)

- ~25 forced-choice probes drawn adaptively (§3.7).
- Rotates between `triad`, `duel`, `context_flip`, `correction`, `twin_rank`.
- Each probe offers: A/B (binary), "no preference" (indifference), or custom text.
- Every answer → subagent verdict → live Δw → card weights update.
- Mini-compaction (§3.6) fires every ~8-10 events.
- Admin sees node graph + Δw matrix sliders in real time (§7.1, §7.2).

### 5.4 Open chat phase (T+30 → T+45 min)

- Transitions to mining-agent chat. Compaction pass continues to mint new cards.
- Chat events also produce subagent verdicts on existing cards (`chat_extract` step type) but with smaller Δw than forced choices.
- C-suite cohort benefits from this phase: feels less like a survey, more like a conversation.

### 5.5 Holdout evaluation (T+45 → T+55 min)

- 10-15 reserved holdout probes are surfaced.
- Subagent does NOT update Δw on holdout events.
- For each holdout, the twin produces a predicted distribution over the option set.
- Predictions and actual choices are logged.

### 5.6 Calibration + handoff (T+55 → T+60 min)

- System computes accuracy, Brier, ECE on holdout.
- Assigns calibration band.
- If red, temperature scaling pass runs automatically; re-evaluates ECE.
- Admin sees final band + lineage report.
- If green or amber, twin enters chat mode (§3.9).

### 5.7 Session abort handling

If the participant aborts at any point past warmup:
1. Mark `session_abort_reason` on the token.
2. Run partial calibration on whatever holdout slots have been filled.
3. Mark calibration band as `preliminary_{green|amber|red}`.
4. Chat mode is permitted only if preliminary band is green AND ≥ 50% of holdout slots were filled. Otherwise locked pending re-session.

---

## 6. Participant Experience (C-suite specific)

### 6.1 Briefing principles

- **90-second cap.** Any longer and they're calculating opportunity cost.
- **Frame as utility, not measurement.** "We're building a model of how you make calls so you can offload some of the smaller ones." Reframes participant as user, not subject.
- **No "test" language.** Don't say calibration, evaluation, or benchmark. Triggers performance behavior.
- **Surface the value proposition explicitly.** What they get out of this hour.

Exact briefing copy is deferred (§13). Lives outside the codebase; admin reads it.

### 6.2 Live learning panel (participant-facing)

Visible to the participant throughout the session. Updates every 30-60 seconds.

Contents:
- "Here's what we've learned about how you make decisions" — surface 2-3 cards in plain language as they accumulate weight.
- Pillar progress visualization (lightly stylized, not the admin's debugging graph).
- Estimated remaining time.

**Do NOT show:** specific Δw values, subagent rationales, ECE, calibration bands, or any explicit scoring. The participant is the user; debugging surfaces are admin-only.

### 6.3 Answer mode options per probe

Every forced-choice probe offers:
- **Binary** — pick A or B.
- **No preference / indifferent** — explicit button. Logs as `step_type=indifference`, zero Δw, but the selector treats this area as needing different probing.
- **Custom text** — free-form response. Subagent classifies onto the option spectrum [-1, +1] for graded Δw.

### 6.4 Probe design conventions (for the probe-pool author)

To mitigate social desirability bias:
- **Anchor probes to concrete past situations** when possible. "The last time X happened, did you Y or Z?" beats "If X happened, would you Y or Z?"
- **Pair some probes.** Ask the same functional trade-off twice, 15+ minutes apart, with different framing. Internal inconsistency between paired probes is signal.

### 6.5 Pause / abort handling

- No formal pause mechanism. C-suite participants self-manage breaks.
- Wall-clock time is logged but `session_active_seconds` is the canonical duration for fatigue analysis.
- Abort is a single button labeled "Stop here for today" — no judgment language.

---

## 7. Admin Tooling

### 7.1 Trace visualizer (node graph)

- Cards rendered as nodes; sized by `|cumulative_delta_w|`, colored by polarity dominance.
- Color thresholds:
  - $|w| \ge 1.5$: saturated (crimson contradict / emerald reinforce)
  - $0.8 \le |w| < 1.5$: amber/slate
  - $|w| < 0.8$: translucent gray
- Hover a card → highlight every `RawEvent` that contributed, with timestamps and subagent rationale strings.
- Tabs by `card_type` and `pillar`.

### 7.2 Δw matrix editor

- 7×2 sliders (7 step types × reinforce/contradict).
- Every slider change writes a new `experiment_variants` row AND a `config_events` row. The slider does NOT mutate in place — it forks.
- "Pin variant" button locks Δw for the rest of the session.
- Warning surfaces when accumulated overrides exceed 3 mid-session — heavy tweaking invalidates the variant's measured accuracy.

### 7.3 Live SSE stream

- `GET /api/admin/tokens/{token_id}/live-stream`
- Localhost-only (V2). No admin auth in V2 — deployment posture is the security model.
- Payloads ≤ 2KB per event.
- Event types: `participant_input`, `subagent_verdict`, `weight_update`, `config_event`, `compaction_completed`, `calibration_updated`, `card_promoted`.

### 7.4 Pre-seed deck review UI

- Card list with type, pillar links, and proposed weight 1.0.
- Admin can edit title, body, type, pillar links.
- Add card (manual seed) / remove card.
- "Ready to activate" gate. Token cannot move from `generated` → `active` until reviewed.

### 7.5 Calibration badge surface

On `/admin/tokens` index and individual token pages:
- 🟢 Green — ECE < 0.05
- 🟡 Amber — 0.05 ≤ ECE < 0.10 (tooltip: "Predictions systematically over/underconfident — use distributions, not point estimates")
- 🔴 Red — ECE ≥ 0.10 (tooltip: "Calibration failed; recalibration required before downstream use")
- ⚪ Unmeasured — pre-evaluation state

Badge persists `calibration_band` and `calibration_ece` on the token row.

### 7.6 Recalibration action

- Available when band is red.
- Runs temperature scaling on holdout split, fits scalar $T$, applies $\sigma(z/T)$ to outputs.
- Stores fitted $T$ in `calibration_temperature`.
- Re-evaluates ECE post-fit. If still red, escalates with a "Δw matrix review needed" admin alert.

---

## 8. Research Export

Auto-generated at session completion (or abort). Written to `{settings.research_export_dir}/{date}/{token_short_id}/`. Failure to export is logged via `ErrorReport` but never blocks session completion.

### 8.1 Archive structure

```
v2_research_export/
├── cohort.csv                          # one row per participant
├── README.md                           # schema, variant catalog, methodology notes
├── variants/
│   └── {variant_id}.json               # full Δw matrix + subagent config
└── participants/
    └── {token_short_id}/
        ├── manifest.json
        ├── events.jsonl
        ├── cards_final.json
        ├── holdout.json
        ├── card_tensions.json
        ├── profile_redacted.json
        └── design_debrief.md
```

### 8.2 `cohort.csv` columns

| Column | Notes |
|---|---|
| `token_short_id` | 8-char prefix |
| `variant_label` | |
| `variant_id` | |
| `session_started_at` | ISO8601 |
| `session_duration_seconds` | |
| `aborted` | bool |
| `events_total` | |
| `events_training` | |
| `events_holdout` | |
| `events_evaluated` | events with successful subagent verdict (denominator for metrics) |
| `cards_seeded` | |
| `cards_from_compaction` | |
| `cards_with_any_update` | |
| `cards_dead_weight` | reviewed cards with zero Δw — flags selector failure |
| `holdout_accuracy` | |
| `holdout_brier` | |
| `holdout_ece` | |
| `calibration_band` | |
| `calibration_temperature` | post-fit |
| `subagent_abstention_rate` | |
| `subagent_failure_count` | |
| `target_band_met` | bool |
| Per-type card counts | `cards_biographical`, `cards_disposition`, ... |
| Per-pillar card counts | `cards_pillar_situation_framing`, ... |

### 8.3 `manifest.json` per participant

Contains variant snapshot, config_events log, phase timings, calibration result. See §4.1 schemas; structure mirrors them in nested JSON.

### 8.4 `events.jsonl` — one event per line

Fully denormalized. Subagent verdicts inlined.

```json
{
  "event_id": "...",
  "ordinal": 17,
  "created_at": "...",
  "elapsed_seconds_from_session_start": 412,
  "phase": "main_probe",
  "step_type": "duel",
  "step_id": "...",
  "holdout_slot": false,
  "prompt": "...",
  "options_available": ["A...", "B..."],
  "participant_answer": {
    "mode": "binary",
    "selected_index": 1,
    "selected_option": "B...",
    "text": null
  },
  "subagent_verdicts": [
    {
      "card_id": "...",
      "card_title": "...",
      "card_type": "trigger",
      "polarity": "reinforce",
      "confidence": 0.81,
      "spectrum_position": null,
      "delta_w_applied": 0.4225,
      "rationale": "...",
      "latency_ms": 4120
    }
  ],
  "holdout_prediction": null
}
```

Holdout events have `holdout_slot: true`, no verdicts, and a populated `holdout_prediction` block with predicted distribution + actual + log_loss.

### 8.5 `cards_final.json`

Each card with its full Δw lineage:

```json
{
  "card_id": "...",
  "title": "...",
  "body": "...",
  "card_type": "trigger",
  "status": "reviewed",
  "priority": "high",
  "seed_source": "cv",
  "created_at": "...",
  "promoted_at": "...",
  "pillar_links": [
    {
      "pillar_key": "valuation_expectancies",
      "initial_weight": 1.0,
      "cumulative_delta_w": 1.47,
      "final_weight": 2.47,
      "update_count": 6,
      "update_history": [
        {"event_id": "...", "ordinal": 4, "delta": 0.50, "polarity": "reinforce"},
        {"event_id": "...", "ordinal": 12, "delta": -0.30, "polarity": "contradict"}
      ]
    }
  ]
}
```

### 8.6 `card_tensions.json`

Pairs of cards with opposing Δw patterns — surfaces conditional-policy structure.

```json
[
  {
    "card_a": "card-uuid-1",
    "card_b": "card-uuid-2",
    "tension_score": 0.78,
    "co_occurring_events": ["event-id-1", "event-id-2"],
    "interpretation": "Card A reinforced at events {5, 12}; Card B reinforced at events {18, 24}. Inverse correlation suggests conditional policy."
  }
]
```

### 8.7 `design_debrief.md`

Generated markdown for the *project owner* (not external researchers). Sections:

- **Confidently wrong predictions** — holdout events where predicted probability for the wrong answer was > 0.7, with the 2-3 cards whose weights drove the prediction.
- **Dead-weight cards** — cards with `update_count == 0`. Selector failure or genuinely irrelevant.
- **Internal contradictions worth preserving** — pillar-link pairs with conflicting Δw on different events.
- **Latency hotspots** — subagent calls exceeding 5s, grouped by step type.

### 8.8 `profile_redacted.json`

`profile_structured_context` and `profile_llm_summary` with regex PII redaction (names → `[NAME]`, employers → `[ORG]`). Mark `"redacted": true` in metadata.

### 8.9 Cohort-level debrief

Generated only with `--with-cohort-debrief` flag when N > 3. Adds top-level `cohort_debrief.md`:
- Per-variant accuracy and ECE distributions
- Δw matrix entries that predict good vs bad outcomes
- Step types with highest/lowest average information gain
- Seeded vs compaction-derived cards: which class ended with higher final weight

---

## 9. Non-Functional Requirements

### 9.1 Cost model

DeepSeek V4 Pro pricing: $0.435/M input, $0.87/M output. Estimated per-session cost:
- ~50 forced-choice subagent calls × ~3K tokens = 150K tokens
- ~5 mini-compaction calls × ~6K tokens = 30K tokens
- ~10 holdout prediction calls × ~3K tokens = 30K tokens
- Chat phase calls (~20) × ~4K tokens = 80K tokens

Total ≈ 290K tokens/session. At blended pricing, ~$0.20/session. Cost not a constraint.

### 9.2 Latency

- Subagent timeout: 8 seconds (hard).
- Subagent runs async after the participant sees the next probe.
- Participant-perceived inter-question latency target: < 1.5 seconds.
- p95 subagent latency target: < 6 seconds (leaves 2s safety margin).

### 9.3 Reliability

- Subagent failure is non-fatal. Participant never sees errors.
- `ErrorReport` rows created for every abstention caused by infrastructure failure (distinct from confidence-driven abstentions).
- Provider outage: events queue in `pending_subagent_evals`, processed on recovery.
- Session completion is never blocked on subagent state — partial sessions produce preliminary calibration.

### 9.4 Determinism & reproducibility

- All LLM calls use `temperature=0`.
- Model version IDs (not aliases) captured in `experiment_variants.subagent_model_id` and embedded in research export manifests.
- System warns when a session begins with a model version it hasn't seen before.

### 9.5 Privacy & security

- **Localhost-only V2.** No remote deployment.
- **No admin auth** in V2 — deployment posture is the security model.
- **Participant token gating** (`/play/[token]`) sufficient for co-present sessions.
- **No PII redaction enforced on `RawEvent.payload`** — admin is in the room, free-text answers are inspectable. Participant briefed on this.
- **Research export PII redaction** is regex-based (V2). NER-based redaction is a V3 concern.

### 9.6 Performance

- SSE payload size ≤ 2KB.
- Trace visualizer must render < 50 cards in < 500ms.
- Cohort.csv export must complete in < 30 seconds for N ≤ 100 participants.

---

## 10. Phase 1 Deliverables (one-week build)

Aggressive but workable. Order optimized for de-risking.

| Day | Deliverable |
|---|---|
| 1 | Schema additions per §4 — `models.py` updates, single Alembic baseline revision, fresh DB. |
| 2 | Pre-seed deck generator (CV/profile → card draft list). |
| 2-3 | Admin pre-seed deck review UI (§7.4). |
| 3-4 | Subagent hook integration in `adaptive_scenario_service` — verdict capture, Δw application, `subagent_verdicts` row creation. |
| 4 | Mini-compaction integration — mid-session card creation with `seed_source='compaction'`, draft → reviewed promotion logic. |
| 4 | Adaptive probe selector replacing static sequence (§3.7). |
| 5 | Holdout slot allocator at session start; calibration eval at session end; band assignment; temperature scaling. |
| 5 | Trace visualizer + Δw matrix editor (§7.1, §7.2). |
| 6-7 | Smoke test with internal user; iterate on participant UI per §6.2. |

### 10.1 Smoke test acceptance criteria

Before opening to the first C-suite participant:
1. Complete 60-event synthetic session end-to-end with no subagent failures.
2. Verify `subagent_verdicts` populated for every non-warmup event.
3. Verify holdout events do NOT have verdicts.
4. Verify calibration band assigned correctly across all four states (green/amber/red/unmeasured).
5. Research export generates successfully and re-loads without schema errors.
6. Admin SSE stream produces all expected event types.
7. DeepSeek V4 Pro confirmed: `response_format: json_object` honored, p95 latency < 6s, temperature=0 reproducibility verified across 5 identical calls.

---

## 11. Open Questions / Deferred Decisions

| Question | Default for V2 | Defer to |
|---|---|---|
| Briefing script exact copy | TBD by project lead | Pre-Phase 1 smoke test |
| Live learning panel exact copy | TBD by project lead | Phase 1 build |
| NER-based PII redaction for export | Regex only | V3 |
| Multi-tenant auth | Out of scope | V3 |
| Remote / non-co-present sessions | Out of scope | V3 |
| Cards spanning multiple types (secondary types) | Single primary type only | Revisit if data shows loss |
| Per-card-type Δw tensor (vs filter approach) | Filter approach only | V2.5 if needed |
| Cross-session card persistence (longitudinal twins) | Each session is independent | V3 |
| Drift detection between calibration and use | Out of scope | V3 |

---

## 12. Appendices

### 12.1 Default Δw matrix (V2 v2_default variant)

```json
{
  "triad":        { "reinforce": 0.30, "contradict": 0.45 },
  "duel":         { "reinforce": 0.50, "contradict": 0.65 },
  "context_flip": { "reinforce": 0.20, "contradict": 0.30 },
  "correction":   { "reinforce": 0.40, "contradict": 0.55 },
  "twin_rank":    { "reinforce": 0.35, "contradict": 0.50 },
  "indifference": { "reinforce": 0.00, "contradict": 0.00 },
  "chat_extract": { "reinforce": 0.15, "contradict": 0.20 }
}
```

### 12.2 Step type × card type relevance map

| Step type | biographical | disposition | trigger | stylistic | competence | relational |
|---|:-:|:-:|:-:|:-:|:-:|:-:|
| `triad` | – | ✓ | ✓ | – | – | – |
| `duel` | – | ✓ | ✓ | – | ✓ | – |
| `context_flip` | – | – | ✓ | – | – | – |
| `correction` | – | ✓ | – | ✓ | – | – |
| `twin_rank` | – | ✓ | ✓ | ✓ | ✓ | ✓ |
| `chat_extract` | – | ✓ | ✓ | ✓ | ✓ | ✓ |
| `indifference` | – | – | – | – | – | – |

### 12.3 Subagent reasoning effort by call type

| Call | Reasoning effort |
|---|---|
| Forced-choice event evaluation | `high` |
| Chat-extract evaluation | `high` |
| Mini-compaction (card extraction) | `xhigh` |
| Holdout prediction | `high` |
| Card-tension analysis (research export) | `xhigh` |

### 12.4 Card promotion rule

A draft card auto-promotes to `reviewed` when:
- `reinforcement_count >= 3` with average confidence ≥ 0.5
- OR admin manually promotes via the trace visualizer

Promoted cards count toward pillar readiness; draft cards do not.

### 12.5 Tension score formula (research export)

For two cards A and B with update histories over shared events:

$$\text{tension}(A, B) = \frac{|\sum_e \text{sign}(\Delta w_A^e) \cdot \text{sign}(\Delta w_B^e) \cdot -1|}{|\text{shared events}|}$$

Cards are surfaced in `card_tensions.json` when tension ≥ 0.6 and shared events ≥ 4.

---

## 13. Sign-off

This PRD describes the design as locked through 2026-05-22. Changes require a versioned amendment and a `config_events` analog at the document level — i.e. note what changed and why, don't silently mutate.

**Next action:** Begin Phase 1 build per §10. First C-suite session targeted for week of 2026-05-29 pending smoke-test completion.
