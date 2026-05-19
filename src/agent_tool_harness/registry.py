from .models import BackendSpec, Capability, HarnessTool


def _distill_input_schema(required_extra: list[str] | None = None) -> dict:
    required = ["vault", *(required_extra or [])]
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


def _distill_capability(
    capability_id: str,
    name: str,
    summary: str,
    side_effect: str = "local_files",
    required_extra: list[str] | None = None,
) -> Capability:
    return Capability(
        id=capability_id,
        name=name,
        summary=summary,
        input_schema=_distill_input_schema(required_extra),
        side_effect=side_effect,  # type: ignore[arg-type]
        preview_protocol="preview-bundle/v1",
        backend=BackendSpec(kind="python_function", target="run_distill_command"),
        examples=[
            f"agent-tool-harness run {capability_id} distill-input.json "
            "--preview-dir .preview --json"
        ],
    )


DISTILL_CAPABILITIES = [
    _distill_capability(
        "distill.status",
        "status",
        "Run distill status and bundle the JSON report.",
    ),
    _distill_capability(
        "distill.health",
        "health",
        "Run distill health and bundle the JSON report.",
    ),
    _distill_capability(
        "distill.capabilities",
        "capabilities",
        "Show engine capability surface and bundle the JSON report.",
    ),
    _distill_capability(
        "distill.instance-doctor",
        "instance_doctor",
        "Audit engine-to-instance runtime adoption.",
    ),
    _distill_capability("distill.upgrade-plan", "upgrade_plan", "Build the instance upgrade plan."),
    _distill_capability("distill.lint-check", "lint_check", "Run distill lint without fixes."),
    _distill_capability(
        "distill.lint-fix",
        "lint_fix",
        "Run distill lint with automatic fixes.",
        side_effect="external_write",
    ),
    _distill_capability(
        "distill.route",
        "route",
        "Plan the minimal read/write surface for an intent.",
        required_extra=["intent"],
    ),
    _distill_capability(
        "distill.plan",
        "plan",
        "Return the full action plan for an intent.",
        required_extra=["intent"],
    ),
    _distill_capability(
        "distill.search",
        "search",
        "Search vault objects and bundle the text results.",
        required_extra=["query"],
    ),
    _distill_capability("distill.promote-dry-run", "promote_dry_run", "Preview promotion queue."),
    _distill_capability(
        "distill.promote-auto",
        "promote_auto",
        "Auto-promote low-risk promotion queue items.",
        side_effect="external_write",
    ),
    _distill_capability(
        "distill.pipeline-run",
        "pipeline_run",
        "Run the distill pipeline and bundle the JSON report.",
    ),
    _distill_capability(
        "distill.capture",
        "capture",
        "Apply the minimal progress-capture path for an intent.",
        side_effect="external_write",
        required_extra=["intent"],
    ),
    _distill_capability(
        "distill.apply",
        "apply",
        "Alias for the minimal progress-capture write path.",
        side_effect="external_write",
        required_extra=["intent"],
    ),
]

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
]
