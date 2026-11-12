"""Read public deployment metadata; never enable a model or send inference."""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import yaml


def build_report(seed, mapping, catalog, leader):
    entries = {entry["id"]: entry for entry in catalog["data"]}
    seed_ids = {entry["id"] for entry in seed["models"]}
    if set(mapping["models"]) != seed_ids:
        raise ValueError("mapping must cover exactly the chart roster")
    rows = []
    for model in seed["models"]:
        endpoint = mapping["models"][model["id"]]
        observed = entries.get(endpoint)
        rows.append({
            "model": model["id"],
            "role": "router" if model["id"] == leader else "executor",
            "endpoint": endpoint,
            "catalog_present": observed is not None,
            "live_verified": False,
            "access_verified": False,
            "chart_configuration_verified": False,
            "deployment": "hosted" if observed else None,
            "context_length": observed.get("context_length") if observed else None,
            "pricing_per_token": observed.get("pricing") if observed else None,
            "reasoning": observed.get("reasoning") if observed else None,
            "supported_parameters": observed.get("supported_parameters") if observed else None,
        })
    return {"retrieved_at": datetime.now(UTC).isoformat(),
            "source": mapping["catalog_url"], "models": rows,
            "catalog_matches": sum(row["catalog_present"] for row in rows),
            "inference_calls": 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("config"))
    args = parser.parse_args()
    seed = yaml.safe_load((args.config / "models.seed.yaml").read_text())
    mapping = yaml.safe_load((args.config / "chart-provider-map.yaml").read_text())
    router = yaml.safe_load((args.config / "router.yaml").read_text())
    response = httpx.get(mapping["catalog_url"], timeout=30)
    response.raise_for_status()
    print(json.dumps(build_report(seed, mapping, response.json(),
                                  router["router"]["intelligence_model"]), indent=2))


if __name__ == "__main__":
    main()
