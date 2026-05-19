from __future__ import annotations

from .capabilities import (
    DISTILL_CAPABILITY_SPECS,
    SITE_CAPABILITY_SPECS,
    DistillCapabilitySpec,
    SiteCapabilitySpec,
)
from .models import BackendSpec, Capability, HarnessTool


def _distill_input_schema(required_extra: tuple[str, ...] | None = None) -> dict:
    required = ["vault", *(required_extra or ())]
    return {
        "type": "object",
        "required": required,
        "properties": {
            "vault": {"type": "string", "description": "Path to the distill vault root."},
            "intent": {"type": "string"},
            "project": {"type": "string"},
            "query": {"type": "string"},
            "limit": {"type": "integer"},
            "type": {"type": "string"},
            "mode": {"type": "string", "enum": ["keyword", "semantic", "hybrid"]},
            "incremental": {"type": "boolean"},
            "worker_mode": {"type": "string", "enum": ["auto", "process", "thread", "serial"]},
            "workers": {"type": "integer"},
            "timeout_seconds": {"type": "integer"},
        },
    }


def _distill_capability(spec: DistillCapabilitySpec) -> Capability:
    return Capability(
        id=spec.id,
        name=spec.name,
        summary=spec.summary,
        input_schema=_distill_input_schema(spec.required_extra),
        side_effect=spec.side_effect,
        preview_protocol="preview-bundle/v1",
        backend=BackendSpec(kind="python_function", target="run_distill_command"),
        examples=[
            f"agent-tool-harness run {spec.id} distill-input.json --preview-dir .preview --json"
        ],
    )


def _site_input_schema() -> dict:
    return {
        "type": "object",
        "required": ["site"],
        "properties": {
            "site": {"type": "string", "description": "Path to the personal site repository."},
            "timeout_seconds": {"type": "integer"},
        },
    }


def _site_capability(spec: SiteCapabilitySpec) -> Capability:
    return Capability(
        id=spec.id,
        name=spec.name,
        summary=spec.summary,
        input_schema=_site_input_schema(),
        side_effect=spec.side_effect,
        preview_protocol="preview-bundle/v1",
        backend=BackendSpec(kind="python_function", target="run_site_command"),
        examples=[
            f"agent-tool-harness run {spec.id} site-input.json --preview-dir .preview --json"
        ],
    )


DISTILL_CAPABILITIES = [
    _distill_capability(spec) for spec in DISTILL_CAPABILITY_SPECS.values()
]
SITE_CAPABILITIES = [_site_capability(spec) for spec in SITE_CAPABILITY_SPECS.values()]

DEFAULT_TOOLS = [
    HarnessTool(
        name="xhs-image-cards",
        display_name="XHS Image Cards Harness",
        category="content",
        description=(
            "Generate Xiaohongshu image card preview bundles from trend summary "
            "and repo list."
        ),
        capabilities=[
            Capability(
                id="xhs.generate-cards",
                name="generate_cards",
                summary="Generate a preview bundle with XHS-ready card artifacts.",
                input_schema={
                    "type": "object",
                    "required": ["trend_summary", "repos"],
                    "properties": {
                        "trend_summary": {"type": "string"},
                        "repos": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "required": ["name"],
                                "properties": {
                                    "name": {"type": "string"},
                                    "stars": {"type": "integer"},
                                    "why": {"type": "string"},
                                },
                            },
                        },
                    },
                },
                side_effect="local_files",
                preview_protocol="preview-bundle/v1",
                backend=BackendSpec(kind="python_function", target="run_xhs_generate_cards"),
                examples=[
                    "agent-tool-harness run xhs.generate-cards "
                    "examples/github-trending.json --preview-dir .preview --json"
                ],
            )
        ],
        healthcheck="agent-tool-harness doctor xhs-image-cards --json",
        side_effects={"doctor": "none", "xhs.generate-cards": "local_files"},
    ),
    HarnessTool(
        name="distill-vault",
        display_name="Distill Vault Harness",
        category="knowledge-runtime",
        description=(
            "Expose distill-vault CLI surfaces as inspectable agent capabilities."
        ),
        capabilities=DISTILL_CAPABILITIES,
        healthcheck="agent-tool-harness doctor distill-vault --json",
        side_effects={
            "doctor": "none",
            **{capability.id: capability.side_effect for capability in DISTILL_CAPABILITIES},
        },
    ),
    HarnessTool(
        name="personal-site",
        display_name="Personal Site Harness",
        category="site-ops",
        description=(
            "Operate Jarl's personal Astro site through inspectable preview bundles."
        ),
        capabilities=SITE_CAPABILITIES,
        healthcheck="agent-tool-harness doctor personal-site --json",
        side_effects={
            "doctor": "none",
            **{capability.id: capability.side_effect for capability in SITE_CAPABILITIES},
        },
    ),
]
