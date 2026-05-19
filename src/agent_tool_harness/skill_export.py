from __future__ import annotations

from .models import Capability, HarnessTool


def render_skill(tool: HarnessTool, capability: Capability) -> str:
    examples = "\n".join(
        f"{idx}. `{example}`" for idx, example in enumerate(capability.examples, 1)
    )
    lower_summary = capability.summary[0].lower() + capability.summary[1:]
    verification_run = (
        f"agent-tool-harness run {capability.id} examples/github-trending.json "
        "--preview-dir /tmp/agent-tool-harness-preview --json"
    )
    return f"""---
name: {tool.name}
description: {tool.description}
capability: {capability.id}
---

## When to use
Use when an agent needs to {lower_summary}

## Inputs
Provide a JSON file matching the capability input schema.
For `{capability.id}`, the minimum useful shape contains `trend_summary` and `repos[]`.

## Commands
{examples}

Run the no-side-effect healthcheck first:

```bash
{tool.healthcheck}
```

## JSON output
All commands return the stable harness envelope:

```json
{{ "ok": true, "data": {{}}, "artifacts": [], "warnings": [], "next_actions": [] }}
```

Failures return:

```json
{{ "ok": false, "error": {{ "type": "...", "message": "...", "fix": "..." }} }}
```

## Artifacts
Successful file-producing runs emit a `{capability.preview_protocol}` directory.
It contains `manifest.json`, `summary.json`, and preview artifacts.

## Verification
Run:

```bash
agent-tool-harness doctor --all --json
{verification_run}
```
"""


def render_tool_skill(tool: HarnessTool) -> str:
    capability_lines = "\n".join(
        f"- `{capability.id}`: {capability.summary} side_effect={capability.side_effect}"
        for capability in tool.capabilities
    )
    read_capabilities = "\n".join(
        f"- `{capability.id}`"
        for capability in tool.capabilities
        if capability.side_effect != "external_write"
    )
    write_capabilities = "\n".join(
        f"- `{capability.id}`"
        for capability in tool.capabilities
        if capability.side_effect == "external_write"
    )
    skill_name = f"{tool.name}-harness"
    return f"""---
name: {skill_name}
description: Use ath to access {tool.display_name} capabilities safely through preview bundles.
---

## When to use
Use when an agent needs to call `{tool.name}` capabilities through `agent-tool-harness` / `ath`
instead of guessing raw commands.

## Required flow
1. Discover capabilities with `ath registry list --json` when unsure.
2. Run the no-side-effect doctor before using the tool:

```bash
ath doctor {tool.name} --json
```

3. Write an input JSON file.
4. Run the capability with `ath run <capability> <input.json> --preview-dir .preview --json`.
5. Read the returned `artifacts[0].path`, then inspect the bundle:

```bash
ath inspect <bundle-dir> --json
```

6. Use `summary.json` / `ath inspect` output to decide the next action.

## Capabilities
{capability_lines}

## Read / preview capabilities
{read_capabilities}

## Write-capable capabilities
{write_capabilities}

Do not run external_write capabilities without explicit user approval.
When approval is present, add `--allow-external-write`:

```bash
ath run distill.capture input.json --preview-dir .preview --allow-external-write --json
```

## Distill examples
Route a knowledge task before reading or writing:

```bash
cat > /tmp/distill-route-input.json <<'JSON'
{{"vault":"/home/jarl/all_in_one","intent":"记录一个最小进展"}}
JSON
ath run distill.route /tmp/distill-route-input.json --preview-dir .preview --json
ath inspect <bundle-dir> --json
```

Search the vault:

```bash
cat > /tmp/distill-search-input.json <<'JSON'
{{"vault":"/home/jarl/all_in_one","query":"agent-tool-harness","limit":5}}
JSON
ath run distill.search /tmp/distill-search-input.json --preview-dir .preview --json
ath inspect <bundle-dir> --json
```

## JSON output
All commands return the stable harness envelope:

```json
{{ "ok": true, "data": {{}}, "artifacts": [], "warnings": [], "next_actions": [] }}
```

Failures return:

```json
{{ "ok": false, "error": {{ "type": "...", "message": "...", "fix": "..." }} }}
```
"""
