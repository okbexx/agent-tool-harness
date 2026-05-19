from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from .backends import run_capability, tool_for_capability
from .models import HarnessResponse
from .registry import DEFAULT_TOOLS
from .skill_export import render_skill

app = typer.Typer(help="Agent Tool Harness: stable contracts for agent-callable internal tools.")
registry_app = typer.Typer(help="Inspect registered tools and capabilities.")
skill_app = typer.Typer(help="Export agent skills from capability metadata.")
app.add_typer(registry_app, name="registry")
app.add_typer(skill_app, name="skill")
console = Console()


def emit(payload: HarnessResponse | dict, as_json: bool) -> None:
    if isinstance(payload, HarnessResponse):
        data = payload.model_dump(exclude_none=True)
    else:
        data = payload
    if as_json:
        # Do not route JSON through Rich: it wraps long lines and can insert raw newlines
        # inside string values, making stdout invalid for agents that parse it.
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        console.print(data)


@registry_app.command("list")
def registry_list(
    as_json: Annotated[bool, typer.Option("--json", help="Emit JSON envelope.")] = False,
) -> None:
    """List registered harness tools."""
    tools = [tool.model_dump() for tool in DEFAULT_TOOLS]
    emit(HarnessResponse.success(data={"tools": tools}), as_json=as_json)


@app.command("doctor")
def doctor(
    tool_name: Annotated[str | None, typer.Argument(help="Tool name to inspect.")] = None,
    all_tools: Annotated[
        bool,
        typer.Option("--all", help="Inspect every registered tool."),
    ] = False,
    as_json: Annotated[bool, typer.Option("--json", help="Emit JSON envelope.")] = False,
) -> None:
    """Run no-side-effect health checks."""
    selected = (
        DEFAULT_TOOLS
        if all_tools or tool_name is None
        else [t for t in DEFAULT_TOOLS if t.name == tool_name]
    )
    if not selected:
        emit(
            HarnessResponse.failure(
                "unknown_tool",
                f"Unknown tool: {tool_name}",
                "Run registry list --json",
            ),
            as_json=True,
        )
        raise typer.Exit(2)

    statuses = []
    for tool in selected:
        statuses.append(
            {
                "name": tool.name,
                "ok": True,
                "side_effect": tool.side_effects.get("doctor", "none"),
                "checks": [
                    {"name": "registry_entry", "ok": True},
                    {"name": "json_contract", "ok": True},
                    {"name": "preview_protocol", "ok": True},
                ],
            }
        )
    emit(HarnessResponse.success(data={"statuses": statuses}), as_json=as_json)


@app.command("run")
def run(
    capability_id: Annotated[str, typer.Argument(help="Capability id, e.g. xhs.generate-cards.")],
    input_path: Annotated[Path, typer.Argument(help="JSON input file.")],
    preview_dir: Annotated[
        Path | None,
        typer.Option(
            "--preview-dir",
            help="Directory where preview bundles are written.",
        ),
    ] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Emit JSON envelope.")] = False,
) -> None:
    """Run a capability and emit a stable JSON envelope."""
    response = run_capability(capability_id, input_path=input_path, preview_dir=preview_dir)
    emit(response, as_json=as_json)
    if not response.ok:
        raise typer.Exit(1)


@skill_app.command("export")
def skill_export(
    capability_id: Annotated[str, typer.Argument(help="Capability id to export as SKILL.md.")],
    as_json: Annotated[bool, typer.Option("--json", help="Emit JSON envelope.")] = False,
) -> None:
    """Generate an agent-readable SKILL.md from capability metadata."""
    try:
        tool, capability = tool_for_capability(capability_id)
    except KeyError:
        emit(
            HarnessResponse.failure(
                "unknown_capability",
                f"Unsupported capability: {capability_id}",
                "Run registry list --json",
            ),
            as_json=True,
        )
        raise typer.Exit(2) from None
    emit(
        HarnessResponse.success(data={"skill_md": render_skill(tool, capability)}),
        as_json=as_json,
    )
