#!/usr/bin/env python
"""Reproduce a recorded routing decision offline, without another paid request."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from router_core.ledger.replay import replay_request  # noqa: E402
from router_core.ledger.store import SQLiteLedger  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("request_id")
    parser.add_argument("--ledger", default="data/requests.sqlite3")
    parser.add_argument(
        "--include-request", action="store_true", help="include retained request text"
    )
    args = parser.parse_args()
    if not Path(args.ledger).is_file():
        parser.error("ledger does not exist")
    ledger = SQLiteLedger(args.ledger)
    try:
        result = replay_request(ledger, args.request_id)
        if not args.include_request:
            for field in ("request", "normalized_request", "provider_request"):
                result.pop(field, None)
        print(json.dumps(result, indent=2))
        return 0 if result["decision_matches"] else 1
    except ValueError as exc:
        print(f"Replay failed: {exc}")
        return 1
    finally:
        ledger.close()


if __name__ == "__main__":
    raise SystemExit(main())
