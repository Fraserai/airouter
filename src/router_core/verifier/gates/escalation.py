"""Failure-class-driven escalation choices."""

from __future__ import annotations

from enum import StrEnum

from router_core.verifier.gates.core import FailureClass


class EscalationAction(StrEnum):
    NONE = "none"
    RETRY_SAME = "retry_same"
    EFFORT_UP = "effort_up"
    FAMILY_UP = "family_up"


DEFAULT_LADDER: dict[FailureClass, tuple[EscalationAction, ...]] = {
    FailureClass.UNDER_THINKING: (EscalationAction.EFFORT_UP, EscalationAction.FAMILY_UP),
    FailureClass.CAPABILITY_MISSING: (EscalationAction.FAMILY_UP,),
    FailureClass.CONTEXT_OVERFLOW: (EscalationAction.FAMILY_UP,),
    FailureClass.PROVIDER_ERROR: (EscalationAction.RETRY_SAME, EscalationAction.FAMILY_UP),
    FailureClass.UNKNOWN: (EscalationAction.EFFORT_UP, EscalationAction.FAMILY_UP),
    FailureClass.NONE: (),
}


def next_escalation(
    failure_class: FailureClass,
    attempts: int,
    *,
    max_escalations: int = 2,
    ladder: dict[FailureClass, tuple[EscalationAction, ...]] | None = None,
) -> EscalationAction:
    if attempts < 0 or max_escalations < 0:
        raise ValueError("attempts and max_escalations must be non-negative")
    if attempts >= max_escalations:
        return EscalationAction.NONE
    options = (ladder or DEFAULT_LADDER).get(failure_class, ())
    return options[attempts] if attempts < len(options) else EscalationAction.NONE
