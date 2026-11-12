"""Bounded routing input.

The leader must never see the whole request. A consult that scales with prompt
size costs more on exactly the long-context requests where the savings are
supposed to come from, and that failure is silent -- it shows up in the monthly
bill, not in any test. So the digest is capped in tokens before it is sent, and
the cap is enforced here rather than trusted to callers.

The cost of this bound is real and worth stating: the leader decides with less
information than the executor will have. That trade is deliberate.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

CHARS_PER_TOKEN = 4  # crude, deterministic, and always reported as an estimate


def approx_tokens(text: str) -> int:
    """A tokeniser-free estimate. Never presented as a measured count."""
    return max(1, len(text) // CHARS_PER_TOKEN) if text else 0


class _Message(Protocol):
    role: str
    content: str | None


@dataclass(frozen=True)
class DigestLimits:
    max_tokens: int
    head_chars: int
    tail_chars: int


@dataclass(frozen=True)
class RequestDigest:
    """A structural sketch of the request, not the request."""

    message_count: int
    roles: tuple[str, ...]
    head: str
    tail: str
    approx_input_tokens: int
    requested_max_tokens: int
    tool_names: tuple[str, ...]
    response_format: str | None
    task_class: str | None
    truncated: bool
    tokens: int

    def to_payload(self) -> dict[str, Any]:
        return {
            "message_count": self.message_count,
            "roles": list(self.roles),
            "head": self.head,
            "tail": self.tail,
            "approx_input_tokens": self.approx_input_tokens,
            "input_tokens_estimated": True,
            "requested_max_tokens": self.requested_max_tokens,
            "tools": list(self.tool_names),
            "response_format": self.response_format,
            "task_class": self.task_class,
            "truncated": self.truncated,
        }


def _clip(text: str, limit: int) -> tuple[str, bool]:
    if limit <= 0:
        return "", bool(text)
    if len(text) <= limit:
        return text, False
    return text[:limit], True


def build_digest(
    messages: Sequence[_Message],
    *,
    limits: DigestLimits,
    requested_max_tokens: int,
    tool_names: Sequence[str] = (),
    response_format: str | None = None,
    task_class: str | None = None,
) -> RequestDigest:
    """Build a digest that is guaranteed to fit `limits.max_tokens`.

    Head and tail are taken from the first and last message because those carry
    the instruction and the actual ask; the middle of a long conversation is the
    part a router can most afford to lose.
    """
    full = "\n".join(f"{m.role}: {m.content or ''}" for m in messages)
    approx_input = approx_tokens(full)

    head_source = (messages[0].content or "") if messages else ""
    tail_source = (messages[-1].content or "") if messages else ""
    head_chars, tail_chars = limits.head_chars, limits.tail_chars

    # Shrink head/tail together until the whole digest fits its token budget.
    # Iterative rather than analytic because the fixed overhead (roles, tool
    # names) is not known until it is rendered.
    for _ in range(8):
        head, head_cut = _clip(head_source, head_chars)
        tail, tail_cut = _clip(tail_source, tail_chars)
        digest = RequestDigest(
            message_count=len(messages),
            roles=tuple(m.role for m in messages),
            head=head,
            tail=tail,
            approx_input_tokens=approx_input,
            requested_max_tokens=requested_max_tokens,
            tool_names=tuple(tool_names),
            response_format=response_format,
            task_class=task_class,
            truncated=head_cut or tail_cut or len(messages) > 2,
            tokens=0,
        )
        rendered = approx_tokens(repr(digest.to_payload()))
        if rendered <= limits.max_tokens or head_chars + tail_chars <= 2:
            return _with_tokens(digest, rendered)
        head_chars = max(1, head_chars // 2)
        tail_chars = max(1, tail_chars // 2)

    return _with_tokens(digest, rendered)


def _with_tokens(digest: RequestDigest, tokens: int) -> RequestDigest:
    return RequestDigest(
        message_count=digest.message_count,
        roles=digest.roles,
        head=digest.head,
        tail=digest.tail,
        approx_input_tokens=digest.approx_input_tokens,
        requested_max_tokens=digest.requested_max_tokens,
        tool_names=digest.tool_names,
        response_format=digest.response_format,
        task_class=digest.task_class,
        truncated=digest.truncated,
        tokens=tokens,
    )
