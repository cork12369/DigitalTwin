# Harness Revision Plan — Digital Twin V2

**Date:** 2026-05-29  
**Status:** Draft v2 — updated with shared DigiTwin chat concepts  
**Scope:** `harness_service.py` + supporting services, informed by ACP Workbook, PRD V2 direction, and the investor digital twin design conversation

---

## 1. Current Harness Assessment

The current harness (`harness_service.py`, 931 lines) is a **logprob-based scoring system** that:

- Selects up to 3 held-out discrete-action events (triads, duels, twin_ranks) from the participant's last 60 events
- Collects up to 6 memory card sources and 6 questionnaire event sources
- For each case, scores **isolated lift** (single source vs. baseline) and **marginal ablation** (all-minus-one vs. all) via OpenRouter logprobs
- Computes KL divergence, lift in nats, information gain in bits, and assigns verdicts (positive_lift, negative_drift, zero_impact, policy_displacement, mixed)
- Optionally integrates OpenViking retrieval sources with bundle scoring

**What it does well:** Rigorous statistical framework for measuring whether individual sources (memory cards, questionnaire signals) actually shift the model toward the participant's real choice. The ablation design cleanly separates which sources help vs. hurt.

**Gaps identified (relative to PRD + ACP concepts):**

1. **No domain-structured evaluation.** Cases are picked by recency, not by coverage across the 5 pillars or across preference domains. A harness run could score 3 triads from the same pillar and miss entire decision axes.

2. **No state-dependent testing.** The ACP workbook structures preferences around life-state transitions (well → unwell → after death). The current harness evaluates in a single static context — it never tests whether the twin's predictions shift appropriately when the scenario's framing context changes (e.g., "under normal pressure" vs. "under crisis").

3. **No proxy/spokesperson fidelity.** The ACP's Nominated Healthcare Spokesperson concept maps directly to the digital twin's core job: representing the participant's preferences to a third party. The harness doesn't test this — it only tests action prediction, not whether the twin can articulate *why* the participant would choose that action.

4. **No value-conflict probing.** The ACP explicitly surfaces trade-offs (comfort-focused care vs. life-sustaining treatment). The harness scores each case independently but doesn't evaluate whether the twin correctly handles value tensions — cases where two strong cards pull in opposite directions.

5. **Caps are too tight.** MAX_CASES=3 and MAX_SOURCES_PER_TYPE=6 made sense for MVP but undercount for the PRD's target of 20-25 cards and 10-15 holdout slots.

6. **No pillar-aware aggregation.** Aggregate metrics are flat averages. No per-pillar or per-card-type breakdown to identify which decision axes the twin has learned vs. which remain uncalibrated.

7. **No calibration band integration.** The harness runs independently of the ECE/Brier calibration system described in PRD §3.8. The two systems should cross-reference.

8. **Prompt is generic.** The scoring prompt doesn't leverage structured preference context (the ACP's "what matters to you" categories) — it just concatenates source text.

9. **No constraint/veto gating.** The chat established that constraint cards (vetoes, fiduciary duties, deferral rules) sit *off the graph* and fire as hard gates regardless of how the weighing layer scores. The current harness treats all memory cards uniformly — it has no way to test whether a VETO-type constraint properly blocks a decision path.

10. **No dual-weight distinction.** The chat's core architectural insight is that edges carry two weights: *association* (what the investor's mind actually pulls toward — observational, cheap) and *relevance* (what he endorsed on reflection — reflective, expensive). The gap between high-association and low-relevance is the key signal ("his mind pulls hard here; he asked us not to"). The current harness scores all sources identically.

11. **Twin outputs briefs, not decisions.** The chat's deliverable is explicitly a *brief* — a spread with variance drivers named, biases called out, gates flagged — not a point prediction. The harness only measures point-prediction accuracy (did you pick the right label?), not brief quality.

12. **No trajectory/dispersion tracking.** Parameter cards should carry trajectory (how the estimate moved across sessions) and dispersion (cross-session jitter). The harness has no way to evaluate whether high-dispersion cards are appropriately down-weighted in predictions.

13. **No endorsed vs. unendorsed separation.** The chat's `endorsed: true/false` flag marks whether the participant ratified a card on reflection. Endorsed cards represent the *ought* layer (relevance); unendorsed cards represent the *is* layer (association). The harness should score these separately.

---

## 2. Conceptual Sources Mapped to Harness Revisions

### 2.1 From the ACP Workbook

| ACP Concept | Harness Application |
|---|---|
| **Structured preference domains** (medical care, daily care, support, concerns) | Add **domain-tagged case selection** — ensure cases cover multiple preference domains, not just whatever was recent |
| **Comfort vs. life-sustaining spectrum** | Add **value-conflict cases** — test cases where the twin must resolve tension between competing strong cards |
| **Life-state transitions** (well → unwell → after death) | Add **context-conditioned scoring** — score the same case under multiple context frames and measure whether the twin's distribution shifts appropriately |
| **Nominated Healthcare Spokesperson** (proxy who represents your wishes) | Add **rationale fidelity scoring** — beyond predicting the action, evaluate whether the twin can articulate the participant's reasoning |
| **Reflect → Plan → Share lifecycle** | Add **phase-aware harness runs** — different scoring emphasis depending on session phase (early calibration vs. post-chat vs. holdout) |
| **Concern/support modifiers** | Add **contextual modifier injection** — test whether injecting concern/support signals (analogous to ACP's worry checklist) appropriately shifts predictions |

### 2.2 From the DigiTwin Chat (Investor Digital Twin Design)

| Chat Concept | Harness Application |
|---|---|
| **Three stores** (episodes / parameter cards / constraint cards) | Harness must test each store's contribution separately. Constraint cards scored via **gate testing**, not lift. |
| **Dual-weighted edges** (association vs. relevance) | New scoring mode: **assoc-relev divergence scoring** — test whether high-assoc-low-relev cards are appropriately dampened, not overweighted |
| **Constraint/veto cards fire as hard gates** | New metric type: **gate_accuracy** — does the twin correctly block decision paths when a VETO-scope constraint applies? |
| **Output is a brief, not a decision** | New evaluation: **brief quality scoring** — does the twin name variance drivers, flag biases, call out gates, present a spread rather than a point? |
| **Endorsed flag (is/ought gap)** | Score endorsed and unendorsed cards separately. Measure whether endorsed cards produce higher positive lift than unendorsed (they should). |
| **Trajectory + dispersion on parameter cards** | New aggregate metric: **dispersion-weighted lift** — high-dispersion cards should have lower influence; test if this holds |
| **Non-stationarity** (investor changes over time) | Harness should report **temporal stability** — do predictions on early-session holdouts match late-session holdouts? |
| **Reactivity** (measurement deforms the measured) | Flag cases where the participant's later answers contradict earlier ones on similar probes — this is the twin's hardest test |
| **Religion/faith as operator, not axis** | Validates the constraint-card architecture — religious constraints are VETO-type, scoped, volatile. Harness should test volatile constraint handling |

| ACP Concept | Harness Application |
|---|---|
| **Structured preference domains** (medical care, daily care, support, concerns) | Add **domain-tagged case selection** — ensure cases cover multiple preference domains, not just whatever was recent |
| **Comfort vs. life-sustaining spectrum** | Add **value-conflict cases** — test cases where the twin must resolve tension between competing strong cards |
| **Life-state transitions** (well → unwell → after death) | Add **context-conditioned scoring** — score the same case under multiple context frames and measure whether the twin's distribution shifts appropriately |
| **Nominated Healthcare Spokesperson** (proxy who represents your wishes) | Add **rationale fidelity scoring** — beyond predicting the action, evaluate whether the twin can articulate the participant's reasoning |
| **Reflect → Plan → Share lifecycle** | Add **phase-aware harness runs** — different scoring emphasis depending on session phase (early calibration vs. post-chat vs. holdout) |
| **Concern/support modifiers** | Add **contextual modifier injection** — test whether injecting concern/support signals (analogous to ACP's worry checklist) appropriately shifts predictions |

---

## 3. Revision Plan — Three Phases

### Phase 1: Structural Improvements (Low Risk, High Value)

These changes improve the harness within its existing architecture.

**1.1 Pillar-aware case selection**

File: `harness_service.py` → `_build_case_candidates()`

Currently picks the last 60 events and takes the first 3 valid discrete-action events. Revise to:
- Tag each candidate with its pillar(s) from the originating step's card evaluations
- Select cases to maximize pillar coverage (greedy set-cover)
- Increase MAX_CASES from 3 to 5-6 (aligns with PRD's 10-15 holdout slots)
- Fall back to recency if pillar metadata is unavailable

**1.2 Per-pillar and per-type aggregate metrics**

File: `harness_service.py` → `_aggregate_scores()`

Add breakdowns:
- `pillar_scores`: average lift and KL per pillar
- `card_type_scores`: average lift per card type (disposition, trigger, etc.)
- `coverage_gaps`: pillars with zero cases or zero positive-lift sources
- `dead_weight_sources`: sources that never produce positive lift across any case

**1.3 Raise caps**

- MAX_CASES: 3 → 6
- MAX_SOURCES_PER_TYPE: 6 → 10
- MAX_CONTEXT_CHARS: 5200 → 8000 (modern models handle this fine)

**1.4 Holdout-slot aware case selection**

File: `harness_service.py` → `_build_case_candidates()`

Prefer events where `holdout_slot=true` — these are the events the PRD designates for evaluation. Currently the harness ignores this flag entirely.

---

### Phase 2: Three-Store & Dual-Weight Evaluation (Medium Complexity)

These add new scoring dimensions grounded in the chat's architectural concepts.

**2.1 Constraint/veto gate testing**

The chat established that constraint cards (vetoes, fiduciary duties, deferral rules, volatile religious constraints) sit off the graph and fire as hard gates. The harness needs a new metric type that tests gate behavior rather than lift.

For each case, identify constraint cards whose scope matches the situation. Score:
- **Gate accuracy**: Did the twin correctly block/allow decision paths per active constraints?
- **Volatile constraint handling**: For cards marked `volatile: true`, does the twin flag uncertainty rather than assert?
- **Deferral routing**: When a constraint card specifies `authority: deferral → [named party]`, does the twin output defer rather than decide?

New metric type: `gate_accuracy`

Implementation:
- New function `_score_constraint_gates()` in harness_service.py
- Requires constraint cards to be tagged with `type: VETO/DEFERRAL/FIDUCIARY` and `scope`
- Uses structured LLM evaluation (prompt the model with the constraint active, check if it properly gates)

**2.2 Assoc-relev divergence scoring**

The chat's key insight: edges carry association weight (what his mind pulls toward) and relevance weight (what he endorsed). High-assoc-low-relev sources are the dangerous ones — they'll dominate naive retrieval but should be dampened.

For each source, if both weights are available:
- Score lift with the source included (current behavior)
- Compare against the source's `relev` weight
- Flag **overweight sources**: positive lift but low relevance → the twin is following association, not endorsement
- Flag **underweight sources**: low lift but high relevance → the twin is ignoring something the participant said matters

New metric type: `assoc_relev_divergence`

**2.3 Value-conflict case detection**

Identify cases where the participant's card deck has strong opposing signals (cards with high cumulative_delta_w in opposite polarities relevant to the same case). These are the "comfort vs. life-sustaining" moments from the ACP, the "risk_loss_aversion vs. honor_long_commitments" tensions from the chat.

For value-conflict cases, add:
- `conflict_cards`: which cards are in tension
- `resolution_accuracy`: did the twin predict the participant's actual resolution correctly?
- `conflict_strength`: magnitude of the opposing weights

New field on `TwinHarnessCase`: `is_value_conflict: bool`, `conflict_card_ids: list[str]`

**2.4 Context-conditioned scoring (state-dependent testing)**

Inspired by ACP's lifecycle model and the chat's discussion of non-stationarity. For each case, generate a **context variant** — the same situation with a modified framing (e.g., higher stakes, different time pressure, shifted authority). Score both variants and measure:

- **Context sensitivity**: Does the twin's distribution shift? (KL between variants)
- **Direction correctness**: Does it shift in the direction the participant's actual behavior suggests?

New metric type: `context_conditioned_lift`

**2.5 Brief quality scoring (spokesperson mode)**

The chat established that the twin outputs **briefs, not decisions**. A brief names the weighing lean, its variance drivers, any gates that fired, and biases the participant flagged. The current harness only tests point-prediction (pick label A/B/C). This new mode tests whether the twin can produce a well-structured brief.

Prompt the model to generate a brief for the held-out situation (without seeing the participant's actual answer). Score:
- **Spread presented**: Does it show a distribution, not just a point?
- **Variance drivers named**: Does it identify which cards are driving the prediction?
- **Gates flagged**: Does it surface any active constraints?
- **Biases called out**: Does it note high-assoc-low-relev sources (things the participant overweights)?
- **Rationale-action consistency**: Does the brief's lean match the predicted label?

New metric type: `brief_quality`

Implementation:
- Separate prompt that asks for a structured brief instead of a single label
- Scoring via structured LLM evaluation (subagent-style, independent model)
- This subsumes the earlier "rationale fidelity" concept — a brief is a richer test than a rationale

**2.6 Endorsed vs. unendorsed source separation**

Score endorsed and unendorsed cards in separate buckets. Expected behavior:
- Endorsed cards should produce higher positive lift (they represent the *ought* layer)
- Unendorsed cards may produce lift but should be flagged if they dominate (the twin is following the *is* layer)

New aggregate metric: `endorsed_lift_ratio` = average lift of endorsed sources / average lift of all sources

---

### Phase 3: Calibration Integration & Research Export (Higher Complexity)

**3.1 Cross-reference with ECE calibration**

Connect the harness to the PRD's calibration band system (§3.8):
- After harness run completes, compute Brier score on the harness cases
- Compare harness accuracy with holdout ECE
- Flag discrepancies (e.g., harness shows positive lift but ECE is red → the sources help predict correctly but the confidence is miscalibrated)
- Store `harness_brier`, `harness_accuracy` on the run

**3.2 Temperature-aware scoring**

If `calibration_temperature != 1.0`, apply temperature scaling to the logprob distributions before computing lift and KL. Currently the harness uses raw logprobs regardless of calibration state.

**3.3 Research export integration**

Add harness results to the PRD's research export (§8):
- `harness_runs.json` per participant: all runs with cases, scores, and aggregate metrics
- `source_effectiveness.csv`: per-source lift and KL across all cases (which cards actually matter?)
- `coverage_report.json`: pillar and type coverage gaps

**3.4 Structured preference context in prompts**

Replace the generic prompt template with one that organizes participant context into the three-store architecture from the chat:

**Parameter cards** (the weighing layer):
- Sorted by relevance weight, not just recency
- Each card shows: estimate, trajectory direction, dispersion, endorsed flag
- High-dispersion cards explicitly flagged as uncertain

**Constraint cards** (the gate layer):
- Listed separately, not mixed into the weighing layer
- Each shows: type (VETO/DEFERRAL/FIDUCIARY), scope, volatile flag
- Active constraints for this situation highlighted

**Contextual grounding** (from episode store):
- Biographical cards as static context
- Most recent relevant episode excerpts (not full transcripts)
- Stylistic cards informing tone expectations

This structured prompt replaces the current flat concatenation and should improve both prediction accuracy and brief quality.

**3.5 Temporal stability scoring**

The chat flagged non-stationarity as a core challenge. Add a harness metric that compares predictions on early-session holdouts vs. late-session holdouts:
- **Temporal consistency**: Do predictions improve over the session? (they should)
- **Drift detection**: Do early predictions on the same pillar contradict late predictions?
- **Reactivity flag**: Cases where the participant's later answers contradict earlier ones on similar probes — these are the twin's hardest test

**3.6 Dispersion-weighted aggregation**

Parameter cards with high dispersion (cross-session jitter) should have lower influence on predictions. Add:
- `dispersion_weighted_lift`: lift weighted by inverse dispersion
- `high_dispersion_sources`: sources with dispersion > threshold that still produce high lift — potential overfitting to noise

---

## 4. File Change Map

| File | Phase | Changes |
|---|---|---|
| `harness_service.py` | 1 | Pillar-aware case selection, raised caps, holdout-slot preference, per-pillar aggregation |
| `harness_service.py` | 2 | Gate testing, assoc-relev divergence, value-conflict detection, context-conditioned scoring, brief quality scoring, endorsed separation |
| `harness_service.py` | 3 | Calibration cross-reference, temperature-aware scoring, structured 3-store prompts, temporal stability, dispersion-weighted aggregation |
| `models.py` | 1-2 | New fields on MemoryCard: `card_class` (parameter/constraint), `endorsed`, `volatile`, `dispersion`, `association_weight`, `relevance_weight` |
| `models.py` | 2 | New fields on TwinHarnessCase: `is_value_conflict`, `conflict_card_ids`, `is_gate_test` |
| `models.py` | 2-3 | New fields on TwinHarnessRun: `harness_brier`, `harness_accuracy`, `endorsed_lift_ratio`, `temporal_consistency` |
| `models.py` | 2 | New TwinHarnessScore metric_types: `gate_accuracy`, `assoc_relev_divergence`, `brief_quality`, `context_conditioned_lift` |
| `schemas.py` | 1-2 | Updated response schemas for richer aggregate metrics |
| `routes/analysis.py` | 1-2 | Expose new harness metrics in admin API |
| `adaptive_scenario_service.py` | 2 | Context variant generation for harness use |
| `v2_lineage_service.py` | 2 | Value-conflict card detection helper, constraint scope matching |

---

## 5. Suggested Execution Order

1. **Phase 1.3** (raise caps) — trivial, immediate improvement
2. **Phase 1.4** (holdout-slot awareness) — aligns harness with PRD's holdout design
3. **Phase 1.1** (pillar-aware selection) — requires pillar metadata on events, moderate effort
4. **Phase 1.2** (per-pillar aggregation) — depends on 1.1
5. **Phase 2.6** (endorsed vs. unendorsed separation) — requires `endorsed` flag on cards, lightweight to score
6. **Phase 2.2** (assoc-relev divergence) — requires dual weights on edges, high insight value
7. **Phase 2.3** (value-conflict detection) — standalone, identifies the hardest cases
8. **Phase 2.1** (constraint/veto gate testing) — requires constraint card classification, new scoring paradigm
9. **Phase 2.4** (context-conditioned scoring) — depends on adaptive scenario service
10. **Phase 2.5** (brief quality scoring) — new output format evaluation, test separately
11. **Phase 3.4** (structured 3-store prompts) — improves all scoring, do before calibration integration
12. **Phase 3.5** (temporal stability) — requires session with enough holdout spread
13. **Phase 3.6** (dispersion-weighted aggregation) — requires multi-session trajectory data
14. **Phase 3.1-3.2** (calibration integration) — depends on PRD calibration system being implemented
15. **Phase 3.3** (research export) — last, depends on stable harness output schema

---

## 6. Key Design Decisions to Confirm

1. **Card classification: parameter vs. constraint.** The current `MemoryCard` model has `card_type` (biographical, disposition, trigger, etc.) but no parameter/constraint distinction. The chat's architecture puts constraint cards off the graph entirely. Decision: add a `card_class` enum (`parameter`, `constraint`) and retroactively classify existing cards. Trigger cards with VETO-like behavior become constraints; others stay as parameters.

2. **Dual weights: where do they live?** The chat puts `assoc` and `relev` on graph edges. The current model has `cumulative_delta_w` on `memory_card_pillar_links`. Options: (a) add `association_weight` and `relevance_weight` columns on pillar links, derive from Δw and endorsement, or (b) separate edge store. Recommend (a) for v2.

3. **Brief quality evaluation model.** The brief is a qualitative output. Score it with the PRD's subagent (deepseek) for independence from the prediction model. Adds ~8s latency per case but is the honest approach.

4. **Context-conditioned scoring: reuse adaptive scenario service or lighter-weight?** The existing service is heavy (800 lines, OpenRouter calls). Recommend a harness-specific variant generator that modifies one context parameter (stakes, time pressure, authority) — lighter, deterministic, testable.

5. **Volatile constraint handling.** The chat flagged that religious constraints can shift exactly when invoked. The harness should test this by scoring with the constraint active vs. inactive and measuring whether the twin flags the volatility. Decision: require `volatile: true` constraints to include uncertainty language in their briefs.

6. **The validation problem.** The chat's sharpest point: you cannot confirm the twin matches what the participant would have decided while they're still competent. The harness can measure internal consistency and source attribution, but it cannot measure *correctness* in the out-of-capacity future. This is an inherent limitation, not a bug to fix. The harness should explicitly report what it *can* validate (prediction consistency, source grounding, gate behavior) and what it *cannot* (future-self fidelity).

7. **ACP preference categories vs. PRD pillars vs. chat's axes.** Three taxonomies in play:
   - PRD pillars: decision-process axes (situation_framing, option_generation, valuation_expectancies, counterfactual_stress, feedback_integration)
   - ACP categories: preference domains (medical care, daily care, concerns, support)
   - Chat axes: investor-specific (meaning, context, fears/red-lines, consequences, temporality, risk tolerance, trusted parties, time horizon)
   
   These are orthogonal. Recommend: PRD pillars remain the structural backbone. ACP categories and chat axes are domain-specific instantiations — they tag cards and cases but don't replace the pillar system. The harness reports per-pillar AND per-domain when domain tags are available.
