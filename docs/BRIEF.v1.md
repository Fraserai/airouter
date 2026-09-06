# Build Brief — Intelligent AI API Router

**How to use this document:** save it to your repo root as `BRIEF.md`, open Claude Code in that directory, and start with:

> Read `BRIEF.md` end to end. Do not start coding. First, write `PLAN.md` containing your interpretation of the thesis, your proposed stack, the repo layout you intend to create, and any disagreements with the brief stated in one line each. Then stop and wait for my approval.

Everything below is the spec. Section 1 is the product thesis and is fixed — implement it, don't redesign it.

---

## 1. The thesis (fixed — do not modify)

We believe enterprises will and should use **80% open models and 20% closed frontier models** — as a share of total organisational AI spend and usage.

Our routing system is intelligent from the ground up. **The best frontier model in the world is the intelligence of the router.** Today that means models like Claude Fable 5.1 or GPT-6 Astra at the top. These models have extensive reasoning, tool use, agentic, coding and software engineering capabilities that are very powerful when focused on being the best AI router.

The router decides which model, and how, should handle each inference request. Its objective is: **the highest quality output for the cheapest cost.**

Open models and closed frontier models are both available to the router. Roughly 80% of usage should be suited to open models, while the hardest and highest-value ~20% goes to closed frontier models.

When a better frontier model becomes the best in the world, **it becomes the new router intelligence.** The previous frontier routing models remain available in the model pool.

The enterprise therefore actually gets to spend *more* on frontier closed intelligence, because 80% of spend goes to open models which are cheap — the savings fund the frontier 20%, and the intelligence router manages all of it.

Routing is not just open-vs-closed. It is an intelligent switch across **local open models, cloud-hosted open models, and closed frontier APIs.**

**The interesting problem, stated plainly:** as models get more powerful you end up delegating your smartest model the job of figuring out when *not* to use itself — when to go to an open model instead. That is the fun area to solve, and it is the core of this product.

---

## 2. The hard problem — read this before you design anything

There is a recursion in the thesis that a naive implementation will get wrong, and getting it right is the whole product.

If the frontier model is consulted on every request in order to decide where that request should go, you pay frontier prices on 100% of traffic and the 80/20 economics collapse. The router costs more than the thing it was meant to make cheap.

So "the best frontier model is the intelligence of the router" must be implemented as **the frontier model being the author of the routing policy, not the executor of every routing decision.** Its intelligence lives in the system in three places:

| Where | What the frontier model does | Cost profile |
|---|---|---|
| **Offline — policy compiler** | Periodically reviews execution traces, outcomes, costs and failures; rewrites the routing policy, difficulty rubrics, capability profiles and escalation thresholds. | Batch, amortised over millions of requests. |
| **Online — hard calls only** | Decides routing live for requests the fast path flags as ambiguous, novel, or high-stakes. | Target ≤5% of requests. |
| **Online — final answer** | Handles the hardest ~20% of *work*, as an executor rather than a router. | The 20% the thesis budgets for. |

The fast path — the thing that actually touches ~95% of requests — must be a cheap, distilled artifact that the frontier model *wrote*. Build the decision path in tiers:

- **Tier 0 — deterministic.** Exact/semantic cache hits, explicit per-route overrides, hard policy constraints (data residency, PII, compliance). Sub-millisecond, zero marginal cost.
- **Tier 1 — distilled classifier.** A small local model or a trained classifier that predicts difficulty class and required capabilities from request features. Single-digit milliseconds, effectively free. Its rubric and its training labels come from Tier 2.
- **Tier 2 — frontier router.** Live consultation for the ambiguous tail. Every Tier 2 decision is logged as a training example that improves Tier 1.

Track and expose **routing overhead as a percentage of total spend.** If it exceeds ~3%, the router is failing at its own thesis. Make this a first-class metric on the dashboard, not a footnote.

---

## 3. Seed model registry

Transcribed from the Artificial Analysis Intelligence Index v4.2 snapshot dated **6 Sep 2026**. Source: `https://artificialanalysis.ai/#intelligence`.

The index incorporates 10 evaluations: AA-Briefcase, GDPval-AA v2, τ³-Banking, Terminal-Bench v2.1, SciCode, Humanity's Last Exam, GDP.pdf, CritPt, AA-Omniscience, AA-LCR v1.1.

| # | Model | Index | Lab | Access (seed, unverified) |
|---|---|---|---|---|
| 1 | Claude Fable 5.1 (max, with fallback) | 57 | Anthropic | Closed |
| 2 | GPT-6 Astra (max) | 55 | OpenAI | Closed |
| 3 | Claude Opus 5 (max) | 54 | Anthropic | Closed |
| 4 | Claude Fable 5 (with fallback) | 53 | Anthropic | Closed |
| 5 | Muse Spark 1.3 (max) | 53 | Meta | Open |
| 6 | GPT-5.6 Sol (max) | 51 | OpenAI | Closed |
| 7 | Grok 4.6 (high) | 51 | xAI | Closed |
| 8 | Kimi K3 (max) | 50 | Moonshot | Open |
| 9 | GLM-5.3 (max) | 49 | Z.ai | Open |
| 10 | Gemini 3.8 Flash (high) | 47 | Google | Closed |
| 11 | GPT-5.6 Terra (max) | 47 | OpenAI | Closed |
| 12 | Qwen3.8 2.4T A95B | 47 | Alibaba | Open |
| 13 | GLM-5.3-Flash | 46 | Z.ai | Open |
| 14 | GPT-5.6 Luna (max) | 43 | OpenAI | Closed |
| 15 | DeepSeek V4 Pro 0813 (max) | 42 | DeepSeek | Open |
| 16 | Qwen3.8 27B (xhigh) | 41 | Alibaba | Open |
| 17 | K2 Horizon 375B A23B | 38 | — | Open |
| 18 | MiniMax-M3 | 36 | MiniMax | Open |
| 19 | Inkling | 32 | Thinking Machines | Unknown |
| 20 | Gemini 3.5 Flash-Lite | 28 | Google | Closed |
| 21 | Muse Glimmer (high) | 24 | Meta | Open |
| 22 | gpt-oss-120b (high) | 16 | OpenAI | Open |

### Rules for handling this table

1. **It is seed data, not truth.** It goes in `config/models.seed.yaml` and is loaded at boot. Nothing about it may be hardcoded in routing logic.
2. **The access column is unverified.** Before any model is enabled for production routing, its open/closed status, licence, context window, modality support and per-token pricing must be confirmed against the provider and recorded in the registry with a `verified_at` timestamp. Ship a `scripts/verify_registry.py` that fails loudly on unverified entries.
3. **A single index score is not a capability profile.** The registry must carry per-eval scores where available (the 10 sub-evals above), because routing decisions are capability-specific: a model strong on Terminal-Bench and weak on AA-LCR should get long-horizon coding work and not long-context retrieval work. Design the schema for the sub-scores even if you seed only the composite on day one.
4. **The top model is a variable.** `router.intelligence_model` is a config key. Changing it must be a one-line config change plus a policy recompile — never a code change. This directly implements "when a better frontier model becomes the best in the world, it becomes the new router intelligence."
5. **Demoted routers stay in the pool.** When the intelligence model changes, the previous one is reclassified as an executor, not removed. Model lifecycle states: `candidate → executor → router → executor → deprecated`.
6. Note that entries 1 and 4 are labelled "with fallback" — the published score reflects a system where some queries are served by a secondary model. That is itself a routing product, and a useful reference point for how a fallback path changes measured quality. Worth reading up on before designing the escalation ladder.

### Placement tiers

Every registry entry carries a `placement`, because "open vs closed" is not enough to route on:

- `local` — runs on the enterprise's own hardware. Zero marginal token cost, fixed capital/ops cost, lowest latency, strongest data-residency guarantee, capacity-bound. Small dense and small-MoE open models.
- `cloud_open` — open-weight models served by an inference provider. Cheap per token, elastic, no capex, but data leaves the perimeter. Large open MoEs live here.
- `closed_frontier` — proprietary API. Highest capability, highest cost per token, hard rate limits.

The cost model for `local` is fundamentally different from the other two: it is amortised, not per-token. Implement it as such — a utilisation-aware effective cost per token derived from hardware cost, throughput and current queue depth. Do not fake it with a flat per-token number.

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
                          │       → T2 frontier (tail)      │
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
                          │  quality gate; retry one tier up│
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
```

### Modules

- `gateway/` — OpenAI-compatible HTTP surface, streaming passthrough, auth, tenancy, request normalisation.
- `registry/` — model catalogue, capability profiles, pricing, placement, health, lifecycle state.
- `router/` — the three-tier decision path; emits a `RoutingPlan`.
- `providers/` — one adapter per provider behind a single interface; local, cloud-open and closed all look identical to the router.
- `verifier/` — output quality gates and the escalation ladder.
- `governor/` — budget enforcement and the 80/20 spend-mix controller.
- `ledger/` — append-only record of every request and every routing decision.
- `compiler/` — offline policy compilation by the frontier model.
- `evals/` — the harness that proves the whole thing works.
- `dashboard/` — the operator view.

---

## 5. Routing algorithm

For each request:

1. **Normalise.** Extract features: token count, task type, presence of code/tools/structured-output requirements, context length, latency SLO, tenant policy constraints, declared value tier.
2. **Tier 0.** Check semantic cache. Check hard constraints — if the tenant forbids data leaving the perimeter, the candidate set is `local` only and everything downstream respects that. Constraints are filters, never preferences.
3. **Tier 1.** Predict `difficulty ∈ {trivial, routine, hard, frontier}` and a required-capability vector. Emit a confidence score.
4. **Tier 2, conditionally.** If Tier 1 confidence is below threshold, or the request is flagged high-stakes, or it is structurally novel, consult the frontier router. Log the decision as a Tier 1 training example. Budget this path explicitly.
5. **Select.** Filter the registry to models meeting the capability floor and the hard constraints, then pick the cheapest that clears it — the cost-quality frontier, not the highest score. Break ties on latency, then on placement preference (`local > cloud_open > closed_frontier`).
6. **Execute** through the provider adapter, streaming where the client asked for it.
7. **Verify.** Run the quality gate appropriate to the task class. Cheap gates first: schema validity, does the code compile, does the test suite pass, self-consistency across samples. A frontier-model judge is the expensive last resort and should be sampled, not universal.
8. **Escalate on failure.** Retry exactly one tier up. Cap escalations per request. A request that escalates twice is a Tier 1 misprediction — log it as such and make sure the compiler sees it.
9. **Record** everything to the ledger.

### Design constraints

- **Escalation must be cheaper than pre-emption, on average.** If a cheap-first-then-escalate path costs more than routing straight to frontier, the difficulty classifier is wrong. Measure this ratio continuously and surface it.
- **Never let cost optimisation silently degrade quality.** The objective is "best quality for cheapest cost", not "cheapest". Cost is minimised *subject to* a quality floor. The floor is a config value per task class and it is not negotiable at runtime.
- **The 80/20 is an outcome, not a quota.** Do not hard-cap traffic to hit the ratio — that would degrade quality to satisfy a number. Instead, treat a large deviation as a signal: if only 40% is going to open models, either the classifier is too conservative or the open pool is under-provisioned. Surface it as an alert with a diagnosis, and let the governor apply pressure only within the quality floor.

---

## 6. The 80/20 governor

Implement as a controller, not a gate:

- Track rolling spend and request mix across the three placements, per tenant and globally.
- Target: 80% of spend on open (local + cloud_open), 20% on closed frontier. Configurable.
- When frontier spend runs hot, raise the bar for Tier 1 to route frontier — but only up to the point where the quality floor binds. Quality floor always wins over ratio.
- When frontier spend runs cold, that is the thesis working. Report the freed budget explicitly as **"frontier headroom earned"** — this is the mechanism by which the enterprise gets *more* frontier intelligence, and it should be the headline number on the dashboard.
- Expose a counterfactual: what this traffic would have cost if every request had gone to the current frontier model. `savings = counterfactual − actual`. This is the single most important number the product produces. Compute it honestly, including routing overhead and escalation waste.

---

## 7. API surface

- `POST /v1/chat/completions` — OpenAI-compatible, streaming and non-streaming. Drop-in: existing SDKs point at this URL and work unchanged.
- Request extensions (all optional, namespaced under `x-router-*` headers or a `router` object in the body): `quality_floor`, `max_cost_usd`, `latency_slo_ms`, `placement_allow`, `pin_model`, `explain`.
- `explain: true` returns the `RoutingPlan` alongside the completion — which model, why, what it cost, what it would have cost on frontier, whether it escalated. Operators will not trust the router until they can see this. Build it early.
- `GET /v1/models` — the live registry.
- `GET /v1/routing/stats` — mix, spend, savings, overhead, escalation rate.
- `POST /v1/routing/simulate` — dry-run a request or a replayed trace file, return the plan and projected cost without executing. Essential for pre-sales and for regression testing policy changes.

---

## 8. Stack

Default unless you have a specific reason to deviate — if you do, state it in one line in `PLAN.md` and proceed:

- **Python 3.12 + FastAPI** for the gateway and services.
- **LiteLLM** for provider abstraction where it fits; drop to raw HTTP for anything it handles badly, especially local backends.
- **Postgres** for registry and ledger (SQLite for local dev). The ledger is append-only and will get large — partition by day from the start.
- **Redis** for the semantic cache and rolling spend counters.
- **vLLM** as the primary local serving target, with Ollama supported for developer machines.
- **React + Vite** single-page dashboard.
- **pytest** throughout, with the eval harness as a separate long-running suite.

Non-negotiables regardless of stack: config-driven registry, no vendor names in routing logic, every routing decision reproducible from the ledger, provider adapters behind one interface.

---

## 9. Milestones

Build in this order. Each milestone must be independently runnable and demoable.

**M0 — Skeleton.** Repo, config loading, registry from `models.seed.yaml`, `/v1/models`, health checks, one provider adapter end to end. No routing yet — a fixed model, proven to work.

**M1 — Gateway.** Full OpenAI-compatible completions endpoint with streaming. Three provider adapters live: one local, one cloud-open, one closed. Ledger writing every request with real token counts and real costs.

**M2 — Tier 0 + Tier 1 routing.** Deterministic rules, hard constraints, semantic cache. A first-pass difficulty classifier — heuristic is fine at this stage, it will be replaced. Cost-quality selection. `explain: true` working. **This is the first milestone that demonstrates the thesis** — show the spend mix and the savings number.

**M3 — Verification and escalation.** Quality gates per task class, the escalation ladder, escalation accounting. Prove that cheap-first-then-escalate beats straight-to-frontier on cost at equal quality, on at least one real workload.

**M4 — Tier 2 and the policy compiler.** Live frontier routing for the ambiguous tail. The offline compiler that reads traces and rewrites Tier 0 rules and Tier 1 labels. Demonstrate Tier 1 improving from Tier 2's decisions over a replayed trace set. **This is the intellectual core — do not rush it.**

**M5 — Governor and dashboard.** The 80/20 controller, counterfactual savings, frontier headroom earned, routing overhead, quality floor monitoring, alerts.

**M6 — Model swap drill.** Change `router.intelligence_model` in config, recompile policy, verify the previous router is reclassified as an executor and stays in the pool, verify no code changed. This drill is the acceptance test for the thesis's "when a better model arrives it becomes the router" claim, and it should run in CI against a mock registry.

---

## 10. Evals and acceptance criteria

Build the harness before M2 — you cannot tune a router without it.

The harness replays a labelled request set through the full stack and reports: quality per task class, total cost, cost vs. all-frontier counterfactual, spend mix by placement, escalation rate, Tier 1 misprediction rate, routing overhead as % of spend, p50/p95 latency.

The system is working when, on a representative enterprise workload:

1. **Quality:** within 2% of the all-frontier baseline on every task class, and never below the configured floor on any class.
2. **Cost:** at least 60% below the all-frontier baseline.
3. **Mix:** 75–85% of spend on open models, achieved without breaching the quality floor.
4. **Overhead:** routing costs under 3% of total spend.
5. **Escalation:** under 10% of requests escalate; under 1% escalate twice.
6. **Latency:** routing adds under 50ms at p95 on the Tier 0/Tier 1 path.
7. **Explainability:** every request in the ledger can be replayed to the same routing decision.

If a criterion cannot be met, do not quietly relax it. Write down why in `FINDINGS.md` and raise it.

---

## 11. Non-goals

- Not building a model. Not fine-tuning frontier models.
- Not a general-purpose LLM observability platform. The ledger serves routing; it is not a Datadog competitor.
- Not a prompt-optimisation product. The router picks models and parameters; it does not rewrite the user's prompt beyond adapters required for a target model's format.
- Not solving multi-tenant billing and invoicing in v1. Track spend per tenant; do not build the billing system.

---

## 12. Open questions to resolve in `PLAN.md`

Answer these before writing code. Where you have to guess, say so and say what would change your mind.

1. How do we set the quality floor for open-ended generation, where there is no test suite and no schema to validate against? Sampled frontier judge is the obvious answer — what makes it affordable and unbiased?
2. What is the right retraining cadence for Tier 1, and what triggers an unscheduled recompile? Model registry change, misprediction rate breach, distribution shift — which of these do we detect and how?
3. How does the router handle multi-turn conversations and agentic loops, where a single "request" is dozens of inferences with wildly different difficulty? Per-turn routing is the obvious answer, but state and consistency across a switch is not trivial — what breaks?
4. What is the cold-start behaviour on a new tenant with no trace history? Ship with a conservative default policy that over-routes to frontier and cheapens as it learns, or ship with the global policy and accept early misses?
5. How do we detect and handle a model that silently degrades — a provider quantising a served open model, or a frontier API changing behaviour behind a stable version string? This is a real operational risk for anyone routing across providers and the registry needs an answer.
6. What is the failure mode when the frontier router itself is unavailable? Tier 1 must degrade gracefully, not fail closed — define the behaviour explicitly.

---

## 13. Working agreement for Claude Code

- Write `PLAN.md` first. Wait for approval before implementing.
- Small commits, each independently reviewable, conventional commit messages.
- Tests alongside code, not after. The eval harness is not optional and is not "tests" — build both.
- No vendor name, model name or price appears in routing logic. Ever. Config only.
- When the brief is ambiguous, implement the interpretation that best serves the thesis in Section 1, and note the ambiguity in `FINDINGS.md`.
- When you believe the brief is wrong, say so once, clearly, with the reasoning — then implement as specified unless told otherwise. Section 1 is fixed; everything else is negotiable with an argument.
