# Model Router

**More intelligence. Less cost.**

One API for enterprise AI workloads. A frontier model assesses each request and
selects the lowest-cost model it judges capable of handling it from a shared
pool of open and closed models. The brain is also an executor in that pool.

The September 9 pivot replaces the previous scope. The supplied website mockup
is provisional; this repository currently delivers the API and an operator view.

## Request flow

```text
Enterprise application → Model Router API → Frontier routing brain
                                         → Selected pool model → Response
```

`model="auto"` uses runtime routing by default. The brain receives a bounded
request digest, eligible deployments, dated intelligence references and projected
execution costs. Its structured selection is validated before one model executes.

The catalog's highest intelligence score identifies the intended brain; benchmark
cost breaks ties. The supplied September 8 snapshot selects GPT-6 Astra. Updating
the catalog or setting `router.intelligence_model` changes the brain on restart,
without changing routing code. Its deployment must be verified and configured.
Previous brains remain available as executors.

## Run locally

```bash
uv sync --extra dev
ROUTER_ENV=dev .venv/bin/uvicorn --app-dir src router_core.gateway.app:app --host 127.0.0.1 --port 8099
```

Development uses a deterministic stub and records that no frontier model authored
the decision. It makes no paid model calls. For configured provider deployments:

```bash
ROUTER_ENV=live .venv/bin/uvicorn --app-dir src router_core.gateway.app:app --host 127.0.0.1 --port 8099
```

The existing ignored `.env` supplies provider credentials; process environment
values take precedence. Production (`ROUTER_ENV=production`) requires
`ROUTER_GATEWAY_API_KEY`. No stub is available in production. Live automatic
routing fails with 503 when the brain is unavailable or its decision is invalid;
it does not execute a deterministic replacement.

```python
from openai import OpenAI

client = OpenAI(base_url="http://127.0.0.1:8099/v1", api_key="unused-in-dev")
response = client.chat.completions.create(
    model="auto",
    messages=[{"role": "user", "content": "Summarise this customer enquiry: ..."}],
    max_completion_tokens=256,
    extra_body={"router": {"explain": True}},
)
print(response.choices[0].message.content)
```

Text messages, tool-call messages, structured output and streaming are supported
where the selected adapter/model supports them. Tools are returned to the caller;
the gateway does not execute external actions. Images and unsupported wire fields
are rejected. An explicit registry model ID skips the routing consultation.

## Catalog and deployments

- `config/models.seed.yaml`: all **23 models** and the exact supplied September 8
  intelligence scores and benchmark task costs. This is a dated, user-supplied
  snapshot, not a live market feed. New or ambiguous access classifications remain
  unknown; inherited access/effort/fallback labels are provisional.
- `config/models.live.yaml`: existing verified deployment metadata, provider IDs,
  options and token rates. Different effort settings retain separate identities.
- `config/chart-provider-map.yaml`: endpoint hints, which do not enable a model.
- `config/router.yaml`: brain selection, consultation cost limit, providers and
  gateway authentication. There is no target open/closed execution share.

The Qwen3.8 **247B A95B** entry replaces the differently named older Qwen entry;
the old 2.4T endpoint is not assumed to be the same model. Nemotron 3 Ultra and
Mistral Medium 3.5 are included; K2 Horizon is outside the supplied roster.

A ranked catalog entry does not establish API access. The existing deployment
metadata covers the configured brain, a lower-effort closed executor and a
connectivity baseline. The wider open/local pool still requires provider and
configuration verification. This revamp has not performed a new live provider
smoke test or established workload savings.

## API and operations

| Endpoint | Purpose |
|---|---|
| `POST /v1/chat/completions` | One request, one brain decision, one execution |
| `GET /v1/catalog` | Ranked market snapshot, separate from deployments |
| `GET /v1/models` | Deployment metadata and selection blockers |
| `POST /v1/routing/simulate` | Free candidate preview; does not predict the brain's decision |
| `GET /v1/routing/stats` | Recorded routing, execution and total costs |
| `GET /health` | Configuration readiness, not an upstream connectivity test |
| `GET /dashboard` | Read-only operations view |
| `GET /docs` | Interactive API schema |

`router.explain` returns decision provenance and cost details on non-streaming
responses. Decisions for streaming responses remain in the ledger. Optional
`placement_allow` constrains **executor placement**; the routing brain still
receives the digest at its own configured provider. This option is not a data
residency guarantee. `max_cost_usd` filters projected routing-plus-execution spend;
estimates are not a guaranteed invoice cap. `task_class` can apply operator-supplied
measured capability floors from `config/quality_floors.yaml`; none are invented by
default. Model pinning obeys the same execution constraints.

The default consultation limit is $0.50 **per request**, including the configured
leader output allowance. It is not a lifetime allowance or a monthly account
budget. Execution uses the output limit used in candidate costing.

The SQLite ledger records routing and execution charges separately, including a
paid consultation whose decision is rejected before execution. Missing usage
remains unknown. Benchmark task costs are never converted into customer request
prices. Savings remain unset until measured against a quality-matched baseline.
Request content is retained in the ignored local ledger; credentials are excluded.

## Checks

```bash
.venv/bin/python -m pytest
.venv/bin/ruff check src tests scripts
.venv/bin/python scripts/lint_no_vendor.py
.venv/bin/python scripts/verify_registry.py
```

The registry audit intentionally fails for unverified catalog entries. Pytest uses
isolated provider transports and never spends on inference. It covers brain
self-selection, cheaper open execution, default routing, protocol compatibility,
failed-consult accounting, constraints, snapshot integrity and removed job routes.

The pre-pivot working copy, including pre-existing uncommitted work, is preserved
locally in `work/pre-pivot-2026-09-09.tar.gz`. It contains no `.env` or request ledger.
