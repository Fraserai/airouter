# Gateway security and API-compatibility review — 2026-09-07

## Scope and evidence

This is a bounded read-only review of the current gateway, provider adapters,
and ledger. It covers `src/router_core/gateway/`, `src/router_core/providers/`,
and `src/router_core/ledger/`, with the existing tests in `tests/` as evidence.
The focused suite passed:

```text
.venv/bin/python -m pytest -q
100% passed (one Starlette deprecation warning)
```

The current code is explicitly M0/dev-oriented. Findings marked production
blocker are acceptable only while the process is protected by loopback or an
equivalent authenticated network boundary.

## Findings

### P0 — No gateway authentication or tenant authorization

`src/router_core/gateway/app.py:68-90`, `:92-133`, and `:135-136` expose
`/health`, `/v1/models`, `/v1/routing/stats`, and the paid completion endpoint
without any authentication or authorization. The README acknowledges this at
`README.md:69-70`, but the same application code is used for `live` and
`production`; binding to a non-loopback interface or placing it behind a
misconfigured proxy would let an unauthenticated caller spend the provider key,
read registry metadata, and inspect aggregate spend.

This is a production blocker, not a routing-quality issue. Add an explicit
auth/tenant boundary before any externally reachable deployment. Decide whether
health is public; keep model inventory, spend statistics, and completions
protected. Add tests for missing, invalid, and valid credentials, plus tenant
isolation for ledger reads and model constraints.

### P0 — Full prompts and provider payloads are retained indefinitely in plaintext

The `started` event stores the original request, normalized request, model
snapshot, and (when supported) the complete provider payload at
`src/router_core/gateway/app.py:188-206`. This includes conversation text,
tool arguments, and structured-output schemas. `SQLiteLedger` writes the JSON
directly to the configured database at `src/router_core/ledger/store.py:47-67`,
with no retention policy, redaction, encryption, or access-control setup. The
README confirms the retention behavior at `README.md:82-84`.

This is reasonable for a single-user local debug ledger but unsafe for
enterprise traffic. Make retention and redaction explicit, protect the database
file, and support a no-prompt/hashed-audit mode. Add tests proving credentials,
authorization headers, and configured sensitive fields are absent, and tests
that expired events are removed or rendered inaccessible.

### P1 — Unbounded request bodies and message fields permit memory/disk abuse

`ChatCompletionRequest.messages` only limits the number of messages
(`src/router_core/gateway/openai_compat.py:47-67`); message content, tool
arguments, tool descriptions, schemas, and stop strings have no size limits
(`src/router_core/providers/messages.py:14-22`, `:47-57`, and `:68-83`). The
same payload is then duplicated into the ledger. There is no application body
limit in `src/router_core/gateway/app.py`.

An authenticated caller could still exhaust memory, upstream token budget, or
local disk with one oversized request. Add an ingress/body limit and per-field
limits appropriate to the supported protocol, then test oversized content,
tool arguments, schemas, and cumulative conversation history before the
provider is contacted or the request is persisted.

### P1 — Ledger statistics scan and deserialize the entire database on the event loop

`/v1/routing/stats` calls the synchronous `SQLiteLedger.stats()` directly from
an async route (`src/router_core/gateway/app.py:88-90`). `stats()` loads every
event and JSON payload into memory (`src/router_core/ledger/store.py:80-84`)
and recomputes all totals on every request (`:85-105`). Because payloads include
full prompts, latency and memory grow with traffic and `/v1/routing/stats` can
block completion requests or become a low-effort denial-of-service target.

Use indexed aggregate queries or maintained counters, bound the reporting
window, and move blocking I/O off the event loop if SQLite remains the backend.
Add a scale test with a large ledger and assert bounded response time/memory.

### P1 — Cost accounting trusts `Usage` values outside the adapter parser

`Usage` is an unconstrained dataclass at `src/router_core/providers/base.py:52-69`.
`execution_cost()` subtracts and multiplies those values without checking that
all token counts are non-negative or that output/reasoning counts are
consistent (`src/router_core/ledger/store.py:16-37`). The current HTTP adapter
does validate upstream counts in `chat_api.py:21-42`, but a future/local/custom
adapter can produce a negative cost or inconsistent ledger entry.

Treat usage validation as an interface invariant, not only an HTTP parsing
property. Add tests for negative input/output/cached/write/reasoning counts,
cached-plus-write overflow, and non-finite numeric values; reject them before
costs reach the ledger.

### P1 — Unexpected adapter exceptions are not converted into a safe terminal response

Non-streaming requests only catch `ProviderError` and cancellation at
`src/router_core/gateway/app.py:276-284`. Any unexpected adapter exception
escapes as a framework 500, after the `started` event has been written but
without a corresponding `failed` event. Streaming requests catch only
`ProviderError` at `:225-268`; an unexpected exception terminates the SSE
connection and is recorded as `cancelled` by the `finally` block, which masks
the distinction between client cancellation and provider/application failure.

Add a final sanitized exception boundary, preserve cancellation semantics, and
record a distinct internal failure event. Acceptance tests should inject a
generic exception in both complete and stream paths, assert no sensitive error
text reaches the client, and assert exactly one terminal ledger event.

### P2 — Malformed provider messages with falsey unknown fields are accepted

`ChatAPIAdapter.complete()` computes unknown response fields but rejects only
when their values are truthy (`src/router_core/providers/chat_api.py:134-142`):

```python
if any(message_raw[k] for k in unsupported):
```

An upstream message containing `{"content": "ok", "debug": false}` is
therefore accepted even though the adapter otherwise intends strict protocol
validation. Unknown fields should be rejected by key presence, or explicitly
ignored by documented compatibility policy. Add falsey `0`, `false`, `""`,
`null`, and nested-object cases to the malformed-response tests.

### P2 — Streaming loses provider fingerprint and provider timing telemetry

Non-streaming completions record `provider_fingerprint` at
`src/router_core/gateway/app.py:286-291`. `StreamChunk` has no fingerprint or
timing fields (`src/router_core/providers/base.py:86-91`), and the streaming
completion event records only finish reason (`app.py:253`). The adapter also
does not preserve stream-level `system_fingerprint` or time-to-first-token.

This makes streamed traffic invisible to model-drift and latency analysis even
though the result type supports those fields. Either define the streaming
telemetry contract or document it as unavailable; add a test that a streamed
fingerprint and TTFT are retained when the provider supplies them.

### P2 — Duplicate adapter coverage silently depends on registration order

`AdapterRegistry.register()` accepts every adapter and `for_model()` returns the
first adapter whose `supports()` returns true (`src/router_core/providers/base.py:118-134`).
A configuration or plugin mistake that registers the same model with two
providers silently sends traffic to whichever was registered first.

Reject duplicate model coverage at registration/build time and add a test that
the conflict fails closed with the provider names in the diagnostic.

### P2 — Readiness can report healthy with no adapters

`health()` computes status with `all(...)` over adapter health values
(`src/router_core/gateway/app.py:71-84`). Python returns `True` for `all([])`.
If configuration produces no registered adapters, the endpoint can report
`status: ok` even though every completion will fail with “no adapter serves
model id”. Add an explicit empty-adapter check and an acceptance test for
production configuration with no usable provider.

## Compatibility notes

- The existing tests cover the normal OpenAI SDK path, tool-call history,
  streamed tool arguments, usage discounts, sanitized upstream HTTP errors,
  truncated streams, and replay. Those tests passed.
- The implementation intentionally supports only a subset of the Chat
  Completions protocol and rejects unsupported fields. That is acceptable for
  M0 if clients receive a stable 422; the README should remain the source of
  truth until broader protocol support is added.
- The lack of gateway authentication, plaintext prompt persistence, and
  unbounded request size are the issues that must be addressed before a
  non-loopback or multi-tenant deployment. The other findings are important
  correctness/observability hardening but do not require changing the live
  frontier routing design.
