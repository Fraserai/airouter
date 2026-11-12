"""Bounded live comparisons through the gateway; all calls remain in its ledger."""

from __future__ import annotations

import json
import math
import statistics
import time
from collections import defaultdict
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import httpx

from router_core.config import AppConfig
from router_core.evaluation.workload import WorkloadCase, grade, workload_hash
from router_core.gateway.openai_compat import ChatCompletionResponse
from router_core.ledger.store import execution_cost
from router_core.providers.base import Usage


def wilson_interval(passed: int, count: int) -> list[float] | None:
    if not count:
        return None
    z = 1.959963984540054
    p = passed / count
    denominator = 1 + z * z / count
    center = (p + z * z / (2 * count)) / denominator
    margin = z * math.sqrt(p * (1 - p) / count + z * z / (4 * count * count)) / denominator
    return [max(0, center - margin), min(1, center + margin)]


def reservation_usd(entry, body: dict) -> float:
    """Conservative byte-based reservation, not an invoice guarantee."""
    token_allowance = len(json.dumps(body, ensure_ascii=False).encode()) + 1024
    pricing = entry.pricing
    if pricing is None or pricing.currency != "USD":
        raise ValueError("evaluation requires verified USD token prices")
    if pricing.max_priced_input_tokens and token_allowance > pricing.max_priced_input_tokens:
        raise ValueError("request exceeds the verified pricing range")
    rate = max(pricing.input_usd_per_mtok, pricing.cache_write_input_usd_per_mtok or 0)
    return (
        token_allowance * rate + body["max_completion_tokens"] * pricing.output_usd_per_mtok
    ) / 1e6


def summarize(rows: list[dict], models: list[str], planned_cases: int, baseline: str) -> dict:
    results = {}
    for model in models:
        subset = [r for r in rows if r["model"] == model]
        passed = sum(r["passed"] for r in subset)
        costs = [r["cost_usd"] for r in subset if r["cost_usd"] is not None]
        groups = defaultdict(list)
        for row in subset:
            groups[row["task_class"]].append(row)
        results[model] = {
            "attempted": len(subset),
            "planned": planned_cases,
            "passed": passed,
            "pass_rate": passed / len(subset) if subset else None,
            "pass_rate_wilson_95": wilson_interval(passed, len(subset)),
            "complete": len(subset) == planned_cases,
            "known_cost_usd": float(sum((Decimal(str(c)) for c in costs), Decimal(0))),
            "unknown_cost_requests": len(subset) - len(costs),
            "median_latency_ms": statistics.median(r["latency_ms"] for r in subset)
            if subset
            else None,
            "by_task_class": {
                name: {"attempted": len(group), "passed": sum(r["passed"] for r in group)}
                for name, group in groups.items()
            },
        }
    reference = results[baseline]
    comparisons = {}
    for model, result in results.items():
        eligible = (
            all(r["complete"] and r["unknown_cost_requests"] == 0 for r in (result, reference))
            and reference["known_cost_usd"] > 0
        )
        comparisons[model] = {
            "observed_cost_difference_pct": (
                100
                * (reference["known_cost_usd"] - result["known_cost_usd"])
                / reference["known_cost_usd"]
                if eligible
                else None
            ),
            "quality_noninferiority_proven": False,
            "routing_savings_proven": False,
        }
    return {"models": results, "comparisons_to_baseline": comparisons}


async def run_evaluation(
    config: AppConfig,
    client: httpx.AsyncClient,
    cases: list[WorkloadCase],
    models: list[str],
    *,
    baseline: str,
    max_spend_usd: float,
    output_dir: Path,
) -> dict:
    if not models or len(set(models)) != len(models) or baseline not in models:
        raise ValueError("models must be unique and include the baseline")
    if not cases or len({c.id for c in cases}) != len(cases):
        raise ValueError("workload must be nonempty with unique IDs")
    if not math.isfinite(max_spend_usd) or max_spend_usd <= 0:
        raise ValueError("max_spend_usd must be positive and finite")
    reserve = 0.0
    for model in models:
        entry = config.registry.get(model)
        if not entry.is_selectable or "json_schema" not in entry.api_features:
            raise ValueError(f"model lacks verified pricing or structured output: {model}")
        for case in cases:
            reserve += reservation_usd(entry, case.request(model))
    if reserve > max_spend_usd:
        raise ValueError("planned reservation exceeds spend budget; no requests sent")
    inventory = await client.get("models")
    inventory.raise_for_status()
    if inventory.json().get("registry_version") != config.registry.version:
        raise ValueError(
            "gateway registry differs from local config; restart or select matching config"
        )

    output_dir.mkdir(parents=True, exist_ok=False)
    rows: list[dict] = []
    spent = Decimal(0)
    stopped_reason = None
    metadata = {
        "schema_version": 1,
        "started_at": datetime.now(UTC).isoformat(),
        "workload_hash": workload_hash(cases),
        "synthetic": True,
        "provisional": True,
        "registry_version": config.registry.version,
        "baseline": baseline,
        "baseline_kind": "explicitly_selected_executor",
        "frontier_baseline_verified": False,
        "max_spend_usd": max_spend_usd,
        "reserved_estimate_usd": reserve,
        "budget_method": (
            "byte-based preflight reservation; stop on missing cost or budget exhaustion"
        ),
        "model_snapshots": {m: config.registry.get(m).model_dump(mode="json") for m in models},
        "limitations": [
            "Small authored synthetic smoke set, not representative enterprise traffic.",
            "No model judge, non-inferiority decision, or automatic policy promotion.",
            "Wilson intervals assume independent cases; related templates weaken that assumption.",
            "Cost differences are observed fixed-executor differences, not router savings.",
            "Timing is one sequential local run and is not a service latency guarantee.",
        ],
    }
    (output_dir / "manifest.json").write_text(json.dumps(metadata, indent=2) + "\n")
    with (output_dir / "results.jsonl").open("x") as output:
        for index, case in enumerate(cases):
            # Rotate model order to reduce consistently favouring the first model in time.
            order = models[index % len(models) :] + models[: index % len(models)]
            for model in order:
                entry = config.registry.get(model)
                body = case.request(model)
                if spent + Decimal(str(reservation_usd(entry, body))) > Decimal(str(max_spend_usd)):
                    stopped_reason = "budget_exhausted"
                    break
                started = time.perf_counter()
                row = {
                    "case_id": case.id,
                    "task_class": case.task_class,
                    "model": model,
                    "synthetic": True,
                    "provisional": True,
                    "cost_usd": None,
                    "passed": False,
                    "reason": "request_failed",
                    "request_id": None,
                }
                try:
                    response = await client.post("chat/completions", json=body)
                    response.raise_for_status()
                    parsed = ChatCompletionResponse.model_validate(response.json())
                    if parsed.model != model or len(parsed.choices) != 1:
                        raise ValueError("unexpected selected model or choice count")
                    row["request_id"] = parsed.id
                    reported = parsed.usage
                    usage = Usage(
                        reported.prompt_tokens,
                        reported.completion_tokens,
                        cached_input_tokens=reported.prompt_tokens_details.get("cached_tokens", 0),
                        estimated=reported.estimated,
                        reasoning_output_tokens=reported.completion_tokens_details.get(
                            "reasoning_tokens", 0
                        ),
                        cache_write_input_tokens=reported.prompt_tokens_details.get(
                            "cache_write_tokens", 0
                        ),
                    )
                    cost = execution_cost(entry, usage)
                    row["cost_usd"] = cost
                    row["usage"] = reported.model_dump()
                    choice = parsed.choices[0]
                    row["response"] = choice.message.model_dump(exclude_none=True)
                    row.update(
                        grade(
                            case,
                            choice.message.content,
                            choice.finish_reason,
                            choice.message.refusal,
                        )
                    )
                    if cost is not None:
                        spent += Decimal(str(cost))
                except (httpx.HTTPError, ValueError, KeyError, TypeError):
                    # Keep provider/gateway bodies and transport exception strings out of reports.
                    row["reason"] = "gateway_error_or_invalid_response"
                row["latency_ms"] = (time.perf_counter() - started) * 1000
                rows.append(row)
                output.write(json.dumps(row) + "\n")
                output.flush()
                if row["cost_usd"] is None:
                    stopped_reason = "unknown_request_cost"
                    break
            if stopped_reason:
                break
    report = {
        **metadata,
        "finished_at": datetime.now(UTC).isoformat(),
        "stopped_reason": stopped_reason,
        "complete": len(rows) == len(models) * len(cases),
        "known_total_cost_usd": float(spent),
        **summarize(rows, models, len(cases), baseline),
    }
    (output_dir / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    lines = [
        "# Provisional synthetic smoke evaluation",
        "",
        "This run tests execution and measurement. "
        "It does not establish enterprise quality or router savings.",
        "",
        f"Baseline: `{baseline}`. Workload: `{report['workload_hash']}`.",
        "",
        "| Model | Correct / attempted | Known cost (USD) | Median latency (ms) |",
        "|---|---:|---:|---:|",
    ]
    for model, result in report["models"].items():
        latency = result["median_latency_ms"]
        lines.append(
            f"| {model} | {result['passed']} / {result['attempted']} | "
            f"{result['known_cost_usd']:.8f} | "
            f"{round(latency) if latency is not None else 'unknown'} |"
        )
    lines += [
        "",
        f"Run complete: {report['complete']}. Stop reason: {stopped_reason or 'none'}.",
        "",
    ]
    lines += [f"- {limitation}" for limitation in metadata["limitations"]]
    (output_dir / "report.md").write_text("\n".join(lines) + "\n")
    return report
