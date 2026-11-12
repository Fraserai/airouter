"""Validated text and function-call messages shared by the wire and provider layers."""

from __future__ import annotations

from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class FunctionCall(StrictModel):
    name: str = Field(min_length=1)
    arguments: str


class ToolCall(StrictModel):
    id: str = Field(min_length=1)
    type: Literal["function"] = "function"
    function: FunctionCall


class Message(StrictModel):
    role: Literal["system", "user", "assistant", "tool", "developer"]
    content: str | None = None
    name: str | None = None
    tool_calls: list[ToolCall] | None = Field(default=None, min_length=1)
    tool_call_id: str | None = None
    refusal: str | None = None

    @model_validator(mode="after")
    def validate_role_fields(self) -> Self:
        if self.role == "tool":
            if not self.tool_call_id or self.content is None:
                raise ValueError("tool messages require tool_call_id and content")
        elif self.tool_call_id is not None:
            raise ValueError("tool_call_id is only valid on tool messages")
        if self.role != "assistant" and (self.tool_calls is not None or self.refusal is not None):
            raise ValueError("tool_calls and refusal are only valid on assistant messages")
        if self.role != "assistant" and self.content is None:
            raise ValueError("content is required for this role")
        return self


class FunctionDefinition(StrictModel):
    name: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    description: str | None = None
    parameters: dict[str, Any] | None = None
    strict: bool | None = None


class FunctionTool(StrictModel):
    type: Literal["function"] = "function"
    function: FunctionDefinition


class FunctionName(StrictModel):
    name: str = Field(min_length=1)


class NamedToolChoice(StrictModel):
    type: Literal["function"] = "function"
    function: FunctionName


class JSONSchemaDefinition(StrictModel):
    name: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    description: str | None = None
    schema_: dict[str, Any] = Field(alias="schema")
    strict: bool | None = None


class ResponseFormat(StrictModel):
    type: Literal["text", "json_object", "json_schema"]
    json_schema: JSONSchemaDefinition | None = None

    @model_validator(mode="after")
    def validate_schema(self) -> Self:
        if (self.type == "json_schema") != (self.json_schema is not None):
            raise ValueError("json_schema is required only with type=json_schema")
        return self


class StreamFunctionDelta(StrictModel):
    name: str | None = None
    arguments: str | None = None


class StreamToolDelta(StrictModel):
    index: int = Field(ge=0)
    id: str | None = None
    type: Literal["function"] | None = None
    function: StreamFunctionDelta | None = None


class MessageDelta(StrictModel):
    role: Literal["assistant"] | None = None
    content: str | None = None
    refusal: str | None = None
    tool_calls: list[StreamToolDelta] | None = None
