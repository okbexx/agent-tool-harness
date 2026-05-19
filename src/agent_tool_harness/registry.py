from __future__ import annotations

from .capabilities import (
    DISTILL_CAPABILITY_SPECS,
    SITE_CAPABILITY_SPECS,
    XHS_CAPABILITY_SPECS,
    DistillCapabilitySpec,
    SiteCapabilitySpec,
    XhsCapabilitySpec,
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


def _xhs_input_schema(required: tuple[str, ...]) -> dict:
    return {
        "type": "object",
        "required": list(required),
        "properties": {
            "pending_file": {"type": "string", "description": "Path to an XHS pending JSON file."},
            "pending_dir": {
                "type": "string",
                "description": "Path to an XHS pending queue directory.",
            },
            "target": {
                "type": "string",
                "description": "Pending JSON or artifact directory for QA.",
            },
            "title": {
                "type": "string",
                "description": "Title substring for matching a pending item.",
            },
            "headed": {"type": "boolean", "description": "For publish: open a headed browser."},
            "dry_run": {
                "type": "boolean",
                "description": "For publish: call the publisher in dry-run mode.",
            },
            "timeout_seconds": {"type": "integer"},
        },
    }


def _xhs_capability(spec: XhsCapabilitySpec) -> Capability:
    return Capability(
        id=spec.id,
        name=spec.name,
        summary=spec.summary,
        input_schema=_xhs_input_schema(spec.required),
        side_effect=spec.side_effect,
        preview_protocol="preview-bundle/v1",
        backend=BackendSpec(kind="python_function", target="run_xhs_command"),
        examples=[f"agent-tool-harness run {spec.id} xhs-input.json --preview-dir .preview --json"],
    )


DISTILL_CAPABILITIES = [_distill_capability(spec) for spec in DISTILL_CAPABILITY_SPECS.values()]
SITE_CAPABILITIES = [_site_capability(spec) for spec in SITE_CAPABILITY_SPECS.values()]
XHS_CAPABILITIES = [_xhs_capability(spec) for spec in XHS_CAPABILITY_SPECS.values()]

DEFAULT_TOOLS = [
    HarnessTool(
        name="xhs-image-cards",
        display_name="XHS Image Cards Harness",
        category="content",
        description=(
            "Operate the local Xiaohongshu pending, card generation, QA, preview, "
            "and publish pipeline through inspectable bundles."
        ),
        capabilities=XHS_CAPABILITIES,
        healthcheck="agent-tool-harness doctor xhs-image-cards --json",
        side_effects={
            "doctor": "none",
            **{capability.id: capability.side_effect for capability in XHS_CAPABILITIES},
        },
    ),
    HarnessTool(
        name="distill-vault",
        display_name="Distill Vault Harness",
        category="knowledge-runtime",
        description=("Expose distill-vault CLI surfaces as inspectable agent capabilities."),
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
        description=("Operate Jarl's personal Astro site through inspectable preview bundles."),
        capabilities=SITE_CAPABILITIES,
        healthcheck="agent-tool-harness doctor personal-site --json",
        side_effects={
            "doctor": "none",
            **{capability.id: capability.side_effect for capability in SITE_CAPABILITIES},
        },
    ),
]
