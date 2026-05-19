from __future__ import annotations

from .models import Capability, HarnessTool


def minimum_input_text(capability: Capability) -> str:
    required = capability.input_schema.get("required") or []
    labels = [f"`{name}`" for name in required]
    if not labels:
        return "the fields required by the input schema"
    if len(labels) == 1:
        return labels[0]
    return " and ".join([", ".join(labels[:-1]), labels[-1]])


def verification_command(capability: Capability) -> str:
    if capability.examples:
        return capability.examples[0]
    return (
        f"agent-tool-harness run {capability.id} input.json "
        "--preview-dir /tmp/agent-tool-harness-preview --json"
    )


def render_skill(tool: HarnessTool, capability: Capability) -> str:
    examples = "\n".join(
        f"{idx}. `{example}`" for idx, example in enumerate(capability.examples, 1)
    )
    lower_summary = capability.summary[0].lower() + capability.summary[1:]
    verification_run = verification_command(capability)
    minimum_shape = minimum_input_text(capability)
    return f"""---
name: {tool.name}
description: {tool.description}
capability: {capability.id}
---

## When to use
Use when an agent needs to {lower_summary}

## Inputs
Provide a JSON file matching the capability input schema.
For `{capability.id}`, the minimum useful shape contains {minimum_shape}.

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


def tool_examples(tool: HarnessTool) -> str:
    if tool.name == "xhs-image-cards":
        return """## XHS examples
Select the latest pending item that still needs images:

```bash
cat > /tmp/xhs-select-input.json <<'JSON'
{"pending_dir":"/home/jarl/.hermes/scripts/xhs-pipeline/pending"}
JSON
ath run xhs.select-pending /tmp/xhs-select-input.json --preview-dir .preview --json
ath inspect <bundle-dir> --json
```

Generate local image cards and inspect the bundle:

```bash
cat > /tmp/xhs-generate-input.json <<'JSON'
{"pending_file":"/home/jarl/.hermes/scripts/xhs-pipeline/pending/<file>.json"}
JSON
ath run xhs.generate-cards /tmp/xhs-generate-input.json --preview-dir .preview --json
ath inspect <bundle-dir> --json
```

Run QA and final preview gate before any publishing:

```bash
ath run xhs.image-qa /tmp/xhs-generate-input.json --preview-dir .preview --json
ath run xhs.finalize-preview /tmp/xhs-generate-input.json --preview-dir .preview --json
```

Publishing is external_write and requires explicit user approval:

```bash
ath run xhs.publish /tmp/xhs-generate-input.json \
  --preview-dir .preview --allow-external-write --json
```"""
    if tool.name == "distill-vault":
        return """## Distill examples
Route a knowledge task before reading or writing:

```bash
cat > /tmp/distill-route-input.json <<'JSON'
{"vault":"/home/jarl/all_in_one","intent":"记录一个最小进展"}
JSON
ath run distill.route /tmp/distill-route-input.json --preview-dir .preview --json
ath inspect <bundle-dir> --json
```

Search the vault:

```bash
cat > /tmp/distill-search-input.json <<'JSON'
{"vault":"/home/jarl/all_in_one","query":"agent-tool-harness","limit":5}
JSON
ath run distill.search /tmp/distill-search-input.json --preview-dir .preview --json
ath inspect <bundle-dir> --json
```"""
    if tool.name == "personal-site":
        return """## Personal site examples
Inspect repository status:

```bash
cat > /tmp/site-input.json <<'JSON'
{"site":"/home/jarl/personal-site"}
JSON
ath run site.status /tmp/site-input.json --preview-dir .preview --json
ath inspect <bundle-dir> --json
```

Check generated local links after a build:

```bash
ath run site.check-links /tmp/site-input.json --preview-dir .preview --json
ath inspect <bundle-dir> --json
```

Build or deploy only after explicit approval:

```bash
ath run site.build /tmp/site-input.json --preview-dir .preview --allow-external-write --json
ath run site.deploy /tmp/site-input.json --preview-dir .preview --allow-external-write --json
```"""
    return ""


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
    first_write = next(
        (
            capability.id
            for capability in tool.capabilities
            if capability.side_effect == "external_write"
        ),
        "<external-write-capability>",
    )
    examples = tool_examples(tool)
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
ath run {first_write} input.json --preview-dir .preview --allow-external-write --json
```

{examples}

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
