"""Small synthetic contract checks, never represented as enterprise traffic."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class WorkloadCase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1)
    task_class: Literal["structured_extraction", "reasoning_analysis", "conversational_simple"]
    prompt: str = Field(min_length=1, max_length=12000)
    expected: str
    synthetic: Literal[True]

    def request(self, model_id: str) -> dict:
        return {
            "model": model_id,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Answer the task accurately. Return a JSON object "
                        "with a single string field "
                        "named answer. Follow the task's requested answer format."
                    ),
                },
                {"role": "user", "content": self.prompt},
            ],
            "max_completion_tokens": 128,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "task_answer",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "properties": {"answer": {"type": "string"}},
                        "required": ["answer"],
                        "additionalProperties": False,
                    },
                },
            },
            "router": {"explain": True},
        }


def load_workload(path: str | Path) -> list[WorkloadCase]:
    cases = [
        WorkloadCase.model_validate_json(line)
        for line in Path(path).read_text().splitlines()
        if line.strip()
    ]
    if not cases or len(cases) > 100:
        raise ValueError("smoke workload must contain between 1 and 100 cases")
    if len({c.id for c in cases}) != len(cases):
        raise ValueError("workload IDs must be unique")
    return cases


def workload_hash(cases: list[WorkloadCase]) -> str:
    raw = json.dumps([c.model_dump() for c in cases], sort_keys=True, separators=(",", ":"))
    return "workload_" + hashlib.sha256(raw.encode()).hexdigest()[:16]


def grade(case: WorkloadCase, content: str | None, finish_reason: str, refusal: str | None) -> dict:
    if refusal:
        return {"passed": False, "reason": "refusal"}
    if finish_reason != "stop":
        return {"passed": False, "reason": "incomplete_output"}
    try:
        answer = json.loads(content or "")
    except (ValueError, TypeError):
        return {"passed": False, "reason": "invalid_json"}
    if (
        not isinstance(answer, dict)
        or set(answer) != {"answer"}
        or not isinstance(answer["answer"], str)
    ):
        return {"passed": False, "reason": "invalid_schema"}
    passed = answer["answer"].strip() == case.expected
    return {"passed": passed, "reason": "correct" if passed else "wrong_answer"}
