from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class BackendSpec(BaseModel):
    kind: Literal["python_function", "subprocess"]
    target: str
    timeout_seconds: int = 300


class Capability(BaseModel):
    id: str
    name: str
    summary: str
    input_schema: dict[str, Any] = Field(default_factory=dict)
    side_effect: Literal["none", "local_files", "network", "external_write"] = "none"
    preview_protocol: str | None = None
    examples: list[str] = Field(default_factory=list)
    backend: BackendSpec | None = None


class HarnessTool(BaseModel):
    name: str
    display_name: str
    category: str
    description: str
    capabilities: list[Capability]
    healthcheck: str
    side_effects: dict[str, str] = Field(default_factory=dict)


class HarnessError(BaseModel):
    type: str
    message: str
    fix: str | None = None


class Artifact(BaseModel):
    kind: str
    path: str
    role: str | None = None
    id: str | None = None
    label: str | None = None


class HarnessResponse(BaseModel):
    ok: bool
    data: dict[str, Any] = Field(default_factory=dict)
    artifacts: list[Artifact] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    error: HarnessError | None = None

    @classmethod
    def success(
        cls,
        data: dict[str, Any] | None = None,
        artifacts: list[Artifact] | None = None,
        warnings: list[str] | None = None,
        next_actions: list[str] | None = None,
    ) -> HarnessResponse:
        return cls(
            ok=True,
            data=data or {},
            artifacts=artifacts or [],
            warnings=warnings or [],
            next_actions=next_actions or [],
        )

    @classmethod
    def failure(cls, error_type: str, message: str, fix: str | None = None) -> HarnessResponse:
        return cls(ok=False, error=HarnessError(type=error_type, message=message, fix=fix))
