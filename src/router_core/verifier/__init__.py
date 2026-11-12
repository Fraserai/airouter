"""Deterministic response verification and escalation contracts."""

from router_core.verifier.execute import (
    AttemptRecord,
    ExecutionAttempt,
    ExecutionRun,
    execute_with_escalation,
)
from router_core.verifier.gates.core import (
    FailureClass,
    VerificationResult,
    VerificationStatus,
    verify_completion,
)
from router_core.verifier.gates.escalation import EscalationAction, next_escalation

__all__ = [
    "EscalationAction",
    "AttemptRecord",
    "ExecutionAttempt",
    "ExecutionRun",
    "FailureClass",
    "VerificationResult",
    "VerificationStatus",
    "next_escalation",
    "verify_completion",
    "execute_with_escalation",
]
