"""Regression checks for accounting and honest evaluation conclusions."""

import httpx
import pytest

from router_core.config import load_config
from router_core.evaluation.runner import run_evaluation, summarize, wilson_interval
from router_core.evaluation.workload import WorkloadCase, grade
from router_core.ledger.store import execution_cost, projected_cost
from router_core.providers.base import ProviderError, Usage
from router_core.providers.chat_api import parse_usage

MODEL = "gpt-4-1-mini@api:default"


@pytest.mark.parametrize("value", [0, 800])
def test_flat_and_nested_cache_usage_agree(value):
    base = {"prompt_tokens": 1000, "completion_tokens": 100}
    flat = parse_usage({**base, "cached_tokens": value})
    nested = parse_usage({**base, "prompt_tokens_details": {"cached_tokens": value}})
    assert flat == nested
    assert flat.cached_input_tokens == value


def test_conflicting_cache_counts_fail_including_explicit_zero():
    with pytest.raises(ProviderError):
        parse_usage(
            {
                "prompt_tokens": 1000,
                "completion_tokens": 100,
                "cached_tokens": 800,
                "prompt_tokens_details": {"cached_tokens": 0},
            }
        )


@pytest.mark.parametrize(
    "usage",
    [
        Usage(-1, 2),
        Usage(1, -2),
        Usage(1, 2, 3),
        Usage(1, 2, reasoning_output_tokens=3),
        Usage(1, 2, cache_write_input_tokens=-1),
    ],
)
def test_invalid_usage_is_never_a_known_cost(config_dir, usage):
    entry = load_config(config_dir, env="live").registry.get(MODEL)
    assert execution_cost(entry, usage) is None


def test_missing_cache_tariff_is_unknown(config_dir):
    entry = load_config(config_dir, env="live").registry.get(MODEL).model_copy(deep=True)
    entry.pricing.cached_input_usd_per_mtok = None
    usage = parse_usage({"prompt_tokens": 1000, "completion_tokens": 100, "cached_tokens": 800})
    assert execution_cost(entry, usage) is None


def test_projected_cost_is_a_no_cache_upper_bound(config_dir):
    entry = load_config(config_dir, env="live").registry.get(MODEL)
    assert projected_cost(entry, 1000, 100) == pytest.approx(0.00056)
    limited = load_config(config_dir, env="live").registry.get("gpt-5-6-luna@api:none")
    assert projected_cost(limited, 1_100_000, 100) is None


def test_grading_separates_schema_and_correctness():
    case = WorkloadCase(
        id="one", task_class="reasoning_analysis", prompt="1+1?", expected="2", synthetic=True
    )
    assert grade(case, '{"answer":"2"}', "stop", None)["passed"]
    assert grade(case, '{"answer":2}', "stop", None)["reason"] == "invalid_schema"
    assert grade(case, '{"answer":"3"}', "stop", None)["reason"] == "wrong_answer"
    assert grade(case, '{"answer":"2"}', "length", None)["reason"] == "incomplete_output"
    assert wilson_interval(0, 0) is None
    assert wilson_interval(12, 12)[0] < 0.8


def test_incomplete_comparison_cannot_claim_savings():
    row = {
        "model": "baseline",
        "passed": True,
        "cost_usd": 0.01,
        "task_class": "reasoning_analysis",
        "latency_ms": 10,
    }
    report = summarize([row], ["baseline", "candidate"], 1, "baseline")
    comparison = report["comparisons_to_baseline"]["candidate"]
    assert comparison["observed_cost_difference_pct"] is None
    assert not comparison["routing_savings_proven"]


@pytest.mark.anyio
async def test_budget_preflight_prevents_all_network_calls(config_dir, tmp_path):
    def handler(request):
        pytest.fail("budget preflight must precede network calls")

    case = WorkloadCase(
        id="one", task_class="reasoning_analysis", prompt="1+1?", expected="2", synthetic=True
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://gateway/v1/"
    ) as client:
        with pytest.raises(ValueError, match="reservation exceeds"):
            await run_evaluation(
                load_config(config_dir, env="live"),
                client,
                [case],
                [MODEL],
                baseline=MODEL,
                max_spend_usd=1e-12,
                output_dir=tmp_path / "run",
            )
    assert not (tmp_path / "run").exists()
