# Build Brief — Intelligent AI API Router

**Status:** v2, incorporating corrections from the M0 planning pass. Section 1 is fixed. Everything else is negotiable with an argument — and several things in v1 were wrong and have been fixed here because that argument was made.

**How to use this document:** save to the repo root as `BRIEF.md`. If a `PLAN.md` already exists, reconcile it against this version and note any conflicts before proceeding.

---

## 1. The thesis (fixed — do not modify)

### Why this is worth building

The new idea here is delegating to a single best closed frontier model **whose sole job is to delegate** — to route work and outcomes to the best open-weight or closed frontier model across our split. Not a model that also routes. A model hired to route.

The 80% is the exciting part, not the compromise, because of what a frontier router can do in the world of open models we have today. The open field got good enough that a smart enough router reaching into it gets frontier-adjacent outcomes across most of the workload. That is what makes this buildable now and not two years ago.

This sets a new genre for what "AI router" means.

### The thesis

We believe enterprises will and should use **80% open models and 20% closed frontier models** — as a share of total organisational AI spend and usage.

Our routing system is intelligent from the ground up. **The best frontier model in the world is the intelligence of the router.** Today that means models like Claude Fable 5.1 or GPT-6 Astra at the top. These models have extensive reasoning, tool use, agentic, coding and software engineering capabilities that are very powerful when focused on being the best AI router.

The router decides which model, and how, should handle each inference request. Its objective is: **the highest quality output for the cheapest cost.**

Open models and closed frontier models are both available to the router. Roughly 80% of usage should be suited to open models, while the hardest and highest-value ~20% goes to closed frontier models.

When a better frontier model becomes the best in the world, **it becomes the new router intelligence.** The previous frontier routing models remain available in the model pool.

The enterprise therefore gets to spend *more* on frontier closed intelligence, because 80% goes to open models which are cheap — the savings fund the frontier 20%, and the intelligence router manages all of it.

Routing is not just open-vs-closed. It is an intelligent switch across **local open models, cloud-hosted open models, and closed frontier APIs.**

**The interesting problem, stated plainly:** as models get more powerful you end up delegating your smartest model the job of figuring out when *not* to use itself — when to go to an open model instead. That is the fun area to solve, and it is the core of this product.

---

## 2. The hard problem — read this before you design anything

There is a recursion in the thesis that a naive implementation will get wrong, and getting it right is the whole product.

If the frontier model is consulted on every request in order to decide where that request should go, you pay frontier prices on 100% of traffic and the economics collapse. The router costs more than the thing it was meant to make cheap.

So "the best frontier model is the intelligence of the router" must be implemented as **the frontier model being the author of the routing policy, not the executor of every routing decision.** Its intelligence lives in the system in three places:

| Where | What the frontier model does | Cost profile |
|---|---|---|
| **Offline — policy compiler** | Reviews execution traces, outcomes, costs and failures; rewrites the routing policy, difficulty rubrics, capability profiles and escalation thresholds. | Batch, amortised over millions of requests. |
| **Online — hard calls only** | Decides routing live for requests the fast path flags as ambiguous, novel, or high-stakes. | Budgeted in **spend**, not request count — see below. |
| **Online — final answer** | Handles the hardest ~20% of *work*, as an executor rather than a router. | The 20% the thesis budgets for. |

### The three-tier decision path

- **Tier 0 — deterministic.** Cache hits, per-route overrides, hard policy constraints (data residency, PII, compliance). Sub-millisecond, zero marginal cost.
- **Tier 1 — distilled classifier.** A small local model or trained classifier predicting difficulty class and required capabilities from request features. Single-digit milliseconds. Its rubric and training labels come from Tier 2.
- **Tier 2 — frontier router.** Live consultation for the ambiguous tail. Every Tier 2 decision is logged as a Tier 1 training example.

### Tier 2 must never see the full request

The ambiguous tail correlates positively with context length — the requests Tier 1 can't classify tend to be the long, strange ones. A Tier 2 that reads whole prompts would therefore cost *more* than simply executing them, and it would do so invisibly, showing up only in the monthly bill.

Tier 2 receives a **bounded digest** — a fixed-size summary of request features, never the raw prompt — against a **prompt-cached rubric**. A consult must cost on the order of 1/50th of a frontier execution. Enforce the digest bound structurally, in the type system, not by convention.

### Budget Tier 2 in spend, not request count

An earlier version of this brief capped Tier 2 at "≤5% of requests." That is the wrong unit: because the tail skews long, 5% of requests can be a large multiple of that share of routing cost. **Tier 2 gets a spend budget.** When the budget is exhausted in a window, Tier 1 handles everything and degrades conservatively.

Track and expose **routing overhead** as a first-class dashboard metric. See §10 for the correct denominator — it is not total actual spend.

---

## 3. Seed model registry

Transcribed from the Artificial Analysis Intelligence Index v4.2 snapshot dated **6 Sep 2026**. Source: `https://artificialanalysis.ai/#intelligence`.

Index incorporates 10 evaluations: AA-Briefcase, GDPval-AA v2, τ³-Banking, Terminal-Bench v2.1, SciCode, Humanity's Last Exam, GDP.pdf, CritPt, AA-Omniscience, AA-LCR v1.1.

Cost data from the companion chart, Cost per Intelligence Index Task, same date: weighted average USD per index task, segmented by token type (answer, reasoning, cache write, cache hit, input). Lower is better.

| # | Model | Index | Cost/task | Index per $ | Lab | Access (unverified) |
|---|---|---|---|---|---|---|
| 1 | Claude Fable 5.1 (max, with fallback) | 57 | $6.12 | 9 | Anthropic | Closed |
| 2 | GPT-6 Astra (max) | 55 | $2.57 | 21 | OpenAI | Closed |
| 3 | Claude Opus 5 (max) | 54 | $4.21 | 13 | Anthropic | Closed |
| 4 | Claude Fable 5 (with fallback) | 53 | $5.62 | 9 | Anthropic | Closed |
| 5 | Muse Spark 1.3 (max) | 53 | $0.96 | 55 | Meta | Open |
| 6 | GPT-5.6 Sol (max) | 51 | $1.25 | 41 | OpenAI | Closed |
| 7 | Grok 4.6 (high) | 51 | $1.25 | 41 | xAI | Closed |
| 8 | Kimi K3 (max) | 50 | $1.58 | 32 | Moonshot | Open |
| 9 | GLM-5.3 (max) | 49 | $1.26 | 39 | Z.ai | Open |
| 10 | Gemini 3.8 Flash (high) | 47 | $0.74 | 64 | Google | Closed |
| 11 | GPT-5.6 Terra (max) | 47 | $0.81 | 58 | OpenAI | Closed |
| 12 | Qwen3.8 2.4T A95B | 47 | $1.10 | 43 | Alibaba | Open |
| 13 | GLM-5.3-Flash | 46 | $0.18 | 256 | Z.ai | Open |
| 14 | GPT-5.6 Luna (max) | 43 | $0.10 | 430 | OpenAI | Closed |
| 15 | DeepSeek V4 Pro 0813 (max) | 42 | $0.33 | 127 | DeepSeek | Open |
| 16 | Qwen3.8 27B (xhigh) | 41 | $0.57 | 72 | Alibaba | Open |
| 17 | K2 Horizon 375B A23B | 38 | no data | — | — | Open |
| 18 | MiniMax-M3 | 36 | $0.23 | 157 | MiniMax | Open |
| 19 | Inkling | 32 | $0.44 | 73 | Thinking Machines | Unknown |
| 20 | Gemini 3.5 Flash-Lite | 28 | $0.08 | 350 | Google | Closed |
| 21 | Muse Glimmer (high) | 24 | $0.04 | 600 | Meta | Open |
| 22 | gpt-oss-120b (high) | 16 | $0.12 | 133 | OpenAI | Open |

### What the cost data changes

**Cheap does not mean open.** GPT-5.6 Luna is closed, costs $0.10/task, and scores 43 — cheaper than most open models in this pool and stronger than several. Gemini 3.5 Flash-Lite is closed at $0.08. The open/closed axis is a governance and residency concern; it is not a proxy for cost, and routing logic must never treat it as one. The 80/20 target is a business commitment tracked by the governor, not an input to per-request selection.

**"Index per $" is a browsing aid, not a routing rule.** It is included to make the spread legible, nothing more. A model with a great ratio that sits below the task's capability floor is useless at any price. The selection rule in §5 stands unchanged: filter to models clearing the floor, then take the cheapest survivor.

**Effort settings are a routing lever.** The suffixes — (max), (high), (xhigh) — are effort dials on the same underlying model, and both charts price and score each setting separately. The registry must model `(model, effort)` as the routable unit, not `model`. This gives the router a cheaper move than switching models: turn the dial down first, switch families second. Escalation should walk effort settings before it walks model tiers.

**Reasoning tokens dominate frontier cost.** On the expensive bars the reasoning segment is the largest component. Any capability that reduces reasoning tokens — tighter prompts, cached rubrics, effort dials — attacks the biggest line item. This is also why §2's bounded digest matters so much: a Tier 2 consult that triggers full reasoning is the single easiest way to destroy the economics.

**The headline number:** Fable 5.1 costs roughly 61x what Luna costs for about 33% more index. The whole business case is in that ratio. Reproduce it in the eval harness as a sanity baseline.

**Data gap:** K2 Horizon 375B A23B appears on the intelligence chart but not the cost chart. It has no price and must be marked `cost_unknown` and excluded from routing until priced. Any registry entry lacking a verified cost is ineligible — a router that cannot price a model cannot choose it responsibly.

### Rules for handling this table

1. **Seed data, not truth.** Goes in `config/models.seed.yaml`, loaded at boot. Nothing about it is hardcoded in routing logic.
2. **The access column is unverified.** Before any model is enabled for production routing, confirm open/closed status, licence, context window, modality support and per-token pricing against the provider, recorded with a `verified_at` timestamp. Ship `scripts/verify_registry.py` that fails loudly on unverified entries. A router that silently misclassifies a closed model as open is a compliance incident, not a bug.
3. **A single index score is not a capability profile.** Carry per-eval scores where available — routing is capability-specific. A model strong on Terminal-Bench and weak on AA-LCR gets long-horizon coding work, not long-context retrieval. Design the schema for sub-scores even if you seed only the composite.
4. **The top model is a variable.** `router.intelligence_model` is a config key. Changing it is a one-line config change plus a policy recompile — never a code change.
5. **Demoted routers stay in the pool.** Lifecycle: `candidate → executor → router → executor → deprecated`.
6. Entries 1 and 4 are labelled "with fallback" — the published score reflects a system where some queries are served by a secondary model. That is itself a routing product, and a useful reference for how a fallback path changes measured quality. Read up before designing the escalation ladder.

### Placement tiers

Every entry carries a `placement`:

- `local` — enterprise hardware. Lowest latency, strongest residency guarantee, capacity-bound.
- `cloud_open` — open-weight models served by an inference provider. Cheap per token, elastic, no capex, data leaves the perimeter.
- `closed_frontier` — proprietary API. Highest capability, highest cost, hard rate limits.

### Local cost needs two numbers, not one

This is a correction to v1, which asked for a single utilisation-aware cost and would have produced wrong behaviour in both directions:

- **Marginal cost — drives routing.** Energy plus a congestion term that converges on the spill price as queue depth approaches the SLO. Route on allocated cost instead and an idle GPU looks expensive, so you never use the hardware you already bought.
- **Allocated cost — drives reporting.** Amortised capex over achieved throughput. Report on marginal instead and you book savings you did not make.

Both numbers live in the registry. Never substitute one for the other.

---

## 4. Architecture

```
                          ┌─────────────────────────────────┐
   OpenAI-compatible      │          GATEWAY                │
   client  ───────────►   │  /v1/chat/completions           │
                          │  auth · tenant · budget check   │
                          └───────────────┬─────────────────┘
                                          │
                          ┌───────────────▼─────────────────┐
                          │        ROUTER CORE              │
                          │  T0 cache/rules → T1 classifier │
                          │   → T2 frontier (digest only)   │
                          │  = plan { model, params, verify }│
                          └───────────────┬─────────────────┘
                                          │
                    ┌─────────────────────┼─────────────────────┐
                    ▼                     ▼                     ▼
             ┌────────────┐        ┌────────────┐        ┌────────────┐
             │   LOCAL    │        │ CLOUD OPEN │        │   CLOSED   │
             │ vLLM/Ollama│        │ Together,  │        │ Anthropic, │
             │ llama.cpp  │        │ Fireworks, │        │ OpenAI,    │
             │            │        │ Groq, ...  │        │ Google,xAI │
             └──────┬─────┘        └──────┬─────┘        └──────┬─────┘
                    └─────────────────────┼─────────────────────┘
                                          │
                          ┌───────────────▼─────────────────┐
                          │   VERIFIER  →  ESCALATOR        │
                          │  independent judge; retry one   │
                          │  tier up                        │
                          └───────────────┬─────────────────┘
                                          │
                          ┌───────────────▼─────────────────┐
                          │  LEDGER (every request: model,  │
                          │  cost, latency, tokens, verdict)│
                          └───────────────┬─────────────────┘
                                          │
                     ┌────────────────────┴────────────────────┐
                     ▼                                         ▼
          ┌────────────────────┐                    ┌────────────────────┐
          │  POLICY COMPILER   │                    │    DASHBOARD       │
          │  offline, frontier │◄───── traces ──────│  80/20 · savings   │
          │  rewrites T0/T1    │                    │  quality · overhead│
          └────────────────────┘                    └────────────────────┘
             (never grades its own output — see §5)
```

### Modules

- `gateway/` — OpenAI-compatible HTTP surface, streaming, auth, tenancy, normalisation.
- `registry/` — catalogue, capability profiles, dual cost model, placement, health, lifecycle.
- `router/` — three-tier decision path; emits a `RoutingPlan`.
- `providers/` — one adapter per provider behind a single interface.
- `verifier/` — quality gates, independent judging, escalation ladder.
- `governor/` — budget enforcement and the 80/20 controller.
- `ledger/` — append-only record of every request and decision.
- `compiler/` — offline policy compilation.
- `evals/` — the harness that proves the thing works.
- `dashboard/` — operator view.

---

## 5. Routing algorithm

1. **Normalise.** Extract features: token count, task type, code/tool/structured-output requirements, context length, latency SLO, tenant constraints, declared value tier.
2. **Tier 0.** Cache check. Hard constraints — if the tenant forbids data leaving the perimeter, the candidate set is `local` only. Constraints are filters, never preferences.
3. **Tier 1.** Predict `difficulty ∈ {trivial, routine, hard, frontier}` plus a required-capability vector, with a confidence score.
4. **Tier 2, conditionally.** If confidence is below threshold, or the request is high-stakes or structurally novel, and the Tier 2 spend budget has room: send the **bounded digest** to the frontier router against the cached rubric. Log the decision as a Tier 1 training example.
5. **Select.** Filter to models meeting the capability floor and hard constraints; pick the cheapest that clears it — the cost-quality frontier, not the highest score. Tie-break on latency, then placement (`local > cloud_open > closed_frontier`).
6. **Execute** through the provider adapter, streaming where requested.
7. **Verify.** Cheap gates first: schema validity, compilation, test suite, self-consistency across samples. Model-as-judge is the expensive last resort, sampled rather than universal.
8. **Escalate on failure.** Retry exactly one tier up. Cap escalations per request. Two escalations is a Tier 1 misprediction — log it as such and ensure the compiler sees it.
9. **Record** everything to the ledger.

### The judge must not be the policy author

A router whose rubric is graded by the model that wrote it is a closed loop that drifts toward justifying itself — quality scores rise while real quality does not, and nothing in the telemetry reveals it.

Therefore: **judging model comes from a different lab than the policy compiler.** Blinded — the judge does not know which model produced the output or what the router predicted. Calibrated against a human-labelled gold set. Judge-human agreement is tracked continuously and is a **promotion gate**: policy changes do not ship if agreement has degraded.

This means the project needs API access to a second frontier lab purely for grading. Budget for it.

### Other constraints

- **Escalation must be cheaper than pre-emption, on average.** If cheap-first-then-escalate costs more than routing straight to frontier, the classifier is wrong. Measure the ratio continuously.
- **Cost optimisation must never silently degrade quality.** The objective is best quality for cheapest cost, not cheapest. Cost is minimised *subject to* a quality floor, set per task class, not negotiable at runtime.
- **The 80/20 is an outcome, not a quota.** Do not hard-cap traffic to hit the ratio. A large deviation is a signal — if only 40% is going open, either the classifier is too conservative or the open pool is under-provisioned. Alert with a diagnosis; apply governor pressure only within the quality floor.

---

## 6. The 80/20 governor

A controller, not a gate:

- Track rolling spend and request mix across placements, per tenant and globally.
- Target 80% open (local + cloud_open), 20% closed frontier. Configurable.
- When frontier spend runs hot, raise the bar for routing frontier — up to the point where the quality floor binds. Quality floor always wins over ratio.
- When frontier spend runs cold, report the freed budget as **"frontier headroom earned."** This is the mechanism by which savings buy more frontier intelligence, and it is the headline the thesis promises.

### The counterfactual needs shadow calibration

`savings = counterfactual − actual` is the most important number the product produces, and the naive computation of it is wrong.

You cannot assume the frontier model would have emitted the same number of output tokens for the same request. Multiplying observed tokens by frontier prices produces a number that is confidently incorrect and biased in an unknown direction.

Instead: **shadow-execute a sampled subset** of real traffic on the frontier model, measure the actual token and cost distribution, and use that to calibrate the counterfactual for the rest. Report the savings figure with its confidence interval. Sampled shadow execution costs real money — treat it as a line item, not an afterthought.

---

## 7. API surface

- `POST /v1/chat/completions` — OpenAI-compatible, streaming and non-streaming. Drop-in.
- Request extensions (optional, `x-router-*` headers or a `router` object): `quality_floor`, `max_cost_usd`, `latency_slo_ms`, `placement_allow`, `pin_model`, `explain`.
- `explain: true` returns the `RoutingPlan` — which model, why, actual cost, calibrated counterfactual, whether it escalated. Operators will not trust the router until they can see this. Build it early.
- `GET /v1/models` — live registry.
- `GET /v1/routing/stats` — mix, spend, savings with CI, overhead, escalation rate, judge-human agreement.
- `POST /v1/routing/simulate` — dry-run a request or replayed trace, return plan and projected cost without executing.

---

## 8. Stack and environment

Confirmed environment: Python 3.11.3 on PATH, no Docker, Postgres, Redis or Ollama available.

- **Python 3.12 pinned via `uv`.**
- **FastAPI** for gateway and services.
- **SQLite plus an in-process cache through M2**, behind the same interfaces Postgres and Redis will implement from M3. Do not let SQLite assumptions leak past the repository layer.
- **LiteLLM** for provider abstraction where it fits; raw HTTP where it doesn't, especially local backends.
- **vLLM** as the primary local serving target when hardware is available; Ollama for developer machines. Local placement is stubbed but interface-complete until then.
- **React + Vite** single-page dashboard.
- **pytest** throughout; the eval harness is a separate long-running suite.

Non-negotiable regardless of stack: config-driven registry, no vendor or model names in routing logic, every routing decision reproducible from the ledger, all providers behind one interface.

---

## 9. Milestones

Each must be independently runnable and demoable.

**M0 — Skeleton.** Repo, config loading, registry from seed YAML, `/v1/models`, health checks, one provider adapter end to end. Fixed model, no routing.

**M1 — Gateway.** Full OpenAI-compatible completions with streaming. Three adapters live: one local (stub acceptable), one cloud-open, one closed. Ledger recording real tokens and real costs.

**M2 — Tier 0 + Tier 1 routing.** Deterministic rules, hard constraints, cache. First-pass difficulty classifier — heuristic is fine, it will be replaced. Cost-quality selection. `explain: true` working. **First milestone demonstrating the thesis.**

**M3 — Verification and escalation.** Quality gates, independent judge with gold-set calibration, escalation ladder and accounting. Postgres and Redis swap in behind the M2 interfaces. Prove cheap-first-then-escalate beats straight-to-frontier at equal quality on at least one workload.

**M4 — Tier 2 and the policy compiler.** Bounded-digest live routing under a spend budget. The offline compiler reading traces and rewriting Tier 0 rules and Tier 1 labels. Demonstrate Tier 1 improving from Tier 2 decisions over replayed traces. **The intellectual core — do not rush it.**

**M5 — Governor and dashboard.** 80/20 controller, shadow-calibrated savings with CI, frontier headroom earned, overhead, quality floor monitoring, judge agreement, alerts.

**M6 — Model swap drill.** Change `router.intelligence_model` in config, recompile policy, verify the previous router is reclassified as executor and stays in the pool, verify no code changed. Runs in CI against a mock registry.

---

## 10. Evals and acceptance criteria

Build the harness before M2 — you cannot tune a router without it.

**Trace data:** synthesise until real traffic exists. Every figure derived from synthetic traffic must be **labelled provisional in the eval output itself**, not in a README. Synthetic data flatters routers, and an unlabelled number becomes a believed number within a week.

The system is working when, on representative traffic:

1. **Quality:** passes a **non-inferiority test** against the all-frontier baseline at a pre-registered margin, per task class. Not "within 2%" — at realistic sample sizes that is inside eval noise and would pass or fail on luck. State the margin and the power calculation before running.
2. **Cost:** at least 60% below the all-frontier baseline, reported with the shadow-calibrated confidence interval.
3. **Mix:** 75–85% open, achieved without breaching the quality floor.
4. **Overhead:** routing cost under 3% of **counterfactual** spend. The v1 brief used total actual spend as the denominator — that punishes success, since the denominator shrinks as the router works and fixed routing cost becomes a larger fraction of it. Also report absolute routing cost per request, which is denominator-free.
5. **Escalation:** under 10% of requests escalate; under 1% escalate twice.
6. **Latency:** routing adds under 50ms at p95 on the Tier 0/Tier 1 path.
7. **Judge integrity:** judge-human agreement above threshold on the gold set, tracked over time, gating policy promotion.
8. **Reproducibility:** every ledger request replays to the same routing decision.

If a criterion cannot be met, do not quietly relax it. Write down why in `FINDINGS.md` and raise it.

---

## 11. Non-goals

- Not building or fine-tuning a model.
- Not a general LLM observability platform. The ledger serves routing.
- Not a prompt-optimisation product. The router picks models and parameters; it does not rewrite user prompts beyond format adapters.
- Not multi-tenant billing in v1. Track spend per tenant; do not build invoicing.

---

## 12. Open questions

1. Quality floor for open-ended generation, where there is no test suite and no schema. Sampled independent judge is the shape of the answer — what makes it affordable *and* unbiased?
2. Tier 1 retraining cadence, and what triggers an unscheduled recompile: registry change, misprediction breach, distribution shift. Which do we detect, how?
3. Multi-turn and agentic loops, where one "request" is dozens of inferences of varying difficulty. Per-turn routing is obvious; state and consistency across a switch is not. What breaks?
4. Cold start on a new tenant with no trace history: conservative over-routing that cheapens as it learns, or the global policy with early misses accepted?
5. Silent model degradation — a provider quantising a served open model, or a frontier API changing behaviour behind a stable version string. Real operational risk; the registry needs an answer.
6. Tier 2 unavailability. Tier 1 must degrade gracefully, not fail closed. Define the behaviour explicitly.

---

## 13. Working agreement

- Small commits, independently reviewable, conventional messages.
- Tests alongside code. The eval harness is not "tests" — build both.
- No vendor name, model name or price in routing logic. Config only.
- When the brief is ambiguous, implement the interpretation that best serves the thesis in Section 1, and note it in `FINDINGS.md`.
- **When you believe the brief is wrong, say so and take the better option.** Several v1 criteria were wrong — the overhead denominator, the quality margin, the Tier 2 unit, the local cost model, the counterfactual arithmetic — and they were fixed because that argument was made rather than deferred. Apply the same scrutiny to everything here. Section 1 is fixed; nothing else is.
