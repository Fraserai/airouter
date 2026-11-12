"""Append-only request events. Missing usage is unknown spend, never free work."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Protocol

from router_core.providers.base import Usage
from router_core.registry.schema import ModelEntry


def _known_charge(value: object) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    amount = Decimal(str(value))
    return amount if amount.is_finite() and amount >= 0 else None


def _routing_charge(started: dict, terminal: dict) -> tuple[Decimal, bool, bool]:
    """One charge per request, including routing completed before execution.

    Attempt records also recover charges on historical rejected-plan events
    whose top-level routing cost was omitted. Never add a terminal copy of the
    same decision to its started event.
    """
    decision = terminal.get("routing_decision") or started.get("routing_decision") or {}
    runtime = bool(decision) or started.get("decision") == "runtime"
    attempts = decision.get("attempts")
    if attempts:
        charges = [
            _known_charge(a.get("cost_usd")) if a.get("cost_known") is True else None
            for a in attempts
        ]
        return (
            sum((cost for cost in charges if cost is not None), Decimal(0)),
            all(cost is not None for cost in charges),
            True,
        )
    for payload in (terminal, started, decision):
        cost = _known_charge(payload.get("routing_cost_usd"))
        if cost is not None:
            known = payload.get("routing_cost_known", decision.get("routing_cost_known", True))
            return (cost if known else Decimal(0), bool(known), runtime)
    # No attempt means no charge only for an explicitly recorded fallback, or
    # a legacy fixed-model request that never invoked routing intelligence.
    no_consult = attempts == [] and decision.get("decision_source") == "deterministic_fallback"
    return Decimal(0), bool(no_consult or not runtime), runtime


def execution_cost(entry: ModelEntry, usage: Usage | None) -> float | None:
    if usage is None or usage.estimated or entry.pricing is None:
        return None
    counts = (
        usage.input_tokens,
        usage.output_tokens,
        usage.cached_input_tokens,
        usage.cache_write_input_tokens,
        usage.reasoning_output_tokens,
    )
    if any(type(n) is not int or n < 0 for n in counts):
        return None
    if (
        usage.cached_input_tokens + usage.cache_write_input_tokens > usage.input_tokens
        or usage.reasoning_output_tokens > usage.output_tokens
    ):
        return None
    p = entry.pricing
    if p.currency != "USD":
        return None
    if p.max_priced_input_tokens is not None and usage.input_tokens > p.max_priced_input_tokens:
        return None
    cached_rate = p.cached_input_usd_per_mtok
    write_rate = p.cache_write_input_usd_per_mtok
    if usage.cached_input_tokens and cached_rate is None:
        return None
    if usage.cache_write_input_tokens and write_rate is None:
        return None
    total = (
        Decimal(usage.input_tokens - usage.cached_input_tokens - usage.cache_write_input_tokens)
        * Decimal(str(p.input_usd_per_mtok))
        + Decimal(usage.cached_input_tokens) * Decimal(str(cached_rate or 0))
        + Decimal(usage.cache_write_input_tokens) * Decimal(str(write_rate or 0))
        + Decimal(usage.output_tokens) * Decimal(str(p.output_usd_per_mtok))
    )
    return float(total / Decimal(1_000_000))


def projected_cost(entry: ModelEntry, input_tokens: int, output_tokens: int) -> float | None:
    """Return a conservative no-cache upper bound for a dry-run estimate."""
    if type(input_tokens) is not int or type(output_tokens) is not int:
        return None
    if input_tokens < 0 or output_tokens < 0 or entry.pricing is None:
        return None
    pricing = entry.pricing
    if pricing.currency != "USD":
        return None
    if (
        pricing.max_priced_input_tokens is not None
        and input_tokens > pricing.max_priced_input_tokens
    ):
        return None
    total = Decimal(input_tokens) * Decimal(str(pricing.input_usd_per_mtok)) + Decimal(
        output_tokens
    ) * Decimal(str(pricing.output_usd_per_mtok))
    return float(total / Decimal(1_000_000))


class LedgerStore(Protocol):
    def append(self, request_id: str, event: str, payload: dict) -> None: ...
    def events(self, request_id: str) -> list[dict]: ...
    def stats(self) -> dict: ...
    def routing_spend_usd(self) -> float: ...
    def close(self) -> None: ...


class SQLiteLedger:
    def __init__(self, path: str):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("""CREATE TABLE IF NOT EXISTS request_events (
            sequence INTEGER PRIMARY KEY AUTOINCREMENT,
            request_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            event TEXT NOT NULL,
            payload TEXT NOT NULL
        )""")
        self.db.execute("CREATE INDEX IF NOT EXISTS event_request ON request_events(request_id)")
        self.db.commit()

    def append(self, request_id: str, event: str, payload: dict) -> None:
        with self.db:
            self.db.execute(
                "INSERT INTO request_events(request_id,created_at,event,payload) VALUES (?,?,?,?)",
                (request_id, datetime.now(UTC).isoformat(), event, json.dumps(payload)),
            )

    def events(self, request_id: str) -> list[dict]:
        return [
            {"event": event, "created_at": created, "payload": json.loads(payload)}
            for event, created, payload in self.db.execute(
                "SELECT event,created_at,payload FROM request_events "
                "WHERE request_id=? ORDER BY sequence",
                (request_id,),
            )
        ]

    def stats(self) -> dict:
        requests = self._requests()
        started = sum("started" in events for events in requests.values())
        terminals = [events for events in requests.values() if "terminal" in events]
        execution_charges = [
            _known_charge(events["terminal"].get("execution_cost_usd")) for events in terminals
        ]
        unknown = sum(cost is None for cost in execution_charges)
        routing_charges = [
            _routing_charge(events.get("started", {}), events.get("terminal", {}))
            for events in requests.values()
        ]
        routing_unknown = sum(not complete for _, complete, _ in routing_charges)
        known_execution = sum((c for c in execution_charges if c is not None), Decimal(0))
        known_routing = sum((cost for cost, _, _ in routing_charges), Decimal(0))
        unfinished = sum("terminal" not in events for events in requests.values())
        complete = (
            unknown == 0 and routing_unknown == 0 and unfinished == 0 and started == len(requests)
        )
        mix = self._execution_mix(requests)
        return {
            "requests": started,
            "completed": sum(e.get("terminal_event") == "completed" for e in terminals),
            "failed": sum(e.get("terminal_event") == "failed" for e in terminals),
            "cancelled": sum(e.get("terminal_event") == "cancelled" for e in terminals),
            "unfinished": unfinished,
            "known_execution_cost_usd": float(known_execution),
            "known_routing_cost_usd": float(known_routing),
            "known_total_cost_usd": float(known_execution + known_routing),
            "total_cost_usd": float(known_execution + known_routing) if complete else None,
            "unknown_cost_requests": unknown,
            "unknown_routing_cost_requests": routing_unknown,
            "routing_spend_complete": routing_unknown == 0,
            "spend_complete": complete,
            "cost_basis": "provider tokens at configured standard rates; not invoice reconciled",
            "savings_usd": None,
            "routing_implemented": True,
            "runtime_routed_requests": sum(runtime for _, _, runtime in routing_charges),
            "execution_mix": mix,
        }

    def _requests(self) -> dict[str, dict]:
        requests: dict[str, dict] = {}
        for request_id, event, payload in self.db.execute(
            "SELECT request_id,event,payload FROM request_events ORDER BY sequence"
        ):
            if event not in {"started", "completed", "failed", "cancelled"}:
                continue
            record = requests.setdefault(request_id, {})
            if event == "started":
                record["started"] = json.loads(payload)
            else:
                record["terminal"] = json.loads(payload)
                record["terminal_event"] = event
        return requests

    @staticmethod
    def _execution_mix(requests: dict[str, dict]) -> dict:
        """Execution request shares; leader consultations never enter this mix."""
        total = sum(
            "started" in events and events["started"].get("execution_started", True)
            for events in requests.values()
        )
        result = {"basis": "started execution requests; excludes routing consultations"}
        for field, labels in (
            ("access", ("open", "closed", "unknown")),
            ("placement", ("local", "cloud_open", "closed_frontier", "unknown")),
        ):
            buckets = {
                label: {
                    "requests": 0,
                    "known_execution_cost_usd": Decimal(0),
                    "unknown_execution_cost_requests": 0,
                }
                for label in labels
            }
            for events in requests.values():
                if "started" not in events or not events["started"].get("execution_started", True):
                    continue
                snapshot = events["started"].get("model_snapshot") or {}
                label = snapshot.get(field, "unknown")
                bucket = buckets[label if label in buckets else "unknown"]
                bucket["requests"] += 1
                cost = _known_charge(events.get("terminal", {}).get("execution_cost_usd"))
                if cost is None:
                    bucket["unknown_execution_cost_requests"] += 1
                else:
                    bucket["known_execution_cost_usd"] += cost
            for bucket in buckets.values():
                bucket["known_execution_cost_usd"] = float(bucket["known_execution_cost_usd"])
                bucket["share"] = bucket["requests"] / total if total else None
            result[f"by_{field}"] = buckets
        result["requests"] = total
        return result

    def routing_spend_usd(self) -> float:
        """Known runtime-leader spend in the current ledger window.

        Unknown routing charges are deliberately excluded from this number;
        callers must keep their accounting incomplete rather than treating an
        unpriced consult as free.
        """
        return float(
            sum(
                (
                    _routing_charge(events.get("started", {}), events.get("terminal", {}))[0]
                    for events in self._requests().values()
                ),
                Decimal(0),
            )
        )

    def close(self) -> None:
        self.db.close()
