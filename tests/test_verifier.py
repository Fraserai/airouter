from router_core.verifier import (
    EscalationAction,
    FailureClass,
    VerificationStatus,
    next_escalation,
    verify_completion,
)


def test_structured_response_passes_deterministic_gate():
    result = verify_completion(
        content='{"answer":"ok"}',
        finish_reason="stop",
        response_schema={
            "type": "object",
            "properties": {"answer": {"type": "string"}},
            "required": ["answer"],
            "additionalProperties": False,
        },
    )
    assert result.status == VerificationStatus.PASS
    assert result.gates["schema_valid"] is True


def test_malformed_structured_response_requests_family_escalation():
    result = verify_completion(
        content='{"answer":4}',
        finish_reason="stop",
        response_schema={"type": "object", "properties": {"answer": {"type": "string"}}},
    )
    assert result.status == VerificationStatus.FAIL
    assert result.failure_class == FailureClass.CAPABILITY_MISSING
    assert next_escalation(result.failure_class, 0) == EscalationAction.FAMILY_UP


def test_unknown_open_ended_quality_is_not_called_a_pass():
    result = verify_completion(content="a thoughtful answer", finish_reason="stop")
    assert result.status == VerificationStatus.UNKNOWN
    assert result.failure_class == FailureClass.UNKNOWN


def test_incomplete_response_escalates_effort_before_family():
    result = verify_completion(content="partial", finish_reason="length")
    assert result.failure_class == FailureClass.UNDER_THINKING
    assert next_escalation(result.failure_class, 0) == EscalationAction.EFFORT_UP
    assert next_escalation(result.failure_class, 1) == EscalationAction.FAMILY_UP
    assert next_escalation(result.failure_class, 2) == EscalationAction.NONE


def test_malformed_tool_call_is_a_capability_failure():
    result = verify_completion(
        content=None,
        finish_reason="tool_calls",
        tool_calls=({"id": "call_1", "function": {"name": "lookup", "arguments": "not-json"}},),
    )
    assert result.status == VerificationStatus.FAIL
    assert result.failure_class == FailureClass.CAPABILITY_MISSING
