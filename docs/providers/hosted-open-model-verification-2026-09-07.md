# Hosted open-model provider handoff

Research date: 2026-09-07 (UTC). Status: official-documentation review only; no authenticated inference, account provisioning, credential access, or configuration changes. Prepared for Astra's gateway/evaluation work. The working checkout is changing concurrently; code observations below are a snapshot, not a claim about the final implementation.

## Recommendation

Use Together serverless if the user has no existing provider preference. My integration recommendation is to verify Llama 3.3 first, then evaluate Qwen3.5 9B with reasoning disabled. Llama is the protocol baseline; Qwen is the more interesting low-cost candidate. This ordering follows the current parser's limitations, not a model-quality ranking. An existing working Fireworks account would be a good reason to use the alternative below instead of opening another account.

Evaluation design remains with the lead; its runner schema is now available. None of these candidates has passed the router's quality floor or live acceptance tests. See the [subsequent compatibility delta](together-compatibility-delta-2026-09-07.md) for offline reproductions and the current product alignment.

## Together candidates

Exact deployment metadata from the [live serverless catalog](https://docs.together.ai/docs/serverless/models), opened 2026-09-07. Rates are USD per million tokens; the dash is an unpublished cached rate, not a zero price. All three list function calling and structured outputs as supported.

| API model ID | Context tokens | Quantization | Input | Cached input | Output |
| --- | ---: | --- | ---: | --- | ---: |
| `meta-llama/Llama-3.3-70B-Instruct-Turbo` | 131072 | FP8 | 1.04 | — | 1.04 |
| `Qwen/Qwen3.5-9B` | 262144 | FP8 | 0.17 | — | 0.25 |
| `openai/gpt-oss-120b` | 131072 | MXFP4 | 0.15 | — | 0.60 |

The older search index listed `Qwen/Qwen3-235B-A22B-Instruct-2507-tput`; the opened catalog did not. Do not promote that older endpoint on search-snippet evidence. Absence here is not proof of global discontinuation.

### Access and model licences

Together requires its own account and API key; authenticate with Bearer auth using base URL `https://api.together.ai/v1`. The chat route is `/chat/completions`; the key environment-variable convention is `TOGETHER_API_KEY`. OpenAI account credentials are not a substitute. [Official authentication](https://docs.together.ai/docs/api-keys-authentication), [client setup](https://docs.together.ai/docs/inference/openai-compatibility).

The current self-service billing page specifies a minimum $5 credit purchase, a positive prepaid balance, and no free trial. Existing contracted accounts may differ. No purchase was made. [Credits](https://docs.together.ai/docs/billing-credits).

- Llama: text model under the Llama 3.3 Community License, with an acceptable-use policy and conditional commercial/redistribution obligations. Its weights download is gated on Hugging Face. Do not assume that download gate is also a hosted-API prerequisite. [Publisher card and licence](https://huggingface.co/meta-llama/Llama-3.3-70B-Instruct).
- Qwen: published weights under Apache 2.0; model supports text and vision. Our proposed first evaluation uses text only. [Publisher card](https://huggingface.co/Qwen/Qwen3.5-9B).
- GPT-OSS: text model, Apache 2.0, with configurable reasoning effort. Hosted access and model licensing are separate from provider account terms. [Publisher card](https://huggingface.co/openai/gpt-oss-120b).

### Reasoning and structured answers

Together lists Qwen3.5 9B as hybrid with reasoning on by default. Its documented switch is `reasoning: {enabled: false}`. GPT-OSS uses `reasoning_effort` values low/medium/high; low does not mean off. Reasoning output is included in billed completion tokens. [Reasoning guide](https://docs.together.ai/docs/inference/chat/reasoning).

Together's structured-output example explicitly combines Qwen3.5 9B, disabled reasoning, and `response_format.type = json_schema`. The guide also asks for a JSON instruction and schema in the prompt. Treat this as documented functionality requiring a live check, including the subset of JSON Schema and behavior of `strict`. Schema conformance alone does not prove semantic correctness. [Structured outputs](https://docs.together.ai/docs/inference/chat/structured-outputs).

## Integration findings for Astra

Observed in `src/router_core/providers/chat_api.py` and `providers/messages.py` during this review:

1. **Qwen reasoning toggle cannot currently be expressed through provider defaults.** The adapter allowlist accepts `store`, `service_tier`, `reasoning_effort`, and `verbosity`; neither `reasoning` nor `chat_template_kwargs` is allowed. Supporting the documented toggle needs Astra's implementation work before claiming a configured non-reasoning deployment.
2. **Non-empty reasoning fields can reject otherwise valid completions.** The completion parser rejects populated fields outside `Message`; the strict streaming delta has no reasoning fields either. This is an inferred compatibility failure from the code plus Together's documented response shapes, not a reproduced live error. Include empty/null extension fields in streaming fixtures too.
3. **Cache accounting can silently miss flat usage fields.** `parse_usage` currently reads nested `prompt_tokens_details.cached_tokens`. Together documents both that shape and top-level `usage.cached_tokens`. Preserve the original sanitized usage evidence and test both shapes before assigning discounts.

Together documents ignored `store`/`service_tier` parameters and model-dependent reasoning fields; `store: false` should therefore not be treated as a provider retention control. [Compatibility reference](https://docs.together.ai/docs/inference/openai-compatibility).

Use the documented `max_tokens` parameter for the first verification. The factory already supports choosing that parameter. Start with system/user text messages and explicitly test developer-role handling later. [Parameter reference](https://docs.together.ai/docs/inference/chat/parameters). Whether every provider response passes the existing strict parser remains unverified.

## Pricing boundaries and illustrative arithmetic

For the three Together rows, no separate long-context tariff or cache-write tariff was established from the opened catalog. This is an unknown, not evidence of no surcharge. Do not import cached rates from another provider. Until conditions are established, report standard-rate estimates separately from verified billing, and flag unknown cost where the accounting contract requires it.

Proposed pilot scope: at most 4096 total prompt tokens and 256 total generated tokens per call, concurrency one, automatic retries disabled. These are our experimental limits, not provider guarantees or pricing thresholds. Prompt limits must include the rendered system prompt and tool/schema payload with a model-appropriate tokenizer.

Illustrative uncached token cost at exactly 1000 input + 256 output tokens:

| Deployment | Calculated USD/request |
| --- | ---: |
| Together Llama | 0.00130624 |
| Together Qwen | 0.00023400 |
| Together GPT-OSS | 0.00030360 |

Formula: `(input_tokens * input_rate + total_completion_tokens * output_rate) / 1,000,000`. Do not add reasoning tokens again when already included in completion usage. These are arithmetic examples, not forecasts: tokenizer differences, retrying, response lengths, quality failures, and provider conditions change actual cost. Measure cost per accepted task and end-to-end latency before making a savings claim.

## Alternative if the user has Fireworks

Use base URL `https://api.fireworks.ai/inference/v1`, Bearer authentication, and a Fireworks API key (`FIREWORKS_API_KEY` convention). [Text API setup](https://docs.fireworks.ai/guides/querying-text-models).

Candidate ID: `accounts/fireworks/models/gpt-oss-120b`. Its model page lists serverless access, text-only input, function calling, and approximately 128K context (also displayed as 131k). Streaming and structured outputs are described, but exact JSON-schema semantics and output ceilings require testing; the page's 100-token example is not a verified maximum. [Model page](https://fireworks.ai/models/fireworks/gpt-oss-120b).

Standard rates: $0.15 input / $0.015 cached input / $0.60 output per million tokens. Priority rates: $0.18 / $0.018 / $0.72. Keep tiers separate. Cache eligibility, write pricing, any context surcharge, account-specific access, and exact context token ceiling remain unverified for our integration. [Live pricing](https://docs.fireworks.ai/serverless/pricing). The reasoning-parser issue above still needs examination; changing provider does not establish compatibility.

## Proposed acceptance run once access is available

This is a handoff plan, not an executed test suite or authorization to spend.

1. Confirm the user's provider, model access, billing status, and server-side key setup through the approved secure flow. Never put the key in reports, fixtures, or ledger events.
2. Verify the exact model ID against the provider's authenticated catalog; record returned metadata, retrieval time, provider, deployment, quantization, and effort separately. IDs without an immutable revision do not imply fixed weights forever.
3. Make one bounded text request. Save sanitized request/response, provider request ID, finish reason, total usage, accounting status, and latency. Stop on invalid accounting or response shape.
4. Check a text stream through completion, final usage, and `[DONE]`; test a harmless synthetic tool call and tool-result round trip, first non-streaming and then streaming. Validate argument JSON without executing a real external tool.
5. Check a small schema-constrained extraction with deterministic expected fields. Exercise truncation and unsupported fields separately; require explicit failure rather than silently dropping constraints.
6. Reconcile a tiny batch against provider billing before applying cached discounts. Compare cold and repeated prefixes only after cache eligibility is documented. Test reasoning-on deployments independently from reasoning-off deployments.
7. Hand successful sanitized samples to Astra's runner once its schema is ready. Record failed attempts, retries, unknown costs, and all billed output in comparisons.

Missing user input remains the provider account or local endpoint they already have. Latency from Brisbane, rate limits on that account, full-context behavior, regional guarantees, invoice reconciliation, and task quality have not been measured. Documentation is sufficient to choose a verification candidate, not to mark it production-ready.
