"""Construct provider adapters from deployment configuration."""

import os

from router_core.config import AppConfig
from router_core.providers.base import AdapterRegistry
from router_core.providers.chat_api import ChatAPIAdapter
from router_core.providers.stub import StubAdapter


def build_adapters(config: AppConfig) -> AdapterRegistry:
    adapters = AdapterRegistry()
    if not config.is_production:
        stub_ids = tuple(e.id for e in config.registry.all() if e.provider == "stub")
        if stub_ids:
            adapters.register(StubAdapter(stub_ids))
    for name, settings in (config.router.get("providers") or {}).items():
        models = {
            e.id: e.provider_model_id
            for e in config.registry.all()
            if e.provider == name
            and e.provider_model_id
            and (e.is_selectable or settings.get("include_unverified", False))
        }
        if not models:
            continue
        if settings["adapter"] != "chat_api":
            raise ValueError(f"unsupported adapter type for {name}")
        adapters.register(
            ChatAPIAdapter(
                name,
                models,
                base_url=settings["base_url"],
                api_key=os.environ.get(settings.get("api_key_env", "")),
                timeout_s=settings.get("timeout_s", 60),
                default_max_tokens=settings.get("default_max_tokens", 1024),
                auth_required=settings.get("auth_required", True),
                token_limit_parameter=settings.get(
                    "token_limit_parameter", "max_completion_tokens"
                ),
                request_defaults=settings.get("request_defaults"),
                model_parameters={
                    e.id: e.provider_options for e in config.registry.all() if e.id in models
                },
            )
        )
    return adapters
