#!/usr/bin/env python
"""Run bounded, paid synthetic checks through a running gateway."""

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from router_core.config import load_config  # noqa: E402
from router_core.evaluation.runner import run_evaluation  # noqa: E402
from router_core.evaluation.workload import load_workload  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", nargs="+", required=True, help="explicit registry IDs")
    parser.add_argument("--baseline", required=True, help="registry ID included in --models")
    parser.add_argument("--workload", default="evals/workloads/smoke.jsonl")
    parser.add_argument("--base-url", default="http://127.0.0.1:8099/v1/")
    parser.add_argument("--env", default="live", choices=["live", "production"])
    parser.add_argument("--max-spend-usd", type=float, default=0.05)
    parser.add_argument("--output", default=None)
    args = parser.parse_args()
    path = Path(args.output or ("data/evals/" + datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")))

    async def execute():
        async with httpx.AsyncClient(
            base_url=args.base_url.rstrip("/") + "/", timeout=60
        ) as client:
            return await run_evaluation(
                load_config(env=args.env),
                client,
                load_workload(args.workload),
                args.models,
                baseline=args.baseline,
                max_spend_usd=args.max_spend_usd,
                output_dir=path,
            )

    try:
        result = asyncio.run(execute())
    except (ValueError, OSError, httpx.HTTPError) as exc:
        print(
            f"Evaluation did not complete ({type(exc).__name__}); "
            "check config, budget, and gateway."
        )
        return 1
    print(
        json.dumps(
            {
                "provisional": True,
                "synthetic": True,
                "complete": result["complete"],
                "known_total_cost_usd": result["known_total_cost_usd"],
                "models": result["models"],
                "report": str((path / "report.md").resolve()),
            },
            indent=2,
        )
    )
    return 0 if result["complete"] and result["stopped_reason"] is None else 1


if __name__ == "__main__":
    raise SystemExit(main())
