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
