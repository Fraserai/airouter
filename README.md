# Intelligent AI API Router

An OpenAI-compatible gateway that routes each inference request to the cheapest
model that clears a quality floor, across local, cloud-hosted open, and closed
frontier placements.

The frontier model is the **author of the routing policy**, not the executor of
every routing decision. See `BRIEF.md` §2 and `PLAN.md`.

## Status

**M0 — skeleton.** Config-driven registry, `/v1/models`, `/health`, and a fixed
model proven end to end through an unmodified OpenAI SDK. No routing yet.

On a fresh checkout **no seed model is selectable**. All 22 entries are
`verified: false` with `pricing: null`, so `scripts/verify_registry.py` fails,
loudly and by design (`BRIEF.md` §3 rule 2). A deterministic stub adapter carries
the dev path so nothing depends on inventing a price.

## Run it

```bash
uv venv --python 3.12 && uv pip install -e ".[dev]"
.venv/bin/uvicorn --app-dir src router_core.gateway.app:app --port 8099
```

```bash
curl -s localhost:8099/health | python -m json.tool
```

Drop-in check with the real SDK:

```python
from openai import OpenAI

client = OpenAI(base_url="http://127.0.0.1:8099/v1", api_key="unused")
print(
    client.chat.completions.create(model="auto", messages=[{"role": "user", "content": "hi"}])
    .choices[0]
    .message.content
)
```

## Checks

```bash
.venv/bin/python -m pytest
.venv/bin/python scripts/lint_no_vendor.py    # no vendor/model/price in routing logic
.venv/bin/python scripts/verify_registry.py   # expected to FAIL on a fresh checkout
```

## Documents

| File | What it is |
|---|---|
| `BRIEF.md` | The spec (v2). Section 1 is fixed. |
| `docs/BRIEF.v1.md` | The original brief, kept for the record. |
| `PLAN.md` | Interpretation, stack, layout, answers to the open questions. |
| `FINDINGS.md` | Judgement calls, ambiguities, and every provisional number's origin. |
