"""Gateway application.

M0 scope: config + registry load, /health, /v1/models, and a FIXED-MODEL
completions path proven end to end. No routing yet -- the router is M2.
"""

from __future__ import annotations

import json
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse

from router_core import __version__
from router_core.config import AppConfig, load_config, selectable_summary
from router_core.gateway.openai_compat import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    WireChoice,
    WireMessage,
    WireUsage,
    stream_chunk,
)
from router_core.providers.base import AdapterRegistry, ProviderError
from router_core.providers.stub import StubAdapter


def build_adapters(config: AppConfig) -> AdapterRegistry:
    """Adapters are discovered from the registry, never named in code."""
    adapters = AdapterRegistry()
    if not config.is_production:
        stub_ids = tuple(e.id for e in config.registry.all() if e.provider == "stub")
        if stub_ids:
            adapters.register(StubAdapter(stub_ids))
    return adapters


@asynccontextmanager
async def lifespan(app: FastAPI):
    config = load_config()
    app.state.config = config
    app.state.adapters = build_adapters(config)
    app.state.started_at = time.time()
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="Intelligent AI API Router",
        version=__version__,
        lifespan=lifespan,
    )

    @app.get("/health")
    async def health() -> dict[str, Any]:
        config: AppConfig = app.state.config
        adapter_health = {}
        for adapter in app.state.adapters.adapters():
            ok, detail = await adapter.health()
            adapter_health[adapter.name] = {"ok": ok, "detail": detail}
        return {
            "status": "ok",
            "version": __version__,
            "env": config.env,
            "uptime_s": round(time.time() - app.state.started_at, 3),
            "registry": selectable_summary(config.registry),
            "adapters": adapter_health,
            "intelligence_model": config.intelligence_model,
            "milestone": "M0",
        }

    @app.get("/v1/models")
    async def list_models() -> dict[str, Any]:
        """The live registry, including WHY an entry is not selectable.

        Operators will not trust the router until they can see this, and the
        day-one answer is 'almost nothing is selectable', which is correct.
        """
        config: AppConfig = app.state.config
        data = []
        for entry in sorted(config.registry.all(), key=lambda e: e.id):
            reasons = entry.selectable_reasons()
            data.append(
                {
                    "id": entry.id,
                    "object": "model",
                    "owned_by": entry.lab,
                    "display_name": entry.display_name,
                    # The routable unit is (family, effort), not model.
                    "family": entry.family,
                    "effort": entry.effort,
                    "effort_rank": entry.effort_rank,
                    "placement": entry.placement.value,
                    "access": entry.access.value,
                    "lifecycle": entry.lifecycle.value,
                    "verified": entry.verified,
                    "selectable": not reasons,
                    "blocked_by": reasons,
                    "composite_score": entry.scores.composite,
                    # Benchmark economics. Display only -- never a price and
                    # never read by selection. See tests/test_selection_guards.py
                    "benchmark_cost_per_task_usd": entry.benchmark.cost_per_task_usd,
                    "cost_status": entry.benchmark.cost_status.value,
                    "has_subscores": entry.scores.has_subscores,
                    "context_window": entry.context_window,
                }
            )
        return {
            "object": "list",
            "registry_version": config.registry.version,
            "data": data,
        }

    @app.post("/v1/chat/completions")
    async def chat_completions(body: ChatCompletionRequest, request: Request):
        config: AppConfig = app.state.config
        adapters: AdapterRegistry = app.state.adapters

        # M0: no routing. A fixed, CONFIGURED model, proven end to end.
        model_id = body.router.pin_model or (config.router.get("m0") or {}).get("fixed_model")
        if not model_id:
            raise HTTPException(500, "no m0.fixed_model configured and no pin_model given")

        if model_id not in config.registry:
            raise HTTPException(404, f"unknown model id: {model_id}")
        entry = config.registry.get(model_id)
        if not entry.is_selectable:
            # Never silently serve from an unverified model.
            raise HTTPException(
                409,
                {
                    "error": "model_not_selectable",
                    "model": model_id,
                    "blocked_by": entry.selectable_reasons(),
                    "hint": "run scripts/verify_registry.py and record verified pricing",
                },
            )

        internal = body.to_internal(model_id)
        try:
            adapter = adapters.for_model(model_id)
        except ProviderError as exc:
            raise HTTPException(503, str(exc)) from exc

        if body.stream:
            completion_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"

            async def event_stream():
                try:
                    async for chunk in adapter.stream(internal):
                        payload = stream_chunk(
                            completion_id, model_id, chunk.delta, chunk.finish_reason
                        )
                        yield f"data: {json.dumps(payload)}\n\n"
                except ProviderError as exc:
                    yield f"data: {json.dumps({'error': str(exc)})}\n\n"
                yield "data: [DONE]\n\n"

            return StreamingResponse(event_stream(), media_type="text/event-stream")

        started = time.perf_counter()
        try:
            result = await adapter.complete(internal)
        except ProviderError as exc:
            raise HTTPException(502, str(exc)) from exc
        elapsed_ms = (time.perf_counter() - started) * 1000.0

        response = ChatCompletionResponse(
            model=model_id,
            choices=[
                WireChoice(
                    message=WireMessage(role="assistant", content=result.content),
                    finish_reason=result.finish_reason,
                )
            ],
            usage=WireUsage.from_usage(result.usage),
        )

        if body.router.explain:
            # M0 stub of the RoutingPlan. Becomes the real plan at M2.
            response.routing = {
                "milestone": "M0",
                "deciding_tier": None,
                "reason": "fixed model; routing not implemented until M2",
                "model": model_id,
                "placement": entry.placement.value,
                "registry_version": config.registry.version,
                "policy_version": (config.router.get("router") or {}).get("policy_version"),
                "latency_ms": round(elapsed_ms, 3),
                "usage_estimated": result.usage.estimated,
                "provisional": True,
            }
        return response

    return app


app = create_app()
