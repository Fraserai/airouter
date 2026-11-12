# Together compatibility delta for the lead

Reviewed 2026-09-07, approximately 04:45 UTC. Checkout: `codex/gateway-evaluations`, HEAD `09836c5b060aac5eb7542b0e7bce49132f05e328`, plus the active uncommitted implementation. This review describes files read at that time, not only the HEAD commit. Scope: documentation and offline probes; no API calls or implementation changes.

Product alignment supplied by the lead: live frontier reasoning remains the routing intelligence. Deterministic constraints, metrics, and cached evidence support that intelligence. The intended approximately 80–90% open / 10–20% closed allocation concerns execution; router intelligence spend is tracked separately and included in total programme cost. The denominator and observation window for that allocation remain for the lead to specify. Non-reasoning executor candidates do not imply removing reasoning from the router. Multi-step enterprise jobs make faithful provider conversation state relevant.

## Documented wire contract

Together's [reasoning guide](https://docs.together.ai/docs/inference/chat/reasoning), reopened today, specifies:

- `Qwen/Qwen3.5-9B`: reasoning enabled by default; `reasoning: {enabled: false}` disables it, `true` enables it. The guide also shows `chat_template_kwargs.thinking` / `enable_thinking` as alternatives. Precedence when both are supplied is not established; use one mechanism.
- `openai/gpt-oss-120b`: `reasoning_effort` low/medium/high; low is not disabled. Returned reasoning uses `reasoning` on messages and streaming deltas.
- Other deployments can use `reasoning_content`; do not assume one universal field. Pass provider reasoning state back using its original field where required by that model's multi-turn protocol. GLM's documented preserved-thinking option uses `chat_template_kwargs.clear_thinking: false`; do not generalize that option to Qwen.
- Billed completion tokens include reasoning. Qwen's exact response-field behavior when disabled remains an authenticated-test question.

The [compatibility reference](https://docs.together.ai/docs/inference/openai-compatibility), reopened today, documents two usage shapes:

| Meaning | Wire location |
| --- | --- |
| Total input/output | `usage.prompt_tokens`, `usage.completion_tokens` |
| Nested cache count | `usage.prompt_tokens_details.cached_tokens` |
| Flat cache count, including some Llama deployments | `usage.cached_tokens` |
| Reasoning subset of output | `usage.completion_tokens_details.reasoning_tokens` |

It also says `store` and `service_tier` are accepted but ignored. They are not effective retention or service-tier controls here.

The [live catalog](https://docs.together.ai/docs/serverless/models), reopened today, still leaves cached-input rates blank for the shortlisted Llama, Qwen3.5 9B, and GPT-OSS 120B deployments. A reported cache hit does not establish a discounted tariff. No additional cache-write or context-tier pricing was established in this review.

## Confirmed local behavior and required decisions

Offline probes imported the current parser and message classes with bytecode writing disabled. Synthetic inputs below are examples we constructed, not provider responses. No client requests were sent and no ledger database was opened.

| Probe | Observed result | Implication |
| --- | --- | --- |
| Adapter defaults contain `reasoning: {enabled: false}` | Constructor raises `unsupported provider default parameter` | The preferred Qwen switch cannot currently be configured through that path. |
| Streaming delta contains `reasoning` with null, empty string, or nonempty synthetic text | All three fail strict validation | Disabling thinking alone may not ensure a valid stream if the endpoint retains the field. |
| Usage: 1000 input, 100 output, flat cache count 800 | Parsed cache count is 0 | Flat usage is silently misclassified as uncached. |
| Same totals, nested cache count 800 | Parsed cache count is 800 | Current parser is shape-sensitive. |
| Feed both parsed usages to `execution_cost` with $1.04 input/output and no cached tariff | Flat shape gives $0.001144; nested gives `None` | Missing normalization can bypass the ledger's unknown-price protection. This is a certainty/status error even before any actual discount is established. |

Code evidence: `ChatAPIAdapter.__init__`, `parse_usage`, and `stream` in `src/router_core/providers/chat_api.py`; `MessageDelta` in `providers/messages.py`; `execution_cost` in `ledger/store.py`.

Additional static findings:

- `complete` rejects truthy message extensions outside `Message.model_fields`; null/empty extras are filtered out there. Streaming validates the entire delta, so its behavior differs. This completion behavior was inspected, not exercised through a mock HTTP call.
- `ChatMessage` and `CompletionResult` have no dedicated reasoning-state fields, and `to_wire` has no such serialization. Merely accepting a response extension would not establish faithful multi-turn support. Keep model-internal state separate from user-facing final content and the router's decision explanation.
- `parse_usage` validates nonnegative integer counters and subset bounds; retain these checks when adding a provider normalizer. It does not validate `total_tokens` consistency today.

Recommended implementation decisions for the lead:

1. Add only typed, explicitly supported provider controls, and snapshot the effective control values for replay. Avoid enabling arbitrary pass-through fields merely to make the toggle work.
2. Normalize cache counts by key presence, not truthiness. Treat explicit zero as a value. If flat and nested counts coexist and disagree, flag an accounting conflict instead of silently choosing one or adding them.
3. Preserve absent versus reported-zero reasoning details where feasible. Include reasoning in total output once; missing detailed breakdown need not invalidate known total output.
4. For positive cached usage with an unpublished rate, retain unknown exact cost under the existing ledger contract. A standard-input-rate estimate can be shown separately if labelled; do not disguise it as invoice-verified cost. Never copy Fireworks' cached tariff into Together.
5. Normalize documented response extensions consistently across full responses and SSE. Keep unexplained fields explicit rather than silently discarding potentially meaningful provider state.

## Remaining acceptance gates

The lead should confirm model-specific disabled-mode response fields, final streaming usage, schema strictness, tool-result continuation, truncation, and role handling with sanitized live samples once provider access is available. Cache eligibility/TTL, write charges, context surcharges, and invoice treatment still require evidence. The bounded pilot limits in the earlier memo are experimental controls, not verified pricing thresholds.

Suggested offline cases for the lead's existing suite: both usage shapes; explicit zero versus absent; conflicting dual fields; invalid counters; empty/nonempty reasoning deltas; reasoning-only deltas preceding final content; terminal usage with no choices; and continuation preserving the model's original reasoning-state field. No competing evaluation schema or test files were added.

Decision: the recommendation remains conditional on provider access. Llama is a useful first protocol probe; Qwen non-reasoning needs the control path fixed; GPT-OSS needs explicit reasoning handling. None is presently certified end-to-end by this review.
