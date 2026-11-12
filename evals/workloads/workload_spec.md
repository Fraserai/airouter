# Synthetic smoke workload, version 1

Twelve original, manually authored cases: four extraction, four elementary
reasoning/arithmetic, and four classification. Each has a deterministic expected
string, returned in a strict JSON object with exactly one `answer` field. The
expected answer is retained for grading and is not sent to the executor.

The purpose is to validate the gateway, structured responses, token accounting,
request replay, and comparison reporting before routing is introduced. This is
not a representative enterprise sample, a capability benchmark, training data,
or a held-out quality test. Do not promote routing policies from these results.

The runner executes every case against each explicitly selected model, rotates
model order between cases, caps each completion at 128 tokens, and stops when
cost is unknown or the next conservative reservation exceeds the run budget.
The byte-based reservation is a precaution; invoice spend is not guaranteed by
a tokenizer estimate. No retries or model judging add hidden execution costs.

Success requires valid JSON, exactly the requested schema, a normal completion,
no refusal, and the expected string after trimming surrounding whitespace.
Schema correctness alone is not answer correctness. Failed requests remain in
the denominator. Incomplete runs and unknown spend are labelled in the results.

Reports include per-class counts, provider-reported usage, request IDs, model
and price snapshots, dataset hash, cost, latency, and Wilson 95% intervals. The
intervals are descriptive under an independence assumption; these small,
related templates do not justify population claims. The selected baseline is
not called a frontier baseline unless independently verified as such in future.

Before business acceptance we still need representative held-out workloads,
pre-registered non-inferiority margins and sample sizes, an independent judge
calibrated against human labels for open-ended tasks, and real paired/shadow
frontier executions to measure savings with uncertainty.
