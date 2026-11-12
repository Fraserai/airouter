"""Deterministic completion gates and escalation classification."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class VerificationStatus(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    UNKNOWN = "unknown"


class FailureClass(StrEnum):
    NONE = "none"
    UNDER_THINKING = "under_thinking"
    CAPABILITY_MISSING = "capability_missing"
    CONTEXT_OVERFLOW = "context_overflow"
    PROVIDER_ERROR = "provider_error"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class VerificationResult:
    status: VerificationStatus
    gates: dict[str, bool | None]
    reason: str
    failure_class: FailureClass

    @property
    def retryable(self) -> bool:
        return self.status == VerificationStatus.FAIL and self.failure_class != FailureClass.UNKNOWN


def _schema_valid(value: Any, schema: dict[str, Any]) -> bool:
    kind = schema.get("type")
    if kind == "object":
        if not isinstance(value, dict):
            return False
        properties = schema.get("properties") or {}
        required = schema.get("required") or []
        if any(name not in value for name in required):
            return False
        if schema.get("additionalProperties") is False and any(
            name not in properties for name in value
        ):
            return False
        return all(
            name not in value or _schema_valid(value[name], child)
            for name, child in properties.items()
        )
    if kind == "array":
        return isinstance(value, list) and all(
            _schema_valid(item, schema.get("items") or {}) for item in value
        )
    if kind == "string":
        return isinstance(value, str)
    if kind == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if kind == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if kind == "boolean":
        return isinstance(value, bool)
    if kind == "null":
        return value is None
    return True


def _tool_calls_valid(tool_calls: tuple[dict[str, Any], ...]) -> bool:
    ids: set[str] = set()
    for call in tool_calls:
        if not isinstance(call, dict):
            return False
        call_id = call.get("id")
        function = call.get("function")
        if not isinstance(call_id, str) or not call_id or call_id in ids:
            return False
        if not isinstance(function, dict) or not isinstance(function.get("name"), str):
            return False
        arguments = function.get("arguments", "")
        if not isinstance(arguments, str):
            return False
        try:
            json.loads(arguments)
        except (TypeError, ValueError):
            return False
        ids.add(call_id)
    return True


def verify_completion(
    *,
    content: str | None,
    finish_reason: str | None,
    task_class: str | None = None,
    response_schema: dict[str, Any] | None = None,
    tool_calls: tuple[dict[str, Any], ...] = (),
    refusal: str | None = None,
) -> VerificationResult:
    """Apply only gates that are deterministic from the response contract.

    A response without a declared schema or executable tool contract is
    ``unknown`` rather than falsely promoted to a quality pass. Model judges
    and human labels belong in a separate, blinded evaluation path.
    """
    if refusal:
        return VerificationResult(
            VerificationStatus.FAIL,
            {"no_refusal": False},
            "provider refused the request",
            FailureClass.CAPABILITY_MISSING,
        )
    if finish_reason not in {"stop", "tool_calls"}:
        return VerificationResult(
            VerificationStatus.FAIL,
            {"complete": False},
            "provider response was incomplete",
            FailureClass.UNDER_THINKING,
        )
    gates: dict[str, bool | None] = {"complete": True}
    if tool_calls:
        gates["tool_calls_well_formed"] = _tool_calls_valid(tool_calls)
        if not gates["tool_calls_well_formed"]:
            return VerificationResult(
                VerificationStatus.FAIL,
                gates,
                "tool call contract is malformed",
                FailureClass.CAPABILITY_MISSING,
            )
    if response_schema is not None:
        try:
            parsed = json.loads(content or "")
        except (TypeError, ValueError):
            return VerificationResult(
                VerificationStatus.FAIL,
                {**gates, "json_parses": False, "schema_valid": False},
                "response is not valid JSON",
                FailureClass.CAPABILITY_MISSING,
            )
        schema_ok = _schema_valid(parsed, response_schema)
        gates.update({"json_parses": True, "schema_valid": schema_ok})
        if not schema_ok:
            return VerificationResult(
                VerificationStatus.FAIL,
                gates,
                "response does not satisfy the requested schema",
                FailureClass.CAPABILITY_MISSING,
            )
        return VerificationResult(
            VerificationStatus.PASS, gates, "declared gates passed", FailureClass.NONE
        )
    if (
        task_class in {"conversational_simple", "structured_extraction"}
        and not (content or "").strip()
    ):
        return VerificationResult(
            VerificationStatus.FAIL,
            {**gates, "non_empty": False},
            "response content is empty",
            FailureClass.CAPABILITY_MISSING,
        )
    return VerificationResult(
        VerificationStatus.UNKNOWN,
        {**gates, "quality_judgement": None},
        "no deterministic quality contract was declared",
        FailureClass.UNKNOWN,
    )
