# PLAN.md — Intelligent AI API Router

Status: **awaiting approval. No implementation code written.**
Read alongside `BRIEF.md`. Section numbers below refer to that document.

---

## 1. My interpretation of the thesis

The product is not a model picker. It is **a cost-allocation machine with a quality constraint**, whose allocation policy is authored by the best available intelligence and executed by something almost free.

Three claims in §1 that I am treating as the load-bearing ones:

1. **80/20 is a claim about spend, not about requests.** A 90/10 request split can still be a 30/70 spend split if the closed models are handling the long-context work. Every mix number in this system is therefore computed on spend first, with request counts reported alongside as a secondary diagnostic. Where the brief says "usage" I read "spend", because that is what funds the frontier headroom.

2. **"The best frontier model is the intelligence of the router" is a statement about authorship, not about invocation.** §2 already says this and it is correct. I would go one step further than the brief does: the frontier model's most valuable output is not a routing decision, it is a *rubric* — a compressed, inspectable statement of what makes a request hard and which capabilities it needs. The rubric is the product's real asset. Tier 1 is just a fast evaluator of it, and it should be replaceable (heuristic → trained classifier → small local model) without the rubric changing.

3. **The interesting recursion is a budget problem, and the budget is small.** "Delegating your smartest model the job of figuring out when not to use itself" is only interesting because the delegation must cost ~nothing. That constraint — not the classification accuracy — is what shapes the architecture. See §2 below.

What the system is optimising, precisely:

```
minimise   E[cost(request)]
subject to quality(request) ≥ floor(task_class)          # hard, per-config, non-negotiable at runtime
           latency(request) ≤ slo(request)               # hard
           placement(request) ∈ allowed(tenant)          # hard, a filter not a preference
           E[routing_overhead] ≤ 3% of spend             # hard, self-imposed
mix(open) → 80% of spend                                 # an outcome, observed and diagnosed, never enforced
```

The mix target is deliberately on a different line from the constraints. It is a *diagnostic*, and the governor may only apply pressure inside the feasible region the constraints define.

---

## 2. The recursion, resolved — with the budget written down

The brief says routing overhead must stay under 3% of spend. That single number determines almost every design decision downstream, so here is the decomposition I intend to build to, as config with these defaults:

| Overhead component | Budget (% of total spend) | Consequence |
|---|---|---|
| Tier 2 live consults | 2.0% | A consult must cost ≲ 1/50th of a frontier *execution* |
| Verification (judges, extra samples) | 0.7% | Judge is sampled and stratified, never universal |
| Policy compilation, amortised | 0.3% | Batch, nightly-to-weekly, over millions of requests |

The middle row of §2's table says Tier 2 should be "≤5% of requests". I think that is the wrong unit and I say so in §7. The consequence of budgeting in *spend* instead is the single most important design decision in this plan:

> **Tier 2 must never see the full request.** It receives a bounded digest — the feature vector, task-class signals, a truncated head/tail of the prompt, a structural sketch (schema, tool list, code language), and the retrieval-free summary of conversation state — capped at a fixed token budget. Its output is a small structured decision object. The rubric and instructions are prompt-cached.

If Tier 2 read whole prompts, a single consult on a 200k-token request would cost more than executing that request on a mid-tier open model, and the tail of ambiguous requests correlates *positively* with context length. That failure mode is silent, it only shows up in the monthly bill, and it would kill the product's central claim. Bounding the digest is the fix, and it has a real cost: Tier 2 decides with less information than the executor has. I would rather have a slightly worse decision made cheaply than an excellent decision that eats the savings — and the verifier plus escalation ladder is the safety net that makes that trade acceptable.

Corollary for the demo: I will report `overhead_pct_of_spend` **and** `overhead_pct_of_counterfactual`. See §7, disagreement 4.

---

## 3. Stack

Following §8 except where noted. Deviations, one line each:

- **Python 3.12 via `uv`, not the system Python** — this machine has 3.11.3 and no `uv`/`pyenv`; `uv` fetches a private 3.12 without touching the system install.
- **SQLite + in-process cache for M0–M2, Postgres + Redis from M3** — Docker, Postgres and Redis are not installed here; both sit behind `LedgerStore` / `CacheStore` interfaces from commit one, and the day-partitioned schema is written for Postgres from the start so the swap is configuration, not migration.
- **LiteLLM for `cloud_open` and `closed_frontier` only; raw HTTP for `local`** — LiteLLM's cost accounting is per-token by construction and would fight the amortised local cost model in §5.4, and local backends are where the brief already anticipates dropping down.
- **Ollama first as the local target, vLLM second** — vLLM does not run usefully on this Mac; the local adapter is written against an OpenAI-compatible surface so both work, and vLLM gets exercised in the eval harness against a remote host or a stub.
- Everything else as specified: FastAPI, React + Vite, pytest, day-partitioned append-only ledger.

**Enforcement of "no vendor names in routing logic"** — `scripts/lint_no_vendor.py` reads every vendor, model id, provider and price literal out of `config/`, then fails CI if any of them appears as a string or numeric literal anywhere under `router/`, `governor/`, `verifier/` or `registry/selection`. Also wired as a pre-commit hook. A rule that isn't mechanically enforced decays by M3.

---

## 4. Repo layout

```
ai-router/
├── BRIEF.md  PLAN.md  FINDINGS.md  README.md
├── pyproject.toml  .python-version  .pre-commit-config.yaml
├── config/
│   ├── models.seed.yaml          # §3 table, verbatim, verified:false everywhere
│   ├── router.yaml               # intelligence_model, tier thresholds, overhead budget
│   ├── quality_floors.yaml       # per task class — the non-negotiable floor
│   ├── placements.yaml           # local hardware cost model inputs, spill targets
│   ├── tenants/                  # per-tenant constraints, budgets, residency
│   └── policy/                   # COMPILED artifacts, versioned, git-tracked
│       ├── rubric.v001.md        #   the frontier model's rubric — human-readable
│       ├── tier0.v001.yaml       #   deterministic rules
│       └── tier1.v001.json       #   classifier weights / thresholds / labels
├── src/router_core/
│   ├── gateway/        app.py  openai_compat.py  streaming.py  auth.py  tenancy.py
│   ├── registry/       schema.py  store.py  capabilities.py  lifecycle.py  health.py
│   ├── router/         normalise.py  tier0.py  tier1.py  tier2.py  select.py  plan.py
│   ├── providers/      base.py  litellm_adapter.py  local_openai.py  registry_of_adapters.py
│   ├── verifier/       gates/  judge.py  escalator.py
│   ├── governor/       mix_controller.py  budgets.py  counterfactual.py
│   ├── ledger/         models.py  writer.py  replay.py  partitions.py
│   ├── compiler/       trace_sampler.py  compile.py  promote.py  shadow_eval.py
│   └── costing/        pricing.py  local_amortised.py  overhead.py
├── evals/
│   ├── harness/        replay.py  metrics.py  report.py
│   ├── workloads/      *.jsonl  + workload_spec.md
│   └── baselines/      all_frontier.py  pinned_open.py
├── dashboard/          (React + Vite)
├── scripts/            verify_registry.py  lint_no_vendor.py  swap_intelligence_model.py
└── tests/              unit + integration, mirroring src/
```

`config/policy/` being git-tracked is deliberate: a policy change is a reviewable diff, the rubric is readable by a human, and rollback is `git revert`. Every ledger row carries `policy_version` + `registry_version`, which is what makes acceptance criterion 7 (replayability) achievable rather than aspirational.

---

## 5. Core contracts I intend to fix before writing features

### 5.1 `RoutingPlan`
`request_id · tenant · policy_version · registry_version · deciding_tier{0,1,2} · features · difficulty · capability_vector · confidence · candidate_set · rejected[{model, reason}] · chosen{model, placement, params} · projected_cost · counterfactual_cost · verification_plan · escalation_budget · digest_hash · rng_seed`

`rejected[]` with reasons is not decoration — it is what makes `explain: true` convincing to an operator, and it is the field that turns a support ticket into a five-second answer.

### 5.2 Ledger row
The plan, plus: actual tokens in/out (from the provider, never estimated), actual cost, latency split into `routing_ms` / `ttft_ms` / `total_ms`, verifier verdict, escalation chain, cache-hit id if any, and the raw Tier 2 response when one was consulted.

### 5.3 Registry entry
```yaml
- id: <opaque>            # never a vendor string in code paths
  display_name: ...
  lab: ...
  placement: local | cloud_open | closed_frontier
  lifecycle: candidate | executor | router | deprecated | quarantined   # + quarantined, see Q5
  access: open | closed | unknown
  verified: false
  verified_at: null
  scores:
    composite: {value: 57, source: "AA v4.2", measured_at: 2026-09-06}
    aa_briefcase: null      # schema present day one, values as sourced
    gdpval_aa_v2: null
    tau3_banking: null
    terminal_bench_v2_1: null
    scicode: null
    hle: null
    gdp_pdf: null
    critpt: null
    aa_omniscience: null
    aa_lcr_v1_1: null
  context_window: null
  modalities: []
  pricing: null            # null until verified — never a guess
  fingerprint: null        # see Q5
  health: {state: unknown, checked_at: null}
```
`verified: false` + `pricing: null` means **ineligible for selection**. `scripts/verify_registry.py` fails loudly, as the brief requires. I will not invent a price to make a demo work; an unpriced model does not route.

### 5.4 The local cost model — two numbers, not one

The brief is right that a flat per-token number is a fake. But there is a second trap: there are **two** correct numbers and they are used for different things.

- `marginal_cost_per_token` — **used for routing.** Energy per token, plus a congestion term: as queue depth approaches the latency SLO, the true marginal cost of admitting one more request converges on the price of the `cloud_open` model you would spill to.
  `marginal = energy_per_tok + P(slo_breach | queue_depth) × spill_price_per_tok`
- `allocated_cost_per_token` — **used for reporting, mix and savings.** Amortised capex + power + ops over achieved throughput in the window.

Conflating them breaks the product in one direction or the other: route on *allocated* cost and an idle GPU looks expensive so you never use it; report on *marginal* cost and you book savings you did not make. Both go in the ledger; the dashboard shows allocated; the selector uses marginal.

---

## 6. Answers to the §12 open questions

### Q1 — Quality floor for open-ended generation
**Decision: the floor is relative, not absolute.** "Quality ≥ floor" for open-ended work is defined as *non-inferiority to a reference response* — win/tie rate against a reference of at least θ (config, per task class), measured by a sampled pairwise judge. Absolute 1–10 judge scores do not calibrate across task classes, drift between judge versions, and cannot be compared month to month.

What makes it **affordable**: cheap gates run first and most requests never reach a judge; judging is stratified — heavily sampled where the classifier was least confident or the chosen model was closest to the floor, sparsely sampled in the fat safe middle; judgments are cached on `(prompt_hash, response_hash, judge_version)`; the judge sees a bounded digest, same discipline as Tier 2; total judge spend is capped by the 0.7% line in §2 and the sampler adapts its rate to stay inside it.

What makes it **less biased** (not unbiased — I will not claim that): blind the judge to model identity, randomise A/B position and measure position bias explicitly, and — the important one — **the judge must not be the model that authored the policy.** Self-preference is well documented, and a router whose own rubric is graded by the model that wrote it is a closed loop that will quietly drift toward justifying itself. So: judge from a different lab than the policy author wherever the model pool allows it, calibrated against a small human-labelled gold set, with judge-vs-gold agreement tracked as a first-class metric that gates promotion of any new judge.

*Guessing here:* θ and the sampling rates. *What would change my mind:* if judge-vs-gold agreement comes in below ~0.7 on a task class, pairwise judging is not trustworthy for that class and it needs either a deterministic proxy gate or an honest "no floor enforceable here" entry in `FINDINGS.md` — not a number that looks like rigour and isn't.

### Q2 — Tier 1 retraining cadence and unscheduled triggers
Scheduled: nightly label refresh from the day's Tier 2 decisions; weekly full recompile.

Detected triggers, all of them, with the mechanism:
- **Registry change** (model added, removed, repriced, lifecycle change) → immediate recompile. Cheap and deterministic to detect: hash the registry.
- **Misprediction breach** → escalation rate, double-escalation rate and floor-breach rate monitored with a CUSUM / sequential test rather than a raw threshold, so a noisy hour doesn't trigger a recompile and a slow drift doesn't hide under one.
- **Distribution shift** → two signals: PSI on the feature vector, and a novelty rate (share of requests whose nearest-neighbour distance in embedding space to the training set exceeds a fixed percentile). Novelty rate is also the cold-start signal in Q4 and the tenant-onboarding signal — one mechanism, three uses.
- **Tier 2 consult rate exceeding its spend budget** → this means Tier 1 confidence is collapsing; recompile before the overhead budget is breached, not after.
- **Quality floor breach on any class** → immediate, and the governor stops applying mix pressure until it clears.

Guardrail: no compiled policy is promoted without a shadow evaluation on the replay set showing no regression; promotion is versioned; automatic rollback if live metrics regress against the previous version. A policy compiler that can push a bad policy straight to production is a bigger risk than a stale policy.

### Q3 — Multi-turn and agentic loops
Route per inference call, but bind decisions to a **session route context** (running difficulty estimate, incumbent model, coherence class, accumulated spend against the loop's budget), and only switch at **safe seams** — a turn boundary with no open tool call and no partial structured output.

What actually breaks on a switch, in rough order of how much it costs you:
1. **Prompt-cache economics.** Switching invalidates the cached prefix. On a long conversation the re-read of the transcript can cost more than simply staying on the more expensive model. This is the one most naive per-turn routers get wrong, and it means selection needs an explicit `switch_cost` term — the router must be able to decide that a *cheaper* model is the *more expensive* choice right now.
2. **Tool-call dialect.** ID formats, argument-schema strictness and parallel-call conventions differ; a model handed a transcript containing another model's tool calls can produce malformed continuations.
3. **Reasoning-trace continuity.** Models that emit thinking blocks cannot reliably consume another model's traces.
4. **Persona and format discontinuity** — visible to the end user, and the thing that generates the "your router feels broken" complaint even when quality metrics look fine.
5. **Difficulty is non-stationary within a session.** Turn 30 carries far more context than turn 1, so the *same* nominal task crosses the long-context capability floor purely by accumulation. The capability vector must be recomputed per turn, not inherited.

Policy: sticky by default, switch on justification. Escalations ratchet — they persist for N turns (hysteresis) so the router doesn't flap. Agentic loops get a budget scoped to the **loop**, not the step, so a runaway loop cannot escalate its way through the tenant's month.

### Q4 — Cold start on a new tenant
**Neither option as posed.** Start on the global policy, but with a bounded, *visible* exploration budget: an elevated Tier 2 consult rate and an elevated verification sample rate for the tenant's first N requests, capped as a percentage of that tenant's spend and reported on the dashboard as "learning cost" rather than buried.

Reasoning: over-routing to frontier at cold start fails the demo in exactly the week the customer is watching for savings, and it teaches the classifier nothing about *this* tenant that a conservative default policy didn't already assume. Paying for exploration at Tier 2 (a cheap structured decision) instead of at execution (expensive tokens) buys more information per dollar, and the verifier plus escalation ladder already exists to catch the early misses.

*What would change my mind:* if the novelty metric from Q2 shows the tenant's first ~100 requests are genuinely out of distribution against the global trace set, that tenant automatically falls back to a conservative frontier-heavy policy and the dashboard says so explicitly, with the reason.

### Q5 — Silent model degradation
Three layers, cheapest first:

1. **Passive online signals**, free, on every request, per `(provider, model, served_fingerprint)`: verifier pass rate, tool-call malformation rate, refusal rate, output-length distribution, and throughput. Note that a quantised model usually gets **faster** — an unexplained speedup at a stable version string is one of the strongest early tells, and most monitoring only alerts on slowdowns.
2. **Behavioural fingerprint**, scheduled and cheap: a fixed seeded probe set at temperature 0, hashed; plus `system_fingerprint` where the provider exposes it. A fingerprint change under an unchanged version string is the alarm.
3. **Canary suite**, scheduled: deterministic probes where possible (exact answers, schema validity, code that compiles and passes tests) plus a small paired-comparison judge set, tracked as a time series with control limits.

Handling: a confirmed change moves the model to `lifecycle: quarantined` — removed from the candidate set, traffic shifted to the next model clearing the floor, and an alert raised with the specific signal that fired. Re-entry requires re-verification and a fresh `verified_at`. Quarantine is a lifecycle state I am adding to the five in §3 rule 5, because "deprecated" is a decision and this is a suspicion.

This shares its whole harness with the counterfactual shadow-sampling in Q-below and the judge gold set. One probe runner, three consumers.

### Q6 — Frontier router unavailable
**Fail open, never fail closed, and distinguish two different outages.**

- **Tier 2 (router) unavailable:** Tier 0 and Tier 1 do not call out, so they keep working on the last-known-good compiled policy — this is the main argument for the policy being a local artifact rather than a live service. Requests that would have been escalated to Tier 2 are decided by Tier 1 with a widened confidence band, tagged `t2_unavailable`, given a raised verification sample rate, and **queued for retro-consult** when Tier 2 returns so the training labels are not simply lost. High-stakes requests take the conservative branch and route one tier up, because on those the cost of being wrong exceeds the saving. Circuit breaker with exponential backoff; the dashboard shows degraded mode prominently rather than silently.
- **Frontier *executor* unavailable:** a separate circuit breaker. The escalation ladder needs a defined terminal state: escalate to the next-best available executor clearing the floor — which may be another lab's frontier or the top open model. If **nothing** available clears the floor, return an explicit error to the client. That follows directly from §5's "never let cost optimisation silently degrade quality": serving below-floor output without saying so is the one failure this system must not have.

---

## 7. Where I disagree with the brief

One line each, as asked. I will implement as specified on all of these unless you say otherwise; where I have proposed an alternative I have said which one I intend to build.

1. **§2 "Tier 2 ≤5% of requests" should be a budget in spend, not request count** — the ambiguous tail correlates with long context, so 5% of requests can easily be 40%+ of routing spend; I intend to enforce a spend budget and report the request percentage alongside it.
2. **§10.1 "within 2% of the all-frontier baseline" is inside the noise of most eval harnesses at realistic sample sizes** — I will implement it as a non-inferiority test with a stated confidence interval and report the required sample size, otherwise the criterion produces both false passes and false alarms.
3. **§10.4 "overhead under 3% of total spend" has the wrong denominator** — as the router succeeds, total spend falls and overhead percentage rises mechanically, so the metric punishes success; I will report it as specified *and* against the all-frontier counterfactual, which is the stable denominator.
4. **§6's counterfactual cannot assume the frontier model would have emitted the same number of output tokens** — multiplying observed token counts by frontier prices inflates the headline savings number; I intend to calibrate an output-token ratio per task class from shadow samples, and to state the counterfactual as a range with its method visible.
5. **§5.5 "pick the cheapest that clears the capability floor" is fragile exactly at the boundary** — I intend cheapest-that-clears-*with-margin*, where the margin scales with classifier uncertainty, because a router that always picks the marginal model turns every misprediction into an escalation and escalation waste eats the savings.
6. **§3's composite index should not survive past M2 as a routing input** — routing on a single composite is precisely the mistake rule 3 warns against, so beyond M2 the capability floor should read the sub-eval vector, and models without sourced sub-scores should be ineligible for capability-specific work rather than scored by proxy.
7. **§9 M6's swap drill against a mock registry proves less than it appears** — a config-only swap is only really proven when the policy actually recompiles against the real pool, so I would run the CI drill as specified and additionally once against the real registry in staging.
8. **§10's acceptance numbers are only meaningful on "a representative enterprise workload", which does not exist in this repo yet** — I will build the harness with a pluggable workload adapter and seed it with a synthetic mix I label myself, and I will label every resulting number as measured against a proxy workload in `FINDINGS.md` rather than letting a synthetic benchmark quietly become the product's proof.

---

## 8. Milestones — what "done" means for each

Same order as §9, each independently runnable. Acceptance is what I will demo.

- **M0 Skeleton** — config + registry load from seed, `/v1/models`, health, one adapter end to end on a fixed model, `verify_registry.py` failing loudly on unverified entries (this is the *expected* state on day one), `lint_no_vendor.py` green in CI.
- **M1 Gateway** — full OpenAI-compatible completions incl. streaming, three adapters (one per placement), ledger writing real token counts and real costs, replay of a ledger row reproducing the request. Drop-in proof: an unmodified OpenAI SDK client works against it.
- **Eval harness (before M2, as the brief requires)** — replay, metrics, all-frontier baseline, seed workload with its `workload_spec.md` stating honestly what it is and is not.
- **M2 T0+T1** — cache, hard-constraint filters, heuristic classifier, cost-quality selection with margin, `explain: true` returning the full plan with `rejected[]` reasons. Demo: spend mix and savings number on the seed workload.
- **M3 Verify + escalate** — gates per task class, ladder, escalation accounting, and the specific measurement the brief asks for: cheap-first-then-escalate vs straight-to-frontier at equal quality, with the ratio surfaced continuously.
- **M4 T2 + compiler** — bounded-digest Tier 2, trace sampling, rubric + policy compilation, shadow eval, versioned promotion with rollback. Demo: Tier 1 measurably improving from Tier 2's labels across a replayed trace set, with the before/after on the same workload.
- **M5 Governor + dashboard** — mix controller acting only inside the quality floor, counterfactual with its stated method, frontier headroom earned as the headline, overhead on both denominators, floor monitoring, alerts with diagnoses rather than bare thresholds.
- **M6 Swap drill** — one config line changes `router.intelligence_model`; policy recompiles; the previous router becomes `executor` and stays in the pool; `git diff --stat src/` is empty. In CI against a mock registry, plus once against the real pool.

---

## 9. What I need from you before M0

1. **Directory name** — the working directory is `~/AI ROUTER ` with a **trailing space**, which will break tooling in small confusing ways. May I rename it to `~/ai-router`?
2. **git** — not a repo yet; confirm I should `git init` with conventional commits per §13.
3. **Credentials** — I need at minimum one closed frontier provider, one cloud-open host, and either Ollama running locally or a vLLM endpoint. Tell me which you have and I will scope M1's three adapters to those; everything else stays `verified: false` and unroutable.
4. **Workload** — do you have any real or anonymised trace set? If not I will synthesise and label one, and flag it as a proxy per disagreement 8.
5. **Compiler budget** — M4 makes real frontier calls to compile policy. Give me a ceiling per compile run.
6. **Postgres/Redis timing** — confirm you are happy with SQLite + in-process cache through M2 given nothing is installed on this machine, swapping at M3.

Nothing above is implemented. Say the word and I start at M0.
