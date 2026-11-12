# Model Router — current product brief

Authority: the user's September 9, 2026 vision and instruction to replace the
previous product scope. This document supersedes the earlier brief and plans.

## The product

An enterprise sends its AI workload through one Model Router API. A frontier
model reasons about the request and chooses the lowest-cost available model it
judges capable of completing it. Execution comes from one shared pool of open
and closed models, including the routing model itself.

The current supplied snapshot selects GPT-6 Astra as the brain: intelligence 53,
benchmark cost $3.26 versus Claude Fable 5.1 at 53 and $7.63. These are benchmark
observations, not verified API prices or guarantees of equal workload quality.

When a better frontier model is configured, it becomes the brain. Previous
leaders remain in the execution pool. Model identity and pricing live in
configuration, not provider-specific selection rules.

## Four parts

1. Intelligent routing layer: understand the request and assess capability needed.
2. Model pool: open and closed models are possible suppliers, including the brain.
3. API endpoint: one interface hides model/provider selection from applications.
4. Enterprise user: pays for the intelligence required by its workloads.

## Boundaries

No autonomous jobs, decomposition, worker orchestration, policy compiler,
open-spend governor, exploration program or target execution share. They are
removed from the active product. Request accounting, protocol validation and
provider configuration support the four-part product; they do not expand it.

The website mockup is exploratory. Its layout, copy and proposed interactions
are not final implementation requirements. Provider logos do not certify access.

## Evidence

Keep the supplied 23-model snapshot intact and dated. Do not infer missing
per-token prices, exact effort parity, licenses or API access. Assess workload
quality and total cost, including the routing consultation, before claiming
customer savings. An unavailable brain must not silently become cheap fixed
selection in live mode.
