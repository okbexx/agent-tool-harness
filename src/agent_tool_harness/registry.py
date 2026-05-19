from .models import Capability, HarnessTool

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
                examples=[
                    "agent-tool-harness run xhs.generate-cards "
                    "examples/github-trending.json --preview-dir .preview --json"
                ],
            )
        ],
        healthcheck="agent-tool-harness doctor xhs-image-cards --json",
        side_effects={"doctor": "none", "xhs.generate-cards": "local_files"},
    )
]
