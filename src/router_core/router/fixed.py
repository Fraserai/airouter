"""Versioned fixed-model selection, reproducible from archived inputs."""

from dataclasses import dataclass


@dataclass(frozen=True)
class FixedSelectionInputs:
    requested_model: str
    pin_model: str | None
    default_model: str | None


def select_fixed(inputs: FixedSelectionInputs) -> str:
    selected = inputs.pin_model or (
        inputs.requested_model if inputs.requested_model != "auto" else inputs.default_model
    )
    if not selected:
        raise ValueError("no default model configured and no model pin provided")
    return selected


DECISION_VERSION = "fixed-v1"
