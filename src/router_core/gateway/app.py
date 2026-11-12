# ruff: noqa: E501

"""Gateway application.

One API routes automatic requests through the frontier brain and shared pool.
Development simulation and explicit model selection retain honest provenance.
"""

from __future__ import annotations

import asyncio
import hmac
import json
import os
import time
import uuid
from contextlib import aclosing, asynccontextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse

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
from router_core.ledger.store import SQLiteLedger, execution_cost, projected_cost
from router_core.providers.base import (
    AdapterRegistry,
    ChatMessage,
    ProviderError,
)
from router_core.providers.factory import build_adapters
from router_core.registry.schema import Health, HealthState
from router_core.registry.store import Registry
from router_core.router.candidates import RequestProfile, evaluate_entry
from router_core.router.digest import DigestLimits, approx_tokens
from router_core.router.fixed import DECISION_VERSION, FixedSelectionInputs, select_fixed
from router_core.router.leader import ProviderLeader
from router_core.router.protocol import RoutingError
from router_core.router.runtime import RuntimeRouter, RuntimeRoutingConfig
from router_core.verifier import verify_completion


def routing_mode(body: ChatCompletionRequest, config: AppConfig) -> bool:
    automatic = body.model == "auto" and not body.router.pin_model
    enabled = body.router.runtime
    if enabled is None:
        enabled = bool((config.router.get("runtime_routing") or {}).get("enabled", True))
    if automatic and not enabled and config.env != "dev":
        raise HTTPException(
            422, "automatic requests require intelligent routing; select a model explicitly"
        )
    return bool(automatic and enabled)


def request_profile(body: ChatCompletionRequest, config: AppConfig) -> RequestProfile:
    required = set()
    if body.tools or any(m.tool_calls or m.role == "tool" for m in body.messages):
        required.add("tools")
    if body.response_format and body.response_format.type != "text":
        required.add(body.response_format.type)
    # Include tool definitions, arguments and schemas in the input estimate.
    rendered = body.model_dump_json(include={"messages", "tools", "response_format"})
    return RequestProfile(
        input_tokens=approx_tokens(rendered),
        max_output_tokens=body.max_completion_tokens
        or body.max_tokens
        or int((config.router.get("runtime_routing") or {}).get("default_max_tokens", 1024)),
        required_features=frozenset(required),
        task_class=body.router.task_class,
        placement_allow=(
            frozenset(body.router.placement_allow)
            if body.router.placement_allow is not None
            else None
        ),
        max_cost_usd=body.router.max_cost_usd,
    )


def validate_explicit_model(entry, profile: RequestProfile, config: AppConfig) -> None:
    classes = config.quality_floors.get("task_classes") or {}
    floor = (classes.get(profile.task_class) or {}).get("capability") or {}
    _, reasons = evaluate_entry(entry, profile, floor)
    if reasons:
        raise HTTPException(422, {"error": "model_constraints_not_met", "blocked_by": reasons})


@asynccontextmanager
async def lifespan(app: FastAPI):
    load_dotenv(".env", override=False)
    config = load_config()
    app.state.config = config
    app.state.adapters = build_adapters(config)
    runtime_cfg = config.router.get("runtime_routing") or {}
    leader = None
    leader_id = config.intelligence_model
    if leader_id and leader_id in config.registry:
        leader_entry = config.registry.get(leader_id)
        if leader_entry.is_selectable:
            try:
                adapter = app.state.adapters.for_model(leader_id)
                if not getattr(adapter, "configured", True):
                    raise ProviderError("routing provider is not configured")
            except ProviderError:
                pass
            else:
                leader = ProviderLeader(
                    leader_entry,
                    app.state.adapters,
                    rank=0,
                    max_output_tokens=int(runtime_cfg.get("leader_max_output_tokens", 256)),
                )
    # The brain remains in the execution pool. Stub work is development-only.
    pool = []
    for entry in config.registry.all():
        if entry.provider == "stub" and config.env != "dev":
            continue
        try:
            adapter = app.state.adapters.for_model(entry.id)
            configured = getattr(adapter, "configured", True)
        except ProviderError:
            configured = False
        if not configured:
            entry = entry.model_copy(
                update={"health": Health(state=HealthState.DOWN, detail="provider not configured")}
            )
        pool.append(entry)
    executor_registry = Registry(pool, config.catalog.source)
    app.state.runtime_router = RuntimeRouter(
        executor_registry,
        leader=leader,
        quality_floors=config.quality_floors,
        catalog=config.catalog,
        config=RuntimeRoutingConfig(
            digest_limits=DigestLimits(
                max_tokens=int(runtime_cfg.get("max_digest_tokens", 2000)),
                head_chars=int(runtime_cfg.get("digest_head_chars", 3200)),
                tail_chars=int(runtime_cfg.get("digest_tail_chars", 3200)),
            ),
            spend_budget_usd=float(runtime_cfg.get("max_consult_cost_usd", 0.50)),
            require_leader=config.env != "dev",
            placement_preference=tuple(runtime_cfg.get("placement_preference", [])),
        ),
    )
    app.state.started_at = time.time()
    ledger_path = os.environ.get(
        "ROUTER_LEDGER_PATH",
        (config.router.get("ledger") or {}).get("path", "data/requests.sqlite3"),
    )
    app.state.ledger = SQLiteLedger(ledger_path)
    try:
        yield
    finally:
        for adapter in app.state.adapters.adapters():
            close = getattr(adapter, "aclose", None)
            if close:
                await close()
        app.state.ledger.close()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Model Router",
        version=__version__,
        lifespan=lifespan,
    )

    def require_gateway_auth(request: Request, config: AppConfig) -> None:
        """Protect paid and operator routes without ever echoing the secret."""
        auth_cfg = config.router.get("auth") or {}
        enabled = config.is_production or bool(auth_cfg.get("enabled", False))
        if not enabled:
            return
        expected = os.environ.get(auth_cfg.get("api_key_env", "ROUTER_GATEWAY_API_KEY"))
        if not expected:
            raise HTTPException(503, "gateway authentication is not configured")
        supplied = request.headers.get("authorization", "")
        scheme, separator, token = supplied.partition(" ")
        if (
            not separator
            or scheme.lower() != "bearer"
            or not token
            or not hmac.compare_digest(token, expected)
        ):
            raise HTTPException(
                401,
                "gateway authentication required",
                headers={"WWW-Authenticate": "Bearer"},
            )

    @app.get("/health")
    async def health() -> dict[str, Any]:
        config: AppConfig = app.state.config
        adapter_health = {}
        for adapter in app.state.adapters.adapters():
            ok, detail = await adapter.health()
            settings = (config.router.get("providers") or {}).get(adapter.name) or {}
            adapter_health[adapter.name] = {
                "ok": ok,
                "detail": detail,
                "optional": bool(settings.get("optional", False)),
            }
        required_health = [h for h in adapter_health.values() if not h["optional"]]
        return {
            "status": "ok"
            if all(h["ok"] for h in required_health)
            and (config.env == "dev" or app.state.runtime_router.leader is not None)
            else "degraded",
            "version": __version__,
            "env": config.env,
            "uptime_s": round(time.time() - app.state.started_at, 3),
            "registry": selectable_summary(config.registry),
            "adapters": adapter_health,
            "intelligence_model": config.intelligence_model,
            "runtime_routing": {
                "enabled": bool((config.router.get("runtime_routing") or {}).get("enabled", False)),
                "leader_configured": app.state.runtime_router.leader is not None,
                "leader_model": (
                    app.state.runtime_router.leader.model_id
                    if app.state.runtime_router.leader is not None
                    else None
                ),
                "leader_in_execution_pool": (
                    config.intelligence_model in app.state.runtime_router.registry
                ),
                "mode": "development_simulation" if config.env == "dev" else "intelligent",
            },
            "product": "Model Router",
            "live_gateway": config.env != "dev",
            "health_check": "configuration readiness; use smoke test for upstream connectivity",
        }

    @app.get("/", response_class=HTMLResponse)
    async def product() -> HTMLResponse:
        """Branded product entry point; API consumers use /v1/chat/completions."""
        return HTMLResponse(
            """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="theme-color" content="#22b9d4">
  <title>Model Router — More intelligence. Less cost.</title>
  <style>
    :root { color-scheme: dark; font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
    * { box-sizing: border-box; }
    html, body { min-height: 100%; margin: 0; }
    body { color: #fff; background: #16bad5 url('/brand/model-router-gradient-logo.png') center / cover fixed no-repeat; }
    body::before { content: ""; position: fixed; inset: 0; pointer-events: none; background: rgba(6, 18, 40, .13); }
    a { color: inherit; }
    .shell { position: relative; min-height: 100vh; display: flex; flex-direction: column; padding: 26px clamp(22px, 5vw, 76px) 34px; }
    .nav { display: flex; align-items: center; justify-content: space-between; gap: 24px; }
    .brand-logo { display: block; width: min(190px, 24vw); height: auto; filter: drop-shadow(0 2px 12px rgba(0,0,0,.12)); }
    .nav-links { display: flex; align-items: center; gap: clamp(14px, 3vw, 34px); font-size: .9rem; }
    .nav-links a { text-decoration: none; opacity: .88; }
    .nav-links a:hover, .nav-links a:focus-visible { opacity: 1; text-decoration: underline; text-underline-offset: 5px; }
    .nav-cta, .hero-cta { display: inline-flex; align-items: center; gap: 9px; background: #07142a; color: #fff; border-radius: 999px; padding: 12px 17px; font-weight: 640; text-decoration: none; box-shadow: 0 10px 28px rgba(3, 17, 40, .2); }
    .nav-cta:hover, .hero-cta:hover, .nav-cta:focus-visible, .hero-cta:focus-visible { background: #10274c; transform: translateY(-1px); }
    .hero { width: min(690px, 100%); margin: clamp(90px, 18vh, 190px) 0 auto; padding: 30px 34px 32px; background: rgba(5, 18, 40, .38); border: 1px solid rgba(255,255,255,.23); border-radius: 28px; box-shadow: 0 20px 60px rgba(2, 13, 30, .16); backdrop-filter: blur(12px); }
    .eyebrow { margin: 0 0 17px; font-size: .74rem; font-weight: 760; letter-spacing: .19em; text-transform: uppercase; opacity: .8; }
    h1 { max-width: 630px; margin: 0; font-size: clamp(3.6rem, 9vw, 7.5rem); line-height: .88; letter-spacing: -.085em; font-weight: 640; text-wrap: balance; text-shadow: 0 4px 28px rgba(0,0,0,.16); }
    .lede { max-width: 510px; margin: 30px 0 0; font-size: clamp(1.06rem, 1.8vw, 1.28rem); line-height: 1.47; color: rgba(255,255,255,.9); text-wrap: pretty; }
    .actions { display: flex; flex-wrap: wrap; align-items: center; gap: 18px; margin-top: 32px; }
    .text-link { font-weight: 620; text-underline-offset: 5px; text-decoration-thickness: 1px; }
    .footer { display: flex; align-items: end; justify-content: space-between; gap: 20px; margin-top: clamp(90px, 15vh, 180px); font-size: .8rem; color: rgba(255,255,255,.78); }
    .footer p { margin: 0; }
    .footer-links { display: flex; gap: 18px; }
    .footer-links a { text-decoration: none; }
    .footer-links a:hover { text-decoration: underline; text-underline-offset: 4px; }
    @media (max-width: 650px) {
      .shell { padding: 20px 20px 26px; }
      .nav-links a:not(.nav-cta) { display: none; }
      .hero { margin-top: 98px; padding: 25px 22px 26px; border-radius: 22px; }
      h1 { font-size: clamp(3.4rem, 16vw, 5.2rem); }
      .footer { align-items: start; flex-direction: column; margin-top: 100px; }
    }
  </style>
</head>
<body>
  <main class="shell">
    <nav class="nav" aria-label="Primary">
      <a href="/" aria-label="Model Router home"><img class="brand-logo" src="/brand/model-router-logo.png" alt="Model Router"></a>
      <div class="nav-links">
        <a href="/v1/catalog">Model pool</a>
        <a href="/docs">Docs</a>
        <a class="nav-cta" href="/docs#/default/chat_completions_v1_chat_completions_post">Get started <span aria-hidden="true">→</span></a>
      </div>
    </nav>
    <section class="hero" aria-labelledby="hero-title">
      <p class="eyebrow">One API for your model stack.</p>
      <h1 id="hero-title">More intelligence.<br>Less cost.</h1>
      <p class="lede">Send a request once. Model Router picks the right model for the work — balancing capability, latency, and cost across your pool.</p>
      <div class="actions">
        <a class="hero-cta" href="/docs#/default/chat_completions_v1_chat_completions_post">Start with the API <span aria-hidden="true">→</span></a>
        <a class="text-link" href="/v1/catalog">Explore the model pool <span aria-hidden="true">↗</span></a>
      </div>
    </section>
    <footer class="footer">
      <p>Model Router · One API for the model market.</p>
      <div class="footer-links"><a href="/dashboard">Operations</a><a href="/docs">API docs</a><a href="/health">Health</a></div>
    </footer>
  </main>
</body>
</html>"""
        )

    @app.get("/brand/model-router-gradient-logo.png")
    async def brand_asset() -> FileResponse:
        return FileResponse(
            Path(__file__).with_name("assets") / "model-router-gradient-logo.png",
            media_type="image/png",
        )

    @app.get("/brand/model-router-logo.png")
    async def logo_asset() -> FileResponse:
        return FileResponse(
            Path(__file__).with_name("assets") / "model-router-logo.png",
            media_type="image/png",
        )

    @app.get("/v1/catalog")
    async def catalog(request: Request) -> dict[str, Any]:
        config: AppConfig = app.state.config
        require_gateway_auth(request, config)
        ranks: dict[float, int] = {}
        data = []
        for position, entry in enumerate(config.catalog.ranked(), 1):
            score = entry.scores.composite
            rank = ranks.setdefault(score, position) if score is not None else None
            deployments = [
                model.id
                for model in config.registry.all()
                if model.family == entry.family and model.is_selectable
            ]
            data.append(
                {
                    "id": entry.id,
                    "name": entry.display_name,
                    "rank": rank,
                    "intelligence_index": score,
                    "benchmark_cost_per_task_usd": entry.benchmark.cost_per_task_usd,
                    "access": entry.access.value,
                    "access_verified": False,
                    "deployment_ids": deployments,
                    "routing_brain": entry.id == config.intelligence_model,
                }
            )
        return {
            "object": "list",
            "source": config.catalog.source,
            "catalog_version": config.catalog.version,
            "cost_basis": "benchmark task cost; not an API request price",
            "data": data,
        }

    @app.get("/v1/routing/stats")
    async def routing_stats(request: Request) -> dict[str, Any]:
        require_gateway_auth(request, app.state.config)
        return app.state.ledger.stats()

    @app.post("/v1/routing/simulate")
    async def simulate_routing(body: ChatCompletionRequest, request: Request) -> dict[str, Any]:
        """Explain a routing choice without consulting or executing a model."""
        config: AppConfig = app.state.config
        require_gateway_auth(request, config)
        if body.stream:
            raise HTTPException(422, "simulation does not support streaming requests")
        runtime_enabled = routing_mode(body, config)
        profile = request_profile(body, config)
        required_features = profile.required_features
        if runtime_enabled:
            try:
                decision = await app.state.runtime_router.route(
                    [ChatMessage(role=m.role, content=m.content) for m in body.messages],
                    profile,
                    tool_names=[t.function.name for t in body.tools or []],
                    response_format=body.response_format.type if body.response_format else None,
                    routing_spend_usd=0.0,
                    consult_leader=False,
                )
            except RoutingError as exc:
                raise HTTPException(422, {"error": exc.code, **exc.detail}) from exc
            model_id = decision.model_id
        else:
            fixed_key = "fixed_model"
            try:
                model_id = select_fixed(
                    FixedSelectionInputs(
                        requested_model=body.model,
                        pin_model=body.router.pin_model,
                        default_model=(config.router.get("development") or {}).get(fixed_key)
                        if config.env == "dev"
                        else None,
                    )
                )
            except ValueError as exc:
                raise HTTPException(500, str(exc)) from exc
            decision = None
        if model_id not in config.registry:
            raise HTTPException(404, f"unknown model id: {model_id}")
        entry = config.registry.get(model_id)
        if not entry.is_selectable:
            raise HTTPException(
                409,
                {
                    "error": "model_not_selectable",
                    "model": model_id,
                    "blocked_by": entry.selectable_reasons(),
                },
            )
        missing = required_features - set(entry.api_features)
        if missing:
            raise HTTPException(
                422, {"error": "unsupported_model_features", "features": sorted(missing)}
            )
        if not runtime_enabled:
            validate_explicit_model(entry, profile, config)
        return {
            "simulated": True,
            "executes": False,
            "selection_mode": "candidate_preview" if runtime_enabled else "explicit",
            "predicts_live_selection": False,
            "model": model_id,
            "placement": entry.placement.value,
            "input_tokens_estimate": profile.input_tokens,
            "max_output_tokens": profile.max_output_tokens,
            "projected_execution_cost_usd": projected_cost(
                entry, profile.input_tokens, profile.max_output_tokens
            ),
            "routing": decision.to_payload() if decision else None,
            "registry_version": config.registry.version,
        }

    @app.get("/dashboard", response_class=HTMLResponse)
    async def dashboard(request: Request) -> HTMLResponse:
        """Small read-only operator view; all values come from live state."""
        config: AppConfig = app.state.config
        require_gateway_auth(request, config)
        stats = app.state.ledger.stats()
        models = [
            {
                "id": entry.id,
                "placement": entry.placement.value,
                "selectable": entry.is_selectable,
                "blocked_by": entry.selectable_reasons(),
            }
            for entry in sorted(config.registry.all(), key=lambda item: item.id)
        ]
        runtime = app.state.runtime_router
        data = {
            "environment": config.env,
            "registry_version": config.registry.version,
            "intelligence_model": config.intelligence_model,
            "runtime_enabled": bool(
                (config.router.get("runtime_routing") or {}).get("enabled", False)
            ),
            "leader_configured": runtime.leader is not None,
            "leader_model": runtime.leader.model_id if runtime.leader is not None else None,
            "stats": stats,
            "models": models,
        }
        payload = json.dumps(data, sort_keys=True).replace("<", "\\u003c")
        selectable = sum(model["selectable"] for model in models)
        return HTMLResponse(
            "<!doctype html>"
            '<html lang="en"><head>'
            "<title>Model Router — Operations</title>"
            "<style>body{font:16px system-ui;margin:2rem;max-width:72rem}"
            ".cards{display:flex;gap:1rem;flex-wrap:wrap}.card{border:1px solid #ddd;"
            "border-radius:8px;padding:1rem;min-width:12rem}.muted{color:#666}"
            "table{border-collapse:collapse;width:100%;margin-top:1rem}"
            "td,th{border-bottom:1px solid #ddd;padding:.45rem;text-align:left}"
            ".ok{color:#176b35}.blocked{color:#8a3b12}</style></head><body>"
            "<h1>Model Router</h1>"
            '<p class="muted">Read-only operator view. Routing and savings remain provisional.</p>'
            '<div class="cards">'
            f'<div class="card"><strong>Environment</strong><br>{config.env}</div>'
            f'<div class="card"><strong>Selectable models</strong><br>'
            f"{selectable} / {len(models)}</div>"
            f'<div class="card"><strong>Requests</strong><br>{stats["requests"]}</div>'
            f'<div class="card"><strong>Known execution spend</strong><br>'
            f"${stats['known_execution_cost_usd']:.8f}</div>"
            '<div class="card"><strong>Runtime leader</strong><br>'
            f"{runtime.leader.model_id if runtime.leader else 'not configured'}</div>"
            "</div><h2>Model pool</h2><table><thead><tr><th>Model</th><th>Placement</th>"
            "<th>Status</th><th>Reason</th></tr></thead><tbody>"
            + "".join(
                f"<tr><td>{model['id']}</td><td>{model['placement']}</td>"
                f'<td class="{"ok" if model["selectable"] else "blocked"}">'
                f"{'selectable' if model['selectable'] else 'blocked'}</td>"
                f"<td>{', '.join(model['blocked_by']) or 'ready'}</td></tr>"
                for model in models
            )
            + "</tbody></table>"
            f'<script type="application/json" id="router-data">{payload}</script>'
            "</body></html>"
        )

    @app.get("/v1/models")
    async def list_models(request: Request) -> dict[str, Any]:
        """The live registry, including WHY an entry is not selectable.

        Operators will not trust the router until they can see this, and the
        day-one answer is 'almost nothing is selectable', which is correct.
        """
        config: AppConfig = app.state.config
        require_gateway_auth(request, config)
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
                    "api_features": entry.api_features,
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
        require_gateway_auth(request, config)

        runtime_enabled = routing_mode(body, config)
        profile = request_profile(body, config)
        if body.max_tokens is None and body.max_completion_tokens is None:
            body = body.model_copy(update={"max_completion_tokens": profile.max_output_tokens})
        required_features = profile.required_features
        completion_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"
        decision = None
        selection_inputs = None
        if runtime_enabled:
            try:
                decision = await app.state.runtime_router.route(
                    [
                        # The runtime router only needs role/content for its
                        # bounded digest; tool details are passed separately.
                        ChatMessage(role=m.role, content=m.content)
                        for m in body.messages
                    ],
                    profile,
                    tool_names=[t.function.name for t in body.tools or []],
                    response_format=body.response_format.type if body.response_format else None,
                    routing_spend_usd=0.0,
                )
            except RoutingError as exc:
                failed_decision = exc.detail.get("routing_decision")
                app.state.ledger.append(
                    completion_id,
                    "started",
                    {
                        "request": body.model_dump(mode="json"),
                        "decision": "runtime",
                        "execution_started": False,
                        "routing_decision": failed_decision,
                        "registry_version": config.registry.version,
                    },
                )
                app.state.ledger.append(
                    completion_id,
                    "failed",
                    {
                        "error": exc.code,
                        "execution_cost_usd": 0.0,
                        "routing_cost_usd": (failed_decision or {}).get("routing_cost_usd", 0.0),
                        "routing_decision": failed_decision,
                    },
                )
                status = 503 if exc.code == "routing_intelligence_unavailable" else 422
                raise HTTPException(
                    status,
                    {"error": exc.code, **exc.detail},
                    headers={"x-request-id": completion_id},
                ) from exc
            model_id = decision.model_id
        else:
            fixed_key = "fixed_model"
            selection_inputs = FixedSelectionInputs(
                requested_model=body.model,
                pin_model=body.router.pin_model,
                default_model=(config.router.get("development") or {}).get(fixed_key)
                if config.env == "dev"
                else None,
            )
            try:
                model_id = select_fixed(selection_inputs)
            except ValueError as exc:
                raise HTTPException(500, str(exc)) from exc

        if model_id not in config.registry:
            raise HTTPException(404, f"unknown model id: {model_id}")
        entry = config.registry.get(model_id)
        if missing := required_features - set(entry.api_features):
            raise HTTPException(
                422, {"error": "unsupported_model_features", "features": sorted(missing)}
            )
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

        if not runtime_enabled:
            validate_explicit_model(entry, profile, config)
        internal = body.to_internal(model_id)
        try:
            adapter = adapters.for_model(model_id)
        except ProviderError as exc:
            raise HTTPException(503, str(exc)) from exc

        ledger = app.state.ledger
        started = time.perf_counter()
        ledger.append(
            completion_id,
            "started",
            {
                "request": body.model_dump(mode="json"),
                "model": model_id,
                "model_snapshot": entry.model_dump(mode="json"),
                "registry_version": config.registry.version,
                "decision": "runtime" if decision else "fixed_model",
                "decision_version": decision.decision_version if decision else DECISION_VERSION,
                "decision_inputs": asdict(selection_inputs) if selection_inputs else None,
                "routing_decision": decision.to_payload() if decision else None,
                "routing_cost_usd": decision.routing_cost_usd if decision else None,
                "normalized_request": asdict(internal),
                "provider_request": (
                    adapter.snapshot_request(internal)
                    if hasattr(adapter, "snapshot_request")
                    else None
                ),
            },
        )

        def record(event, usage=None, **details):
            ledger.append(
                completion_id,
                event,
                {
                    "model": model_id,
                    "usage": asdict(usage) if usage is not None else None,
                    "execution_cost_usd": execution_cost(entry, usage),
                    "routing_cost_usd": decision.routing_cost_usd if decision else None,
                    "latency_ms": (time.perf_counter() - started) * 1000,
                    **details,
                },
            )

        if body.stream:
            created = int(time.time())

            async def event_stream():
                usage = None
                finish_reason = None
                terminal = False
                include_usage = body.stream_options and body.stream_options.include_usage
                try:
                    async with aclosing(adapter.stream(internal)) as upstream:
                        async for chunk in upstream:
                            if chunk.usage is not None:
                                usage = chunk.usage
                            if chunk.finish_reason is not None:
                                finish_reason = chunk.finish_reason
                            if (
                                chunk.delta
                                or chunk.message_delta
                                or chunk.finish_reason is not None
                            ):
                                payload = stream_chunk(
                                    completion_id,
                                    model_id,
                                    chunk.delta,
                                    chunk.finish_reason,
                                    message_delta=chunk.message_delta,
                                    created=created,
                                )
                                if include_usage:
                                    payload["usage"] = None
                                yield f"data: {json.dumps(payload)}\n\n"
                    record("completed", usage, finish_reason=finish_reason)
                    terminal = True
                    if include_usage and usage is not None:
                        payload = stream_chunk(completion_id, model_id, "", None, created=created)
                        payload["choices"] = []
                        payload["usage"] = WireUsage.from_usage(usage).model_dump()
                        yield f"data: {json.dumps(payload)}\n\n"
                except ProviderError as exc:
                    record("failed", usage, error=str(exc))
                    terminal = True
                    error = {"error": {"message": str(exc), "type": "provider_error"}}
                    yield f"data: {json.dumps(error)}\n\n"
                finally:
                    if not terminal:
                        record("cancelled", usage)
                yield "data: [DONE]\n\n"

            return StreamingResponse(
                event_stream(),
                media_type="text/event-stream",
                headers={"x-request-id": completion_id, "Cache-Control": "no-cache"},
            )

        try:
            result = await adapter.complete(internal)
        except ProviderError as exc:
            record("failed", error=str(exc))
            status = exc.status if exc.status in {422, 429, 503} else 502
            raise HTTPException(status, str(exc), headers={"x-request-id": completion_id}) from exc
        except asyncio.CancelledError:
            record("cancelled")
            raise
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        response_schema = None
        if body.response_format and body.response_format.type == "json_schema":
            response_schema = body.response_format.json_schema.schema_
        verification = verify_completion(
            content=result.content,
            finish_reason=result.finish_reason,
            task_class=body.router.task_class,
            response_schema=response_schema,
            tool_calls=result.tool_calls,
            refusal=result.refusal,
        )
        record(
            "completed",
            result.usage,
            finish_reason=result.finish_reason,
            provider_fingerprint=result.provider_fingerprint,
            verification_status=verification.status.value,
            verification_reason=verification.reason,
            failure_class=verification.failure_class.value,
            verification_gates=verification.gates,
        )

        response = ChatCompletionResponse(
            id=completion_id,
            model=model_id,
            choices=[
                WireChoice(
                    message=WireMessage(
                        role="assistant",
                        content=result.content
                        or (None if result.tool_calls or result.refusal else ""),
                        tool_calls=list(result.tool_calls) or None,
                        refusal=result.refusal,
                    ),
                    finish_reason=result.finish_reason,
                )
            ],
            usage=WireUsage.from_usage(result.usage),
        )

        if body.router.explain:
            if decision is not None:
                response.routing = {
                    "selection_mode": "intelligent",
                    **decision.to_payload(),
                    "placement": entry.placement.value,
                    "registry_version": config.registry.version,
                    "latency_ms": round(elapsed_ms, 3),
                    "usage_estimated": result.usage.estimated,
                    "execution_cost_usd": execution_cost(entry, result.usage),
                    "total_cost_usd": (
                        decision.routing_cost_usd + execution_cost(entry, result.usage)
                        if decision.routing_cost_usd is not None
                        and execution_cost(entry, result.usage) is not None
                        else None
                    ),
                    "provisional": True,
                }
            else:
                response.routing = {
                    "product": "Model Router",
                    "selection_mode": "explicit",
                    "reason": "explicit model selection or development baseline",
                    "model": model_id,
                    "placement": entry.placement.value,
                    "registry_version": config.registry.version,
                    "latency_ms": round(elapsed_ms, 3),
                    "usage_estimated": result.usage.estimated,
                    "execution_cost_usd": execution_cost(entry, result.usage),
                    "provisional": True,
                }
            response.routing["verification"] = {
                "status": verification.status.value,
                "reason": verification.reason,
                "failure_class": verification.failure_class.value,
                "gates": verification.gates,
            }
        return response

    return app


app = create_app()
