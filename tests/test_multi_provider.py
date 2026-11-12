import httpx
import pytest

from router_core.providers.base import AdapterRegistry, ProviderError
from router_core.providers.chat_api import ChatAPIAdapter


def test_two_provider_adapters_route_distinct_model_ids():
    first = ChatAPIAdapter(
        "openai",
        {"model-a": "provider-a-model"},
        base_url="https://a.invalid/v1",
        api_key="secret-a",
        transport=httpx.MockTransport(lambda request: httpx.Response(200)),
    )
    second = ChatAPIAdapter(
        "together",
        {"model-b": "provider-b-model"},
        base_url="https://b.invalid/v1",
        api_key="secret-b",
        transport=httpx.MockTransport(lambda request: httpx.Response(200)),
    )
    registry = AdapterRegistry()
    registry.register(first)
    registry.register(second)
    assert registry.for_model("model-a") is first
    assert registry.for_model("model-b") is second


def test_duplicate_provider_coverage_fails_closed():
    one = ChatAPIAdapter(
        "one",
        {"same-model": "one"},
        base_url="https://one.invalid/v1",
        api_key="secret",
        transport=httpx.MockTransport(lambda request: httpx.Response(200)),
    )
    two = ChatAPIAdapter(
        "two",
        {"same-model": "two"},
        base_url="https://two.invalid/v1",
        api_key="secret",
        transport=httpx.MockTransport(lambda request: httpx.Response(200)),
    )
    registry = AdapterRegistry()
    registry.register(one)
    with pytest.raises(ProviderError, match="duplicate adapter coverage"):
        registry.register(two)
