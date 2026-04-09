# Harness Distillation Experiment Plan — NeurIPS 2026

## Thesis

Local AI optimization exists on a spectrum from changing what surrounds the model (harness) to changing the model itself (weights). Current approaches optimize one layer in isolation:

```
                    ┌── GEPA          (evolutionary prompt search)
Harness-only ──────┤── DSPy          (programmatic prompt/few-shot optimization)
                    └── Distillation  (root-cause-driven harness edits)
                                                                            ← THIS WORK
                    ┌── LoRA          (lightweight weight adaptation)
Weight-only ───────┤── SFT           (supervised fine-tuning)
                    └── RL/GRPO      (reinforcement learning from outcomes)
```

**The key question this section of the paper answers:** How does root-cause-driven harness optimization (distillation) compare to search-based harness optimization (GEPA/DSPy) and weight modification (LoRA/SFT/RL) — and what happens when you combine them?

## How Distillation Differs from GEPA/DSPy

| Dimension | GEPA | DSPy | Distillation |
|-----------|------|------|-------------|
| **Strategy** | Evolutionary search | Programmatic bootstrapping | Diagnosis-driven targeted edits |
| **How it finds improvements** | Generates random mutations, evaluates, selects fittest | Mines successful traces as few-shot examples, optimizes prompts programmatically | Frontier model diagnoses *why* failures happen, proposes specific fixes |
| **Search space** | System prompt text, tool sets, temperature, max_turns | Few-shot examples, prompt templates, module composition | Model routing, system prompts, agent class, tool descriptions, parameters |
| **Evaluator** | Benchmark score (black-box) | Metric function (black-box) | Personal benchmark with per-cluster regression detection |
| **Cost model** | O(population × generations × eval_cost) | O(candidates × eval_cost) | O(1 diagnosis + 1 plan + N edit_evals) |
| **Interpretability** | Low — why did this mutation win? | Medium — can inspect selected examples | High — diagnosis.md explains root causes |
| **Rollback** | Replace config file | Replace config file | Git-backed per-edit rollback with audit trail |
| **Requires** | Eval harness + many trials | Eval harness + trace data | Frontier API key + trace data + personal benchmark |

**The hypothesis:** Distillation should be more **sample-efficient** (fewer evals needed) but more **API-expensive** (one frontier call vs. no frontier call for GEPA/DSPy). The combination of distillation + GEPA/DSPy should outperform either alone because distillation handles "why is this failing?" while GEPA/DSPy handles "what's the optimal phrasing?"

## How Distillation Differs from LoRA/SFT/RL

| Dimension | LoRA/SFT | RL/GRPO | Distillation |
|-----------|----------|---------|-------------|
| **What changes** | Model weights | Model weights (policy) | Config files (prompts, routing, tools) |
| **Training data** | (query, ideal_response) pairs | Reward signal from benchmark | Frontier model's diagnosis |
| **GPU hours** | Hours-days per model | Hours-days per model | 0 (inference only) |
| **Reversibility** | Swap adapter/checkpoint | Swap checkpoint | `jarvis learning rollback` |
| **Model-specific** | Yes — one training run per model | Yes | No — config applies to any model |
| **Inference cost change** | None (same model) | None | None (same model) |
| **Complementary?** | Yes — weights + harness stack | Yes | Yes — harness on top of any weights |

**The hypothesis:** Distillation + LoRA should be strictly better than either alone. Distillation fixes what the *harness* is doing wrong (routing, prompts, tools); LoRA fixes what the *model* is doing wrong (reasoning patterns, format adherence). They operate on orthogonal layers.

## Experimental Design

### Phase 2c: Distillation Optimization (NEW — fits between 2a and 2b)

Add `distillation/` to the results structure:

```
results/neurips-2026/agent-optimization/
├── gepa/                     # Existing
├── dspy/                     # Existing
├── distillation/             # NEW
│   ├── {model}/
│   │   ├── session-{id}/
│   │   │   ├── diagnosis.md
│   │   │   ├── plan.json
│   │   │   ├── session.json
│   │   │   └── teacher_traces/
│   │   ├── benchmark_before.json
│   │   ├── benchmark_after.json
│   │   └── config_diff.patch    # git diff of all applied edits
│   └── ...
└── combined/                 # NEW — stacked optimizations
    ├── distillation+gepa/
    ├── distillation+dspy/
    ├── distillation+lora/
    └── distillation+gepa+lora/
```

### Experiment Matrix

**Independent variable:** Optimization method (7 conditions + 4 combinations)

| Condition | Layer | Method | Cost |
|-----------|-------|--------|------|
| Baseline | None | Raw model | 0 |
| GEPA | Harness | Evolutionary search | ~150 evals × eval_cost |
| DSPy | Harness | Bootstrap few-shot | ~10-50 evals × eval_cost |
| **Distillation** | **Harness** | **Root-cause diagnosis** | **~$5 frontier + N evals** |
| LoRA | Weights | Adapter fine-tuning | GPU hours |
| SFT | Weights | Full fine-tuning | GPU hours |
| RL/GRPO | Weights | Reward optimization | GPU hours |
| **Distillation + GEPA** | **Both harness** | **Diagnose then search** | **$5 + 150 evals** |
| **Distillation + LoRA** | **Harness + Weights** | **Config + adapter** | **$5 + GPU hours** |
| **GEPA + LoRA** | **Harness + Weights** | **Search + adapter** | **150 evals + GPU hours** |
| **Distillation + GEPA + LoRA** | **All** | **Full stack** | **$5 + 150 evals + GPU** |

**Dependent variables:** Same as the paper's existing metrics:
- Accuracy (benchmark-specific)
- Latency (seconds per task)
- Energy (joules per task)
- Cost ($ per task — API cost for distillation teacher, amortized GPU for LoRA/SFT)
- IPW (Intelligence per Watt)
- IPJ (Intelligence per Joule)

**Models to test:** Focus on 3 representative models for the distillation experiments:
- **Qwen-2B** — smallest, most room for improvement
- **Qwen-9B** — mid-range, already decent baseline
- **Qwen-27B** — largest local, closest to cloud quality

**Benchmarks:** Use the 3 fast benchmarks for optimization loop, full 7 for final eval:
- Fast: ToolCall-15, PinchBench, TauBench-A (fast subset)
- Full: All 7

### Concrete Experiments

#### Experiment 1: Distillation standalone (3 models × 3 benchmarks)

For each model:
1. Run baseline eval on fast benchmarks → `benchmark_before.json`
2. Seed feedback on traces (manually score 20+ traces with feedback ≥ 0.7)
3. Run `jarvis learning run` with `teacher_model=claude-opus-4-6`
4. Record: diagnosis.md, plan.json, applied edits, rejected edits, cost
5. Run post-optimization eval → `benchmark_after.json`
6. Compute Δ accuracy, Δ IPW, Δ IPJ

**What to measure per session:**
- Number of failure clusters identified
- Number of edits proposed / applied / rejected
- Teacher API cost ($)
- Wall-clock time for the session
- Per-cluster score delta (which failure modes improved?)
- Which edit *types* had the most impact? (routing vs prompt vs tool)

#### Experiment 2: Distillation vs GEPA vs DSPy (head-to-head)

Run all three harness optimizers on the same model × benchmark:
1. Same starting config, same baseline scores
2. Same eval budget: normalize to ~$10 total cost per method
   - GEPA: ~150 evals at ~$0.07/eval ≈ $10
   - DSPy: ~50 evals at ~$0.20/eval ≈ $10
   - Distillation: ~$5 teacher + 5 gate evals ≈ $7-10
3. Compare final accuracy, but also:
   - **Time to first improvement** — how many evals/$ before the score first exceeds baseline?
   - **Interpretability** — can you explain *why* the optimization worked?
   - **Stability** — does the improvement hold on the full benchmark (not just the fast subset)?

#### Experiment 3: Stacking (Distillation + X)

Test the hypothesis that harness + weights optimizations are complementary:

1. **Distillation → GEPA:** Run distillation first to fix routing/tools, then GEPA to polish prompts
2. **Distillation → LoRA:** Run distillation to fix harness, then LoRA to fix weight-level failures
3. **GEPA → LoRA:** GEPA to optimize prompts, then LoRA (existing plan)
4. **Distillation → GEPA → LoRA:** Full stack

Compare each combination against its components. The key figure:

```
Accuracy improvement (Δ over baseline)

            Baseline  GEPA   DSPy   Distill  LoRA   D+GEPA  D+LoRA  D+G+L
Qwen-2B     ____      ____   ____   ____     ____   ____    ____    ____
Qwen-9B     ____      ____   ____   ____     ____   ____    ____    ____
Qwen-27B    ____      ____   ____   ____     ____   ____    ____    ____
```

#### Experiment 4: Cost-efficiency frontier

Plot: Δ accuracy vs. optimization cost ($) for each method.

The hypothesis is that distillation sits at a favorable point on this curve — it's more expensive than GEPA/DSPy per run ($5 vs ~free for search) but achieves the improvement in fewer iterations because it diagnoses root causes rather than searching blindly.

```
Δ accuracy
    |          * D+G+L
    |        * D+LoRA
    |      * D+GEPA
    |    * Distillation
    |   * LoRA
    |  * DSPy
    | * GEPA
    |
    +-----------------------------------→ optimization cost ($)
```

#### Experiment 5: Edit-type attribution analysis

Unique to distillation — GEPA/DSPy don't produce this data:

For each distillation session, break down which edit *types* drove the improvement:

| Edit Type | Count Applied | Avg Δ Accuracy | Example |
|-----------|--------------|----------------|---------|
| SET_MODEL_FOR_QUERY_CLASS | ? | ? | Route math → qwen-27b |
| PATCH_SYSTEM_PROMPT | ? | ? | Add "use tools" hint |
| ADD_TOOL_TO_AGENT | ? | ? | Enable calculator |
| EDIT_TOOL_DESCRIPTION | ? | ? | Clarify web_search usage |
| SET_AGENT_PARAM | ? | ? | Increase max_turns |

This answers: "What's the highest-leverage knob to turn?" — which is a practically useful finding for the paper.

## Running the Experiments

### Prerequisites

```bash
# Install distillation deps (already on branch)
git checkout feat/distillation-m1-foundations
uv sync --extra dev --extra inference-cloud

# Verify distillation works
uv run jarvis learning init
uv run jarvis learning --help
```

### Step-by-step for Experiment 1

```bash
# 1. Run baseline eval for Qwen-9B on fast benchmarks
uv run python -m openjarvis.evals run \
    -c src/openjarvis/evals/configs/neurips/qwen-9b-pinchbench.toml \
    --output results/neurips-2026/baselines/qwen-9b/pinchbench/

# 2. Seed feedback on 20+ traces
#    (Either from eval scores or manually via jarvis feedback)
uv run python -c "
from openjarvis.traces.store import TraceStore
store = TraceStore()
traces = store.list_traces(limit=30)
for t in traces:
    # Use eval score as feedback proxy, or score manually
    if t.outcome == 'success':
        store.update_feedback(t.trace_id, 0.8)
    else:
        store.update_feedback(t.trace_id, 0.3)
print(f'Seeded feedback on {len(traces)} traces')
"

# 3. Run distillation session
export ANTHROPIC_API_KEY="..."
uv run jarvis learning run --autonomy auto

# 4. Check what happened
uv run jarvis learning history
uv run jarvis learning show <session-id>

# 5. Run post-optimization eval
uv run python -m openjarvis.evals run \
    -c src/openjarvis/evals/configs/neurips/qwen-9b-pinchbench.toml \
    --output results/neurips-2026/agent-optimization/distillation/qwen-9b/pinchbench/

# 6. Compare
python -c "
import json
before = json.load(open('results/neurips-2026/baselines/qwen-9b/pinchbench/summary.json'))
after = json.load(open('results/neurips-2026/agent-optimization/distillation/qwen-9b/pinchbench/summary.json'))
print(f'Before: {before[\"accuracy\"]:.1%}')
print(f'After:  {after[\"accuracy\"]:.1%}')
print(f'Delta:  {after[\"accuracy\"] - before[\"accuracy\"]:+.1%}')
"
```

### Step-by-step for Experiment 3 (Stacking)

```bash
# 1. Start from baseline
# 2. Run distillation → get optimized config
uv run jarvis learning run --autonomy auto
# 3. Run GEPA on top of the distillation-optimized config
uv run jarvis optimize run \
    --benchmark pinchbench \
    --optimizer-model claude-sonnet-4-6 \
    --trials 20 \
    --output-dir results/neurips-2026/agent-optimization/combined/distillation+gepa/qwen-9b/
# 4. Eval the combined result
```

## Paper Framing

### Where this fits in the paper structure

The existing plan has:
- Step 1: Baselines (done)
- Step 2a: Agent optimization (GEPA + DSPy)
- Step 2b: Intelligence optimization (LoRA + SFT + RL)
- Step 3: Full evaluation

Distillation adds a **Step 2c** and a **Step 2d (combinations)**:
- Step 2c: Harness distillation (this doc)
- Step 2d: Stacked optimization (distillation + GEPA, distillation + LoRA, etc.)

### Key claims to support

1. **Root-cause diagnosis is more sample-efficient than search.** Distillation achieves comparable or better improvements to GEPA/DSPy with fewer benchmark evaluations because it identifies *why* failures happen rather than searching blindly.

2. **Harness and weight optimizations are complementary.** The stacked combination (distillation + LoRA) outperforms either layer alone because they optimize orthogonal aspects of the system.

3. **Distillation produces interpretable improvement records.** Unlike GEPA/DSPy which output opaque "best config" files, distillation produces `diagnosis.md` explaining root causes and `plan.json` with typed, attributable edits. This is practically valuable for understanding *what improved and why*.

4. **The personal benchmark enables continuous improvement.** Unlike one-shot optimization, distillation's benchmark gate + rollback mechanism enables a safe continuous improvement loop — the system can keep learning from real usage without regression.

### Key figures for the paper

1. **Table: Optimization method comparison** — accuracy, cost, time, interpretability across all methods × models × benchmarks
2. **Figure: Cost-efficiency Pareto frontier** — Δ accuracy vs optimization cost for each method
3. **Figure: Stacking gain chart** — bar chart showing additive improvement from combining methods
4. **Figure: Edit attribution heatmap** — which edit types matter most per benchmark/model
5. **Table: Sample efficiency** — evaluations-to-first-improvement for each method
6. **Figure: Scaling curve by optimization** — does distillation help more for small or large models?

## Timeline Integration

| Week | Activity |
|------|----------|
| W1 | Seed feedback on existing traces, run Experiment 1 (distillation standalone, 3 models × 3 benchmarks) |
| W2 | Run Experiment 2 (head-to-head GEPA vs DSPy vs distillation, matched cost budget) |
| W3 | Run Experiment 3 (stacking combinations) in parallel with Phase 2b LoRA/SFT runs |
| W4 | Run Experiment 4+5 (cost frontier analysis, edit attribution) — mostly post-processing |
| W5 | Full evaluation (Step 3) with best stacked configs |
| W6 | Write results section, generate figures |

## Open Questions

1. **Teacher model choice:** Should we compare `claude-opus-4-6` vs `claude-sonnet-4-6` as the teacher? Cheaper teacher = cheaper distillation, but possibly worse diagnosis quality. This is an ablation study worth running.

2. **Iterative distillation:** The current experiments run one distillation session. What happens with 3-5 sequential sessions? Does the system plateau, or does each session find new failure modes? This maps to the spec's `parent_session_id` chain feature.

3. **Cross-model transfer:** If we run distillation on Qwen-9B, do the resulting config edits (routing rules, prompt improvements) also help Qwen-2B and Qwen-27B? The spec says config applies to any model, so this should work — but the improvement magnitude may vary.

4. **Personal benchmark vs standard benchmarks:** The gate uses a personal benchmark mined from traces. How does gating on personal benchmarks compare to gating on standard benchmarks (PinchBench, TauBench)? Is the personal benchmark a better proxy for real-world improvement?
