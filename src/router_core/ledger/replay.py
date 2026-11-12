"""Offline replay: reconstruct a saved request and reproduce its fixed decision."""

import json
from dataclasses import asdict

from router_core.gateway.openai_compat import ChatCompletionRequest
from router_core.ledger.store import LedgerStore
from router_core.router.fixed import DECISION_VERSION, FixedSelectionInputs, select_fixed
from router_core.router.protocol import DECISION_VERSION as RUNTIME_DECISION_VERSION


def replay_request(ledger: LedgerStore, request_id: str) -> dict:
    starts = [e["payload"] for e in ledger.events(request_id) if e["event"] == "started"]
    if len(starts) != 1:
        raise ValueError("request must have exactly one start event")
    row = starts[0]
    request = ChatCompletionRequest.model_validate(row["request"])
    version = row.get("decision_version")
    if version == DECISION_VERSION:
        selected = select_fixed(FixedSelectionInputs(**row["decision_inputs"]))
        source = "fixed_replay"
        recorded_decision = None
    elif version == RUNTIME_DECISION_VERSION:
        recorded_decision = row.get("routing_decision")
        if not isinstance(recorded_decision, dict):
            raise ValueError("runtime record has no recorded routing decision")
        selected = recorded_decision.get("model")
        candidates = recorded_decision.get("candidates") or []
        if not isinstance(selected, str) or selected not in candidates:
            raise ValueError("runtime record contains a disallowed selected model")
        source = "runtime_decision_snapshot"
    else:
        raise ValueError("this record predates reproducible decisions or uses another version")
    normalized = asdict(request.to_internal(selected))
    if version == DECISION_VERSION:
        request_matches = (
            request.model == row["decision_inputs"]["requested_model"]
            and request.router.pin_model == row["decision_inputs"]["pin_model"]
            and json.dumps(normalized, sort_keys=True)
            == json.dumps(row["normalized_request"], sort_keys=True)
        )
    else:
        request_matches = json.dumps(normalized, sort_keys=True) == json.dumps(
            row["normalized_request"], sort_keys=True
        )
    return {
        "request_id": request_id,
        "decision_version": version,
        "registry_version": row["registry_version"],
        "recorded_model": row["model"],
        "replayed_model": selected,
        "decision_matches": selected == row["model"] and request_matches,
        "request_matches": request_matches,
        "replay_source": source,
        "frontier_authored": False,
        "routing_decision": recorded_decision,
        "request": request.model_dump(mode="json", by_alias=True),
        "normalized_request": row["normalized_request"],
        "provider_request": row.get("provider_request"),
        "executed": False,
    }
